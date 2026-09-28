"""Cache des lectures Google Sheets (quota de 60 lectures par minute pour tout le compte de service)."""

import threading

import pytest
from gspread.exceptions import APIError
from gspread.http_client import HTTPClient

from app import sheets
from app.sheets import CachedHTTPClient


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code, self.payload = status, payload or {}

    def json(self):
        return self.payload


@pytest.fixture
def client(monkeypatch):
    calls = []

    def fake_request(self, method, endpoint, params=None, **kwargs):
        calls.append((method, endpoint))
        if getattr(self, "quota_errors", 0):
            self.quota_errors -= 1
            raise APIError(FakeResponse(429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}))
        return FakeResponse(payload={"n": len(calls)})

    monkeypatch.setattr(HTTPClient, "request", fake_request)
    monkeypatch.setattr(sheets, "RETRY_WAITS", (0, 0, 0))
    sheets.clear_sheet_cache()
    c = object.__new__(CachedHTTPClient)  # sans identifiants Google
    c.calls = calls
    return c


def test_identical_reads_are_shared(client):
    first = client.request("get", "https://sheets/v4/abc/values/Titres", params={"valueRenderOption": "UNFORMATTED_VALUE"})
    again = client.request("get", "https://sheets/v4/abc/values/Titres", params={"valueRenderOption": "UNFORMATTED_VALUE"})
    other = client.request("get", "https://sheets/v4/abc/values/Positions")
    assert first is again and other is not first
    assert len(client.calls) == 2


def test_write_clears_cache(client):
    client.request("get", "https://sheets/v4/abc/values/Opérations")
    client.request("post", "https://sheets/v4/abc/values/Opérations:append")
    client.request("get", "https://sheets/v4/abc/values/Opérations")
    assert [m for m, _ in client.calls] == ["get", "post", "get"]


def test_expired_entries_are_read_again(client, monkeypatch):
    client.request("get", "https://sheets/v4/abc")
    monkeypatch.setattr(sheets, "CACHE_SECONDS", 0)
    client.request("get", "https://sheets/v4/abc")
    assert len(client.calls) == 2


def test_parallel_reads_make_one_call(client, monkeypatch):
    original = HTTPClient.request
    started = threading.Event()

    def slow(self, *args, **kwargs):
        started.set()
        threading.Event().wait(0.05)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(HTTPClient, "request", slow)
    threads = [threading.Thread(target=client.request, args=("get", "https://sheets/v4/abc")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(client.calls) == 1


def test_quota_exceeded_is_retried(client):
    client.quota_errors = 2
    assert client.request("get", "https://sheets/v4/abc").json() == {"n": 3}
    client.quota_errors = 9
    with pytest.raises(APIError):
        client.request("get", "https://sheets/v4/autre")
