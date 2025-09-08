# ocr/reader.py
"""
EasyOCR-powered reader for images and PDFs.

CLI usage (run from repo root):
  python -m ocr.reader --input data/samples/paystubs/paystub_us_01.pdf --outdir data/interim/ocr_text

Outputs:
  Writes a UTF-8 .txt file into the --outdir with the same basename as the input.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union, cast, Any

import numpy as np
from PIL import Image, UnidentifiedImageError
import fitz  # PyMuPDF
import easyocr
import cv2


# ---------------------------- Data structures ----------------------------


@dataclass
class OCRSpan:
    """One recognized text span with metadata."""

    text: str
    confidence: float
    bbox: List[Tuple[float, float]]  # 4 points: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    page: int


# ------------------------------- Reader ----------------------------------


# put this above the class or anywhere at module top level
def _preprocess(np_img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
    gray = cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    thr = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 10
    )
    return cv2.cvtColor(thr, cv2.COLOR_GRAY2RGB)


class Reader:
    """
    Wraps EasyOCR for image and PDF OCR.

    Args:
        languages: ISO codes for languages, e.g. ['en'] or ['en','hi'].
        gpu: Use GPU only if CUDA is properly installed. Default False (CPU).
        min_confidence: Drop spans below this confidence (0..1).
        paragraph: Merge lines into paragraphs if supported by the EasyOCR version.
        dpi: When rendering PDFs to images, DPI controls sharpness/speed.
    """

    def __init__(
        self,
        languages: Optional[List[str]] = None,
        gpu: bool = False,
        min_confidence: float = 0.5,
        paragraph: bool = True,
        dpi: int = 200,
    ):
        self.languages = languages or ["en"]
        self.min_confidence = float(min_confidence)
        self.paragraph = bool(paragraph)
        self.dpi = int(dpi)

        # Initialize EasyOCR model (downloads on first run)
        # verbose=False → quieter model download logs
        self._reader = easyocr.Reader(self.languages, gpu=gpu, verbose=False)

    # ----------------------------- Public API -----------------------------

    def read(self, path: Union[str, Path]) -> List[OCRSpan]:
        """Auto-detect by extension and run OCR."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Input not found: {path}")

        ext = path.suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}:
            return self.read_image(path)
        elif ext == ".pdf":
            return self.read_pdf(path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    def read_image(self, image_path: Union[str, Path]) -> List[OCRSpan]:
        """OCR a single image file."""
        image_path = Path(image_path)
        try:
            img = Image.open(image_path).convert("RGB")
        except UnidentifiedImageError as e:
            raise ValueError(f"Cannot open image: {image_path}") from e

        np_img = np.array(img)
        np_img = _preprocess(np_img)
        spans = self._run_easyocr(np_img, page=1)
        return spans

    def read_pdf(self, pdf_path: Union[str, Path]) -> List[OCRSpan]:
        """OCR a multi-page PDF by rendering each page to an RGB image."""
        pdf_path = Path(pdf_path)
        spans: List[OCRSpan] = []

        with fitz.open(pdf_path) as doc:
            zoom = self.dpi / 72.0  # 72 dpi is PDF default
            mat = fitz.Matrix(zoom, zoom)

            # Use explicit indexing so static type checkers don't complain.
            for i in range(doc.page_count):
                page = cast(Any, doc.load_page(i))
                pix = page.get_pixmap(matrix=mat, alpha=False)
                mode = "RGB" if pix.n < 4 else "RGBA"

                # NOTE: pass a tuple (w, h) to satisfy Pylance
                img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                if mode == "RGBA":
                    img = img.convert("RGB")

                np_img = np.array(img)
                np_img = _preprocess(np_img)
                spans.extend(self._run_easyocr(np_img, page=i + 1))
        return spans

    def to_plaintext(self, spans: List[OCRSpan]) -> str:
        """Join OCR spans into readable plaintext, grouped by page."""
        if not spans:
            return ""

        pages = {}
        for s in spans:
            pages.setdefault(s.page, []).append(s)

        lines: List[str] = []
        for page_num in sorted(pages):
            lines.append(f"--- Page {page_num} ---")
            # Using returned order (roughly reading order)
            for s in pages[page_num]:
                if s.text:
                    lines.append(s.text)
            lines.append("")  # blank line between pages
        return "\n".join(lines).strip()

    # ----------------------------- Internals ------------------------------

    def _run_easyocr(self, np_img: np.ndarray, page: int) -> List[OCRSpan]:
        """
        Call EasyOCR and normalize outputs across versions.

        EasyOCR typically returns, per span:
          [bbox, text, confidence]
        but in some versions (esp. with paragraph=True) certain items can be:
          [bbox, text]
        We accept both; when confidence is missing we default to 1.0.
        """
        results = self._reader.readtext(np_img, detail=1, paragraph=self.paragraph)

        spans: List[OCRSpan] = []
        for item in results:
            bbox = None
            text = None
            conf = None

            # Accept tuples/lists or dicts (defensive)
            if isinstance(item, (list, tuple)):
                if len(item) == 3:
                    bbox, text, conf = item
                elif len(item) == 2:
                    bbox, text = item
                    conf = 1.0
                else:
                    # Unknown shape; skip
                    continue
            elif isinstance(item, dict):
                bbox = item.get("box") or item.get("bbox")
                text = item.get("text")
                conf = item.get("confidence") or item.get("conf") or 1.0
            else:
                continue

            if text is None or bbox is None:
                continue

            try:
                conf_f = float(conf) if conf is not None else 1.0
            except Exception:
                conf_f = 1.0

            if conf_f < self.min_confidence:
                continue

            spans.append(
                OCRSpan(text=text.strip(), confidence=conf_f, bbox=bbox, page=page)
            )

        return spans


# --------------------------------- CLI -----------------------------------


def _cli():
    p = argparse.ArgumentParser(description="Run EasyOCR on an image or PDF.")
    p.add_argument(
        "--input", required=True, help="Path to an image (.jpg/.png) or PDF (.pdf)"
    )
    p.add_argument(
        "--outdir",
        default="data/interim/ocr_text",
        help="Directory to write .txt output",
    )
    p.add_argument(
        "--lang",
        nargs="+",
        default=["en"],
        help="Language codes for EasyOCR (e.g., en hi)",
    )
    p.add_argument(
        "--gpu", action="store_true", help="Use GPU (only if CUDA is set up)"
    )
    p.add_argument(
        "--min_conf", type=float, default=0.5, help="Minimum confidence to keep a span"
    )
    p.add_argument(
        "--no-paragraph", action="store_true", help="Disable paragraph grouping"
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Render DPI for PDF pages (higher = sharper & slower)",
    )
    args = p.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    reader = Reader(
        languages=args.lang,
        gpu=args.gpu,
        min_confidence=args.min_conf,
        paragraph=not args.no_paragraph,
        dpi=args.dpi,
    )

    spans = reader.read(inp)
    text = reader.to_plaintext(spans)

    out_path = outdir / (inp.stem + ".txt")
    out_path.write_text(text, encoding="utf-8")

    print(f"[OK] OCR complete -> {out_path}")


if __name__ == "__main__":
    _cli()
