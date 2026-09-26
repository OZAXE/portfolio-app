import pytest

from app.operations import OperationError, _positive, _non_negative


def test_positive_numbers_required():
    assert _positive("2.5", "Quantité") == 2.5
    with pytest.raises(OperationError):
        _positive(0, "Quantité")
    with pytest.raises(OperationError):
        _positive("abc", "Prix")


def test_fees_can_be_zero_not_negative():
    assert _non_negative(None, "Frais") == 0
    with pytest.raises(OperationError):
        _non_negative(-1, "Frais")
