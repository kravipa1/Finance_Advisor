# tests/test_doc_type_and_items.py
from parser.doc_type import score
from parser.lineitems import extract_line_items


def test_doc_type_scoring_invoice():
    s = score("INVOICE\nSubtotal: $90.00\nTotal: $100.00")
    assert s.kind == "invoice"
    assert s.invoice >= s.paystub


def test_lineitems_basic():
    lines = ["2 Widget A 19.99 39.98", "1 Service Plan 100.00 100.00"]
    items = extract_line_items(lines)
    assert len(items) == 2
    assert items[0]["qty"] == 2.0
    assert items[0]["line_total"]["value"] == 39.98
