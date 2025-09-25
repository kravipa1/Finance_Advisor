from adapters.legacy import LegacyAdapter


def test_legacy_adapter_minimal():
    text = "STARBUCKS 09/01/2025 Total $7.89 Latte"
    ad = LegacyAdapter()
    doc = ad.build(source_path="tests/data/receipt1.txt", ocr_text=text)
    assert doc.vendor
    assert doc.total is not None
    assert len(doc.line_items) >= 0
