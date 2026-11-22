"""Dernier calcul de l'onglet Perf. gardé dans l'onglet Réglages (stats_store.py)."""

import json

from app import sheets, stats_store


class FakeTab:
    def __init__(self, rows):
        self.rows = rows

    def get_values(self):
        return self.rows

    def update(self, range_name, values, value_input_option=None):
        n = int(range_name[1:range_name.index(":")])
        self.rows[n - 1] = list(values[0])

    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))


def fake_tab(monkeypatch, rows):
    tab = FakeTab(rows)
    monkeypatch.setattr(stats_store, "_settings_tab", lambda sheet_id, create: tab)
    return tab


def test_garde_puis_relit_le_calcul(monkeypatch):
    tab = fake_tab(monkeypatch, [["CLÉ", "VALEUR"], ["push", "{}"]])
    result = {"envelopes": {"PEA": {"ytd": 0.084}}, "attribution": {}}
    assert stats_store.save_stats("s", "world", result)
    assert tab.rows[2][0] == "stats:world"  # ajouté sous les autres réglages, sans y toucher
    stored = stats_store.load_stats("s", "world")
    assert stored["result"] == result and stored["stored_at"]
    # Second calcul : la même ligne est remplacée, pas une ligne de plus
    stats_store.save_stats("s", "world", {"envelopes": {}, "attribution": {}})
    assert len(tab.rows) == 3 and json.loads(tab.rows[2][1])["result"]["envelopes"] == {}
    assert stats_store.load_stats("s", "sp500") is None  # autre indice : jamais calculé


def test_trop_gros_pour_une_cellule(monkeypatch):
    tab = fake_tab(monkeypatch, [["CLÉ", "VALEUR"]])
    assert not stats_store.save_stats("s", "world", {"lignes": ["x" * 100] * 600})  # 60 000 caractères
    assert len(tab.rows) == 1


def test_valeur_illisible_ignoree(monkeypatch):
    fake_tab(monkeypatch, [["CLÉ", "VALEUR"], ["stats:world", "{pas du json"]])
    assert stats_store.load_stats("s", "world") is None


def test_ecriture_neutre_ne_change_pas_la_generation():
    # Garder la Perf. ne doit pas invalider les calculs en mémoire (dont la Perf. elle-même)
    before = sheets.cache_generation()
    with sheets.neutral_writes():
        sheets.clear_sheet_cache(bump=not sheets._neutral.on)
    assert sheets.cache_generation() == before
    sheets.clear_sheet_cache()
    assert sheets.cache_generation() == before + 1
