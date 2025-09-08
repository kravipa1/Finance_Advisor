# sfa_cli/process.py
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Any, List

from config.loader import load_config
from pipeline.process_file import process_file
from storage.sqlite_store import save_document  # NEW


def _emit_csv(doc: Dict[str, Any], csv_path: Path) -> None:
    rows: List[Dict[str, Any]] = doc.get("line_items", []) or []
    if not rows:
        return
    flat_rows: List[Dict[str, Any]] = []
    for r in rows:
        out = {}
        for k, v in r.items():
            if isinstance(v, dict) and {"raw", "value", "currency"} <= set(v.keys()):
                out[f"{k}_raw"] = v.get("raw")
                out[f"{k}_value"] = v.get("value")
                out[f"{k}_currency"] = v.get("currency")
            else:
                out[k] = v
        flat_rows.append(out)
    fieldnames = sorted(set().union(*[r.keys() for r in flat_rows]))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in flat_rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser(
        description="Process file → JSON (+categories) and CSV; optionally save to SQLite."
    )
    ap.add_argument("input", help="Path to image/pdf/txt")
    ap.add_argument(
        "--csv", default="line_items.csv", help="CSV path (default: line_items.csv)"
    )
    ap.add_argument(
        "--db", default=None, help="SQLite path to save results (e.g., data/app.db)"
    )
    args = ap.parse_args()

    cfg = load_config()
    ocrdir = Path(cfg["paths"]["ocrdir"])
    ocrdir.mkdir(parents=True, exist_ok=True)
    normdir = Path(cfg["paths"]["normdir"])
    normdir.mkdir(parents=True, exist_ok=True)
    parsedir = Path(cfg["paths"]["parsedir"])
    parsedir.mkdir(parents=True, exist_ok=True)

    _, _, _, data = process_file(
        Path(args.input),
        ocrdir,
        normdir,
        parsedir,
        languages=cfg["ocr"]["languages"],
        gpu=cfg["ocr"]["gpu"],
        min_confidence=cfg["ocr"]["min_confidence"],
        paragraph=cfg["ocr"]["paragraph"],
        dpi=cfg["ocr"]["dpi"],
    )

    print(json.dumps(data, indent=2, ensure_ascii=False))
    _emit_csv(data, Path(args.csv))
    print(f"\n[info] Wrote line items CSV -> {args.csv}")

    if args.db:
        doc_id = save_document(Path(args.db), data)
        print(f"[info] Saved to SQLite -> {args.db} (document id {doc_id})")


if __name__ == "__main__":
    main()
