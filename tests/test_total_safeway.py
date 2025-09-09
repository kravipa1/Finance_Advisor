# tests/test_total_safeway.py
from parser.extractor import extract_from_text


def test_safeway_total_is_1794():
    text = open("tests/fixtures/safeway_norm.txt", encoding="utf-8").read()
    data = extract_from_text(text)
    assert data["total"]["value"] == 17.94
