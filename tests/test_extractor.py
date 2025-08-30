# tests/test_extractor.py
from parser.extractor import extract_from_text


def test_invoice_total_detection():
    txt = "INVOICE\nSubtotal: $90.00\nTax: $10.00\nTotal: $100.00"
    data = extract_from_text(txt)
    assert data["kind"] == "invoice"
    assert "100.00" in (data["total"] or "")


def test_paystub_detection():
    txt = "EMPLOYER XYZ\nEmployee: Jane Doe\nPay Period: 01/01/2024 to 01/15/2024\nNet Pay: $1234.56"
    data = extract_from_text(txt)
    assert data["kind"] == "paystub"
    assert "1234.56" in (data["net_pay"] or "")
