# pipeline/runner.py
"""
End-to-end pipeline:
  (image|pdf) --OCR--> ocr_text/*.txt --normalize--> normalized_text/*.txt --extract--> parsed/*.json

CLI examples (run from repo root):
  # Single file (image/pdf/txt)
  python -m pipeline.runner --input data/samples/invoices/June_Forex.jpg

  # Batch a folder (mixed image/pdf/txt)
  python -m pipeline.runner --indir data/samples/invoices

  # Choose where outputs go (optional)
  python -m pipeline.runner --input data/samples/paystubs/paystub_us_01.pdf \
      --ocrdir data/interim/ocr_text --normdir data/interim/normalized_text --parsedir data/interim/parsed
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple

# Import our modules
from ocr.reader import Reader as OCRReader
from parser.normalizer import normalize_file as normalize_txt_file
from parser.extractor import extract_file as extract_struct

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}
TXT_EXTS = {".txt"}


def ensure_dirs(ocrdir: Path, normdir: Path, parsedir: Path) -> None:
    ocrdir.mkdir(parents=True, exist_ok=True)
    normdir.mkdir(parents=True, exist_ok=True)
    parsedir.mkdir(parents=True, exist_ok=True)


def run_pipeline_for_file(
    inp: Path,
    ocrdir: Path,
    normdir: Path,
    parsedir: Path,
    languages: list[str] | None = None,
    gpu: bool = False,
    min_confidence: float = 0.5,
    paragraph: bool = True,
    dpi: int = 200,
) -> Tuple[Path | None, Path, Path]:
    """
    Returns: (ocr_txt_path or None if input was already .txt, normalized_txt_path, parsed_json_path)
    """
    ext = inp.suffix.lower()

    # Stage 1: OCR (only for image/pdf)
    if ext in IMAGE_EXTS or ext in PDF_EXTS:
        reader = OCRReader(
            languages=languages or ["en"],
            gpu=gpu,
            min_confidence=min_confidence,
            paragraph=paragraph,
            dpi=dpi,
        )
        spans = reader.read(inp)
        raw_text = reader.to_plaintext(spans)
        ocr_txt_path = ocrdir / f"{inp.stem}.txt"
        ocr_txt_path.write_text(raw_text, encoding="utf-8")
    elif ext in TXT_EXTS:
        ocr_txt_path = inp  # already text, skip OCR
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Stage 2: Normalize
    norm_txt_path = normalize_txt_file(ocr_txt_path, normdir)

    # Stage 3: Extract
    parsed_json_path = extract_struct(norm_txt_path, parsedir)

    return (None if ext in TXT_EXTS else ocr_txt_path, norm_txt_path, parsed_json_path)


def run_pipeline_for_dir(
    indir: Path,
    ocrdir: Path,
    normdir: Path,
    parsedir: Path,
    **kw,
) -> List[Path]:
    outputs: List[Path] = []
    for p in sorted(indir.iterdir()):
        if p.is_dir():
            continue
        if p.suffix.lower() in IMAGE_EXTS | PDF_EXTS | TXT_EXTS:
            _, _, out_json = run_pipeline_for_file(p, ocrdir, normdir, parsedir, **kw)
            outputs.append(out_json)
    return outputs


def _cli():
    ap = argparse.ArgumentParser(
        description="Run OCR → normalize → extract in one command"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input", help="Path to a single file (image/pdf/txt)")
    g.add_argument("--indir", help="Directory containing files (image/pdf/txt)")

    ap.add_argument(
        "--ocrdir", default="data/interim/ocr_text", help="Where to write raw OCR .txt"
    )
    ap.add_argument(
        "--normdir",
        default="data/interim/normalized_text",
        help="Where to write normalized .txt",
    )
    ap.add_argument(
        "--parsedir", default="data/interim/parsed", help="Where to write parsed .json"
    )

    # OCR tuning (optional)
    ap.add_argument(
        "--lang", nargs="+", default=["en"], help="EasyOCR languages (e.g., en hi)"
    )
    ap.add_argument(
        "--gpu", action="store_true", help="Use GPU for EasyOCR (requires CUDA)"
    )
    ap.add_argument(
        "--min-conf",
        type=float,
        default=0.5,
        help="Min confidence threshold for OCR spans",
    )
    ap.add_argument(
        "--no-paragraph", action="store_true", help="Disable EasyOCR paragraph mode"
    )
    ap.add_argument("--dpi", type=int, default=200, help="PDF render DPI for OCR")

    args = ap.parse_args()

    ocrdir = Path(args.ocrdir)
    normdir = Path(args.normdir)
    parsedir = Path(args.parsedir)
    ensure_dirs(ocrdir, normdir, parsedir)

    if args.input:
        inp = Path(args.input)
        if not inp.exists():
            raise FileNotFoundError(f"Input not found: {inp}")
        ocr_p, norm_p, json_p = run_pipeline_for_file(
            inp,
            ocrdir,
            normdir,
            parsedir,
            languages=args.lang,
            gpu=args.gpu,
            min_confidence=args.min_conf,
            paragraph=not args.no_paragraph,
            dpi=args.dpi,
        )
        print("[OK] Pipeline complete")
        if ocr_p:
            print(f" • OCR:        {ocr_p}")
        print(f" • Normalized: {norm_p}")
        print(f" • Parsed:     {json_p}")
    else:
        indir = Path(args.indir)
        if not indir.exists():
            raise FileNotFoundError(f"Input dir not found: {indir}")
        outs = run_pipeline_for_dir(
            indir,
            ocrdir,
            normdir,
            parsedir,
            languages=args.lang,
            gpu=args.gpu,
            min_confidence=args.min_conf,
            paragraph=not args.no_paragraph,
            dpi=args.dpi,
        )
        print(f"[OK] Pipeline complete for {len(outs)} files -> {parsedir}")


if __name__ == "__main__":
    _cli()
