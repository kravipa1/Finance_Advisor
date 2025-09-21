# tests/test_lineitems.py
from parser import lineitems as li

SIMPLE_TEXT = """ITEM A 2 x 3.50
ITEM B 1 x 10.00
Subtotal 17.00
Tax 1.53
Total 18.53
"""


def test_parse_line_items_basic():
    items, totals = li.parse_line_items(SIMPLE_TEXT)
    assert items and isinstance(items, list)
    a = next(i for i in items if i["name"].startswith("ITEM A"))
    assert a["qty"] == 2 and abs(a["unit_price"] - 3.50) < 1e-6
    assert abs(totals["subtotal"] - 17.00) < 1e-6
    assert abs(totals["tax"] - 1.53) < 1e-6
    assert abs(totals["total"] - 18.53) < 1e-6


def test_extract_line_items_varied_patterns():
    lines = [
        "2 Widget A 19.99 39.98",  # qty unit total
        "Widget B $4.00 x 3 .... $12.00",  # multiplicative
        "Bananas 2.97 lb @ 0.59/lb .... 1.75",  # weighted
        "Subtotal 53.73",
    ]
    out = li.extract_line_items(lines)
    assert out and isinstance(out, list)
    names = [r["desc"] for r in out]
    assert any("Widget A" in n for n in names)
    assert any("Widget B" in n for n in names)
    assert any("Bananas" in n for n in names)
