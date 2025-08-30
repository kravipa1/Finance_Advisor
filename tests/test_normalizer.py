# tests/test_normalizer.py
from parser.normalizer import normalize_text


def test_hyphen_breaks_removed():
    raw = "Total pay-\nment due"
    out = normalize_text(raw)
    assert "payment" in out
    assert "pay-\nment" not in out


def test_page_header_removed():
    raw = "--- Page 1 ---\nHello\n--- Page 2 ---\nWorld"
    out = normalize_text(raw)
    assert "--- Page" not in out
    assert "Hello" in out and "World" in out
