# pipeline/process_file.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Tuple

from ocr.reader import Reader as OCRReader
from parser.normalizer import normalize_file as normalize_txt_file
from parser.extractor import extract_file as extract_struct
from sfa_utils.categorizer import apply_categories


def process_file(
    inp: Path,
    ocrdir: Path,
    normdir: Path,
    parsedir: Path,
    languages: list[str] | None = None,
    gpu: bool = False,
    min_confidence: float = 0.5,
    paragraph: bool = True,
    dpi: int = 200,
) -> Tuple[Path | None, Path, Path, Dict[str, Any]]:
    """
    Runs the same stages as pipeline.runner but returns the final JSON data
    with categories applied (and still writes normalized + parsed files).
    """
    ext = inp.suffix.lower()
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    PDF_EXTS = {".pdf"}
    TXT_EXTS = {".txt"}

    # Stage 1: OCR (if needed)
    if ext in IMAGE_EXTS | PDF_EXTS:
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
        ocr_txt_path.parent.mkdir(parents=True, exist_ok=True)
        ocr_txt_path.write_text(raw_text, encoding="utf-8")
    elif ext in TXT_EXTS:
        ocr_txt_path = inp
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Stage 2: normalize
    norm_txt_path = normalize_txt_file(ocr_txt_path, normdir)

    # Stage 3: extract JSON
    parsed_json_path = extract_struct(norm_txt_path, parsedir)

    # Load and categorize for return
    data = json.loads(parsed_json_path.read_text(encoding="utf-8"))
    data = apply_categories(data)
    return (
        None if ext in TXT_EXTS else ocr_txt_path,
        norm_txt_path,
        parsed_json_path,
        data,
    )
