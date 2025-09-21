# tests/test_ocr_reader.py
import pytest


@pytest.mark.usefixtures("fake_easyocr")
def test_read_image_text_returns_joined_lines(sample_invoice_image):
    from ocr.reader import read_image_text

    text = read_image_text(sample_invoice_image)
    assert "ITEM A 2 x 3.50" in text
    assert "ITEM B 1 x 10.00" in text
    assert "Total 18.53" in text
