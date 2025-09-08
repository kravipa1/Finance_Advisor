from sfa_utils.categorizer import apply_categories


def test_vendor_and_keyword_categories():
    doc = {
        "kind": "invoice",
        "vendor": "Uber Technologies",
        "line_items": [
            {
                "desc": "Service Fee",
                "line_total": {"raw": "$2.00", "value": 2.0, "currency": "USD"},
            }
        ],
    }
    out = apply_categories(doc)
    assert out.get("category") == "Transport"
    assert out["line_items"][0]["category"] == "Fees"
