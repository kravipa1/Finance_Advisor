# tests/test_normalizers.py
from sfa_utils.normalizers import normalize_amount, to_iso_date


def test_amount_normalization_us():
    a = normalize_amount("$1,234.56")
    assert a.currency == "USD"
    assert a.value is not None
    assert float(a.value) == 1234.56


def test_amount_normalization_inr_comma_decimal():
    a = normalize_amount("INR 1,234,56")
    assert a.currency == "INR"
    assert a.value is not None
    assert float(a.value) == 1234.56


def test_date_iso():
    assert to_iso_date("Dec 31, 2024") == "2024-12-31"
