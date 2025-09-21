# tests/test_normalizers.py
from sfa_utils.normalizers import (
    normalize_amount,
    Amount,
    to_iso_date,
    _fix_currency_ocr,
)


def test_currency_and_amounts():
    amt = normalize_amount("$1,234.50")
    assert isinstance(amt, Amount)
    assert amt.value == 1234.50
    assert amt.currency == "USD"


def test_negatives_and_parens():
    assert normalize_amount("-3.25").value == -3.25
    assert normalize_amount("(3.25)").value == -3.25


def test_currency_ocr_fix_s_to_dollar():
    assert _fix_currency_ocr("S 17.94").startswith("$")
    assert _fix_currency_ocr("5 0.95").startswith("$")


def test_date_parsing_to_iso():
    assert to_iso_date("2021-05-17") == "2021-05-17"
    assert to_iso_date("May 5, 21") == "2021-05-05"
    assert to_iso_date("12/31/2020") == "2020-12-31"
