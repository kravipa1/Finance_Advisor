from parser.lineitems import extract_line_items


def test_weighted_and_sections():
    lines = [
        "PRODUCE",
        "Bananas 2.00 lb @ 0.50/lb 1.00",
        "Tomatoes 1.50 lb @ 2.00/lb 3.00",
    ]
    items = extract_line_items(lines)
    assert len(items) == 2
    assert items[0].get("section") == "PRODUCE"
    assert items[0]["qty"] == 2.0
    assert items[0]["unit_price"]["value"] == 0.50
    assert items[0]["line_total"]["value"] == 1.00
    assert items[1]["qty"] == 1.5
    assert items[1]["unit_price"]["value"] == 2.00
    assert items[1]["line_total"]["value"] == 3.00
