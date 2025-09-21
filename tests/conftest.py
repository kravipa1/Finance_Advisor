# tests/conftest.py
import importlib
import sys
import types
import pytest

# Try to draw a tiny PNG; if Pillow isn't available, we'll still stub OCR.
try:
    from PIL import Image, ImageDraw

    _PIL = True
except Exception:
    Image = None
    ImageDraw = None
    _PIL = False


@pytest.fixture(scope="session")
def tmp_workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("sfa_ws")
    (root / "invoices").mkdir()
    (root / "out").mkdir()
    return root


@pytest.fixture(scope="session")
def sample_invoice_txt(tmp_path_factory):
    root = tmp_path_factory.mktemp("sfa_ws")
    (root / "invoices").mkdir()
    p = root / "invoices" / "inv001.txt"
    p.write_text(
        "ITEM A 2 x 3.50\nITEM B 1 x 10.00\nSubtotal 17.00\nTax 1.53\nTotal 18.53\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture(scope="session")
def sample_invoice_image(tmp_workspace):
    """Tiny PNG for OCR tests. EasyOCR is stubbed, so content can be minimal."""
    img_path = tmp_workspace / "invoices" / "inv001.png"
    if _PIL:
        img = Image.new("RGB", (800, 300), "white")
        d = ImageDraw.Draw(img)
        d.text(
            (20, 20),
            "ITEM A 2 x 3.50\nITEM B 1 x 10.00\nSubtotal 17.00\nTax 1.53\nTotal 18.53",
            fill="black",
        )
        img.save(img_path)
    else:
        img_path.write_bytes(b"placeholder")
    return img_path


class _FakeEasyOCRReader:
    def __init__(self, *_, **__):
        pass

    def readtext(self, image_path, detail=1, paragraph=False):
        lines = [
            "ITEM A 2 x 3.50",
            "ITEM B 1 x 10.00",
            "Subtotal 17.00",
            "Tax 1.53",
            "Total 18.53",
        ]
        return [([(0, 0), (1, 0), (1, 1), (0, 1)], t, 0.95) for t in lines]


@pytest.fixture
def fake_easyocr(monkeypatch):
    # Create a fake 'easyocr' module that provides Reader
    fake = types.ModuleType("easyocr")
    fake.Reader = _FakeEasyOCRReader
    monkeypatch.setitem(sys.modules, "easyocr", fake)

    # Reload our wrapper so it picks up the fake module no matter how it imports
    import ocr.reader as reader_mod

    importlib.reload(reader_mod)
    return _FakeEasyOCRReader
