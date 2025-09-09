# ocr/reader.py
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
from math import floor


@dataclass
class OCRSpan:
    text: str
    confidence: float
    bbox: List[Tuple[float, float]]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    page: int


def _preprocess_strong(np_img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
    gray = cv2.bilateralFilter(gray, d=7, sigmaColor=50, sigmaSpace=50)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    thr = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 10
    )
    return cv2.cvtColor(thr, cv2.COLOR_GRAY2RGB)


def _dedupe_spans(spans: List[OCRSpan]) -> List[OCRSpan]:
    # de-dupe by (lowercased text, quantized center), keep highest confidence
    best = {}
    for s in spans:
        xs = [p[0] for p in s.bbox]
        ys = [p[1] for p in s.bbox]
        cx, cy = (sum(xs) / 4.0, sum(ys) / 4.0)
        key = (s.text.strip().lower(), s.page, floor(cx / 10), floor(cy / 10))
        if key not in best or s.confidence > best[key].confidence:
            best[key] = s
    return list(best.values())


class Reader:
    def __init__(
        self,
        languages: Optional[List[str]] = None,
        gpu: bool = False,
        min_confidence: float = 0.45,  # slightly lower to catch faint decimals
        paragraph: bool = False,  # keep rows separate for receipts
        dpi: int = 200,
    ):
        self.languages = languages or ["en"]
        self.min_confidence = float(min_confidence)
        self.paragraph = bool(paragraph)
        self.dpi = int(dpi)
        self._reader = easyocr.Reader(self.languages, gpu=gpu, verbose=False)

    def read(self, path: Union[str, Path]) -> List[OCRSpan]:
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
        image_path = Path(image_path)
        try:
            img = Image.open(image_path).convert("RGB")
        except UnidentifiedImageError as e:
            raise ValueError(f"Cannot open image: {image_path}") from e

        np_img = np.array(img)

        # Dual-pass OCR: raw RGB and strong-contrast variant
        variants = [np_img, _preprocess_strong(np_img)]
        all_spans: List[OCRSpan] = []
        for npv in variants:
            all_spans.extend(self._run_easyocr(npv, page=1))

        return _dedupe_spans(all_spans)

    def read_pdf(self, pdf_path: Union[str, Path]) -> List[OCRSpan]:
        pdf_path = Path(pdf_path)
        spans: List[OCRSpan] = []
        with fitz.open(pdf_path) as doc:
            zoom = self.dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            for i in range(doc.page_count):
                page = cast(Any, doc.load_page(i))
                pix = page.get_pixmap(matrix=mat, alpha=False)
                mode = "RGB" if pix.n < 4 else "RGBA"
                img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                if mode == "RGBA":
                    img = img.convert("RGB")
                np_img = np.array(img)

                # Dual-pass per page
                for npv in (np_img, _preprocess_strong(np_img)):
                    spans.extend(self._run_easyocr(npv, page=i + 1))
        return _dedupe_spans(spans)

    def to_plaintext(self, spans: List[OCRSpan]) -> str:
        if not spans:
            return ""
        pages = {}
        for s in spans:
            pages.setdefault(s.page, []).append(s)
        lines: List[str] = []
        for page_num in sorted(pages):
            for s in pages[page_num]:
                if s.text:
                    lines.append(s.text)
        return "\n".join(lines).strip()

    def _run_easyocr(self, np_img: np.ndarray, page: int) -> List[OCRSpan]:
        results = self._reader.readtext(np_img, detail=1, paragraph=self.paragraph)
        spans: List[OCRSpan] = []
        for item in results:
            if isinstance(item, (list, tuple)):
                if len(item) == 3:
                    bbox, text, conf = item
                elif len(item) == 2:
                    bbox, text = item
                    conf = 1.0
                else:
                    continue
            elif isinstance(item, dict):
                bbox = item.get("box") or item.get("bbox")
                text = item.get("text")
                conf = item.get("confidence") or item.get("conf") or 1.0
            else:
                continue

            if not text or bbox is None:
                continue
            try:
                conf_f = float(conf)
            except Exception:
                conf_f = 1.0
            if conf_f < self.min_confidence:
                continue

            spans.append(
                OCRSpan(text=text.strip(), confidence=conf_f, bbox=bbox, page=page)
            )
        return spans


def _cli():
    p = argparse.ArgumentParser(description="Run EasyOCR on an image or PDF.")
    p.add_argument("--input", required=True)
    p.add_argument("--outdir", default="data/interim/ocr_text")
    p.add_argument("--lang", nargs="+", default=["en"])
    p.add_argument("--gpu", action="store_true")
    p.add_argument("--min_conf", type=float, default=0.45)
    p.add_argument("--no-paragraph", action="store_true")
    p.add_argument("--dpi", type=int, default=200)
    args = p.parse_args()
    reader = Reader(
        languages=args.lang,
        gpu=args.gpu,
        min_confidence=args.min_conf,
        paragraph=not args.no_paragraph,
        dpi=args.dpi,
    )
    spans = reader.read(args.input)
    text = reader.to_plaintext(spans)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / (Path(args.input).stem + ".txt")
    out_path.write_text(text, encoding="utf-8")
    print(f"[OK] OCR complete -> {out_path}")


if __name__ == "__main__":
    _cli()
