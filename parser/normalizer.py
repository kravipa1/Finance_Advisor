# parser/normalizer.py
"""
Normalize raw OCR text into a cleaner form for parsing.

Usage (CLI):
  python -m parser.normalizer --input data/interim/ocr_text/June_Forex.txt --outdir data/interim/normalized_text
"""

from __future__ import annotations
import argparse
from pathlib import Path
import re


def normalize_text(text: str) -> str:
    """Apply a series of cleanup rules to OCR text."""

    # 1. Remove EasyOCR page markers like '--- Page 1 ---'
    text = re.sub(r"--- Page \d+ ---", "", text)

    # 2. Fix hyphenated line breaks: e.g. 'pay-\nment' -> 'payment'
    text = re.sub(r"-\s*\n\s*", "", text)

    # 3. Collapse multiple spaces/tabs into one
    text = re.sub(r"[ \t]+", " ", text)

    # 4. Normalize newlines: collapse 2+ newlines into just 1
    text = re.sub(r"\n\s*\n+", "\n", text)

    # 5. Strip leading/trailing whitespace
    return text.strip()


def normalize_file(input_path: Path, outdir: Path) -> Path:
    """Read OCR .txt file, normalize it, and save cleaned version."""
    text = input_path.read_text(encoding="utf-8", errors="ignore")
    norm = normalize_text(text)

    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / input_path.name
    out_path.write_text(norm, encoding="utf-8")
    return out_path


def _cli():
    p = argparse.ArgumentParser(description="Normalize OCR text files for parsing")
    p.add_argument("--input", required=True, help="Path to OCR .txt file")
    p.add_argument(
        "--outdir",
        default="data/interim/normalized_text",
        help="Directory for cleaned output",
    )
    args = p.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir)

    if not inp.exists():
        raise FileNotFoundError(f"Input not found: {inp}")

    out_path = normalize_file(inp, outdir)
    print(f"[OK] Normalized text saved -> {out_path}")


if __name__ == "__main__":
    _cli()
