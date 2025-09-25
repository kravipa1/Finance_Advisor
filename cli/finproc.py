# cli/finproc.py
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

from adapters.legacy import LegacyAdapter
from categorizer.service import CategorizerService
from sfa_core.models import Document, Transaction

LOGGER = logging.getLogger("finproc")
DEFAULT_RULES = Path(__file__).resolve().parents[1] / "config" / "rules.example.yaml"


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("finproc", description="Smart Finance CLI")
    p.add_argument("path", help="Invoice/receipt file or folder to process")
    p.add_argument(
        "--adapter",
        choices=["legacy"],
        default="legacy",
        help="Adapter to use for normalization (default: legacy)",
    )
    p.add_argument(
        "--categorize",
        action="store_true",
        help="Apply rule-based categorization",
    )
    p.add_argument(
        "--rules",
        default=str(DEFAULT_RULES),
        help="Rules YAML path (used when --categorize is set)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output JSON array to stdout instead of human-readable text",
    )
    p.add_argument(
        "--jsonl",
        action="store_true",
        help="Stream JSON lines (one record per line). Overrides --json output shape.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress info logs; only warnings/errors.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging.",
    )
    return p


def _setup_logging(args: argparse.Namespace) -> None:
    level = logging.INFO
    if args.quiet:
        level = logging.WARNING
    if args.verbose:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _discover_sources(path_str: str) -> List[Path]:
    """
    Return list of files to process. Supports single file or directory (recursive).
    """
    p = Path(path_str)
    if p.is_file():
        return [p]
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {path_str}")

    exts = ("*.txt", "*.png", "*.jpg", "*.jpeg", "*.pdf")
    out: List[Path] = []
    for ext in exts:
        out.extend(p.rglob(ext))
    return out


def _obtain_text_and_parsed(src: Path) -> Tuple[Optional[str], Optional[dict]]:
    """
    Minimal shim so the CLI has concrete variables.

    - For .txt files: treat the contents as 'ocr_text' and leave parsed=None.
    - For images/PDFs: wire in your real OCR/parse when ready (left as no-op).
    """
    ocr_text: Optional[str] = None
    parsed_dict: Optional[dict] = None

    if src.suffix.lower() == ".txt":
        ocr_text = src.read_text(encoding="utf-8", errors="ignore")
    else:
        # Example wiring for your real pipeline:
        # from ocr.reader import ocr_to_text
        # from parser.extractor import parse_from_text
        # img_bytes = src.read_bytes()
        # ocr_text = ocr_to_text(img_bytes)
        # parsed_dict = parse_from_text(ocr_text)
        pass

    return ocr_text, parsed_dict


def _dataclass_deep_asdict(
    obj: Union[Document, Transaction, list, dict, str, int, float, None]
):
    """
    JSON-friendly deep converter for dataclasses nested in lists/dicts.
    Converts date/datetime to ISO 8601 strings.
    """
    if is_dataclass(obj):
        return {k: _dataclass_deep_asdict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_dataclass_deep_asdict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_deep_asdict(v) for k, v in obj.items()}
    return obj


def _print_human(results: List[Union[Document, Transaction]]) -> None:
    """
    Simple human-readable output.
    """
    for item in results:
        if isinstance(item, Transaction):
            doc = item.doc
            cat = item.category
            print("-" * 60)
            print(f"Source     : {doc.source_path}")
            print(f"Vendor     : {doc.vendor or 'N/A'}")
            print(f"Date       : {doc.doc_date or 'N/A'}")
            print(
                f"Total      : {doc.total if doc.total is not None else 'N/A'} {doc.currency or ''}"
            )
            print(
                "Category   : "
                f"{cat.primary_category or 'Uncategorized'}"
                f"{(' / ' + cat.secondary_category) if cat.secondary_category else ''}"
            )
            print(f"Merchant   : {cat.merchant or doc.vendor or 'N/A'}")
            if cat.tags:
                print(f"Tags       : {', '.join(cat.tags)}")
            print(f"Confidence : {cat.confidence:.2f}")
            print(f"Line items : {len(doc.line_items)}")
        else:
            doc = item
            print("-" * 60)
            print(f"Source   : {doc.source_path}")
            print(f"Vendor   : {doc.vendor or 'N/A'}")
            print(f"Date     : {doc.doc_date or 'N/A'}")
            print(f"Subtotal : {doc.subtotal if doc.subtotal is not None else 'N/A'}")
            print(f"Tax      : {doc.tax if doc.tax is not None else 'N/A'}")
            print(
                f"Total    : {doc.total if doc.total is not None else 'N/A'} {doc.currency or ''}"
            )
            print(f"Line items: {len(doc.line_items)}")


def _print_json(results: List[Union[Document, Transaction]]) -> None:
    payload = {
        "schema_version": "1.0",
        "results": _dataclass_deep_asdict(results),
    }
    print(json.dumps(payload, ensure_ascii=True))


def _print_jsonl(results: List[Union[Document, Transaction]]) -> None:
    for item in results:
        rec = {
            "schema_version": "1.0",
            "result": _dataclass_deep_asdict(item),
        }
        print(json.dumps(rec, ensure_ascii=True))


def run(args: argparse.Namespace) -> int:
    _setup_logging(args)
    adapter = LegacyAdapter()

    # Resolve rules path; fall back to in-memory defaults if missing
    rules_path = Path(args.rules)
    rules_arg = str(rules_path) if rules_path.exists() else None
    if args.categorize and rules_arg is None:
        LOGGER.info("Rules file not found at %s; using built-in defaults.", args.rules)

    try:
        sources = _discover_sources(args.path)
    except FileNotFoundError as e:
        LOGGER.error(str(e))
        return 3

    if not sources:
        LOGGER.warning("No supported files found under: %s", args.path)
        return 2

    cat_svc = CategorizerService(rules_path=rules_arg) if args.categorize else None

    results: List[Union[Document, Transaction]] = []
    try:
        for src in sources:
            ocr_text, parsed_dict = _obtain_text_and_parsed(src)
            doc = adapter.build(
                source_path=str(src), ocr_text=ocr_text, parsed=parsed_dict
            )
            if cat_svc:
                results.append(cat_svc.categorize(doc))
            else:
                results.append(doc)
    except Exception as exc:  # guardrail: don't crash the CLI
        LOGGER.exception("Processing failed on %s: %s", src, exc)
        return 3

    if args.jsonl:
        _print_jsonl(results)
    elif args.json:
        _print_json(results)
    else:
        _print_human(results)

    return 0


def main() -> int:
    return run(make_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
