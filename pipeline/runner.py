# pipeline/runner.py
"""
End-to-end pipeline:
  (image|pdf) --OCR--> ocr_text/*.txt --normalize--> normalized_text/*.txt --extract--> parsed/*.json

CLI examples (run from repo root):
  python -m pipeline.runner --input data/samples/invoices/June_Forex.jpg
  python -m pipeline.runner --indir data/samples/invoices
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from statistics import mean
from typing import List, Tuple

from config.loader import load_config
from sfa_utils.logging_setup import setup_logging

from ocr.reader import Reader as OCRReader, OCRSpan
from parser.normalizer import normalize_file as normalize_txt_file
from parser.extractor import extract_file as extract_struct

log = logging.getLogger("pipeline")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}
TXT_EXTS = {".txt"}


def ensure_dirs(ocrdir: Path, normdir: Path, parsedir: Path) -> None:
    ocrdir.mkdir(parents=True, exist_ok=True)
    normdir.mkdir(parents=True, exist_ok=True)
    parsedir.mkdir(parents=True, exist_ok=True)


def _metrics_from_spans(spans: List[OCRSpan]) -> dict:
    if not spans:
        return {"pages": 0, "spans": 0, "avg_conf": None}
    pages = max(s.page for s in spans)
    confs = [s.confidence for s in spans if s.text]
    return {
        "pages": pages,
        "spans": len(spans),
        "avg_conf": round(mean(confs), 4) if confs else None,
    }


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
) -> Tuple[Path | None, Path, Path, dict]:
    """
    Returns: (ocr_txt_path or None if input was already .txt, normalized_txt_path, parsed_json_path, metrics)
    """
    ext = inp.suffix.lower()

    metrics: dict = {"pages": None, "spans": None, "avg_conf": None}

    # Stage 1: OCR (only for image/pdf)
    if ext in IMAGE_EXTS | PDF_EXTS:
        log.info("OCR: %s", inp)
        reader = OCRReader(
            languages=languages or ["en"],
            gpu=gpu,
            min_confidence=min_confidence,
            paragraph=paragraph,
            dpi=dpi,
        )
        spans = reader.read(inp)
        metrics = _metrics_from_spans(spans)
        raw_text = reader.to_plaintext(spans)
        ocr_txt_path = ocrdir / f"{inp.stem}.txt"
        ocr_txt_path.write_text(raw_text, encoding="utf-8")
    elif ext in TXT_EXTS:
        log.info("Skip OCR (already .txt): %s", inp)
        ocr_txt_path = inp
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Stage 2: Normalize
    log.info("Normalize -> %s", ocr_txt_path.name)
    norm_txt_path = normalize_txt_file(ocr_txt_path, normdir)

    # Stage 3: Extract
    log.info("Extract -> %s", norm_txt_path.name)
    parsed_json_path = extract_struct(norm_txt_path, parsedir)

    return (
        None if ext in TXT_EXTS else ocr_txt_path,
        norm_txt_path,
        parsed_json_path,
        metrics,
    )


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
            _, _, out_json, m = run_pipeline_for_file(
                p, ocrdir, normdir, parsedir, **kw
            )
            log.info(
                "Metrics: pages=%s spans=%s avg_conf=%s",
                m.get("pages"),
                m.get("spans"),
                m.get("avg_conf"),
            )
            outputs.append(out_json)
    return outputs


def _cli():
    # load config first to set logging
    cfg = load_config()
    setup_logging(cfg.get("logging", {}).get("level", "INFO"))

    ap = argparse.ArgumentParser(
        description="Run OCR → normalize → extract in one command"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input", help="Path to a single file (image/pdf/txt)")
    g.add_argument("--indir", help="Directory containing files (image/pdf/txt)")

    # Default folders come from config.toml, but can be overridden by CLI
    ap.add_argument(
        "--ocrdir", default=cfg["paths"]["ocrdir"], help="Where to write raw OCR .txt"
    )
    ap.add_argument(
        "--normdir",
        default=cfg["paths"]["normdir"],
        help="Where to write normalized .txt",
    )
    ap.add_argument(
        "--parsedir",
        default=cfg["paths"]["parsedir"],
        help="Where to write parsed .json",
    )

    # OCR tuning (config defaults, override via CLI)
    ocrc = cfg["ocr"]
    ap.add_argument(
        "--lang",
        nargs="+",
        default=ocrc["languages"],
        help="EasyOCR languages (e.g., en hi)",
    )
    ap.add_argument(
        "--gpu",
        action="store_true" if not ocrc["gpu"] else "store_false",
        help="Use GPU for EasyOCR (requires CUDA). If config had gpu=true, omit this flag to keep it.",
    )
    ap.add_argument(
        "--min-conf",
        type=float,
        default=ocrc["min_confidence"],
        help="Min confidence threshold",
    )
    ap.add_argument(
        "--no-paragraph", action="store_true", help="Disable EasyOCR paragraph mode"
    )
    ap.add_argument(
        "--dpi", type=int, default=ocrc["dpi"], help="PDF render DPI for OCR"
    )

    args = ap.parse_args()

    ocrdir = Path(args.ocrdir)
    normdir = Path(args.normdir)
    parsedir = Path(args.parsedir)
    ensure_dirs(ocrdir, normdir, parsedir)

    if args.input:
        inp = Path(args.input)
        if not inp.exists():
            raise FileNotFoundError(f"Input not found: {inp}")
        ocr_p, norm_p, json_p, m = run_pipeline_for_file(
            inp,
            ocrdir,
            normdir,
            parsedir,
            languages=args.lang,
            gpu=args.gpu or ocrc["gpu"],
            min_confidence=args.min_conf,
            paragraph=not args.no_paragraph and ocrc["paragraph"],
            dpi=args.dpi,
        )
        print("[OK] Pipeline complete")
        if ocr_p:
            print(f" • OCR:        {ocr_p}")
        print(f" • Normalized: {norm_p}")
        print(f" • Parsed:     {json_p}")
        print(
            f" • Metrics:    pages={m.get('pages')} spans={m.get('spans')} avg_conf={m.get('avg_conf')}"
        )
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
            gpu=args.gpu or ocrc["gpu"],
            min_confidence=args.min_conf,
            paragraph=not args.no_paragraph and ocrc["paragraph"],
            dpi=args.dpi,
        )
        print(f"[OK] Pipeline complete for {len(outs)} files -> {parsedir}")


if __name__ == "__main__":
    _cli()
