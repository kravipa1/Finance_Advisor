# cli/finproc.py
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from adapters.legacy import LegacyAdapter
from categorizer.service import CategorizerService
from sfa_core.models import Document, Transaction

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
        default=str(DEFAULT_RULES),  # <— use repo-relative default
        help="Rules YAML path (used when --categorize is set)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output JSON to stdout instead of human-readable text",
    )
    return p


def _discover_sources(path_str: str) -> Iterable[Path]:
    """
    Yield files to process. Supports single file or directory (recursive).
    """
    p = Path(path_str)
    if p.is_file():
        yield p
        return

    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {path_str}")

    exts = ("*.txt", "*.png", "*.jpg", "*.jpeg", "*.pdf")
    for ext in exts:
        yield from p.rglob(ext)


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
        # Example wiring for your real pipeline (keep as placeholders):
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
    """
    if is_dataclass(obj):
        return {k: _dataclass_deep_asdict(v) for k, v in asdict(obj).items()}
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
                f"Category   : {cat.primary_category or 'Uncategorized'}"
                f"{(' / ' + cat.secondary_category) if cat.secondary_category else ''}"
            )
            print(f"Merchant   : {cat.merchant or doc.vendor or 'N/A'}")
            if cat.tags:
                print(f"Tags       : {', '.join(cat.tags)}")
            print(f"Confidence : {cat.confidence:.2f}")
            print(f"Line items : {len(doc.line_items)}")
        else:
            # Document only
            doc = item
            print("─" * 60)
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
    payload = _dataclass_deep_asdict(results)
    print(json.dumps(payload, ensure_ascii=True))


def run(args: argparse.Namespace) -> int:
    adapter = LegacyAdapter()
    rules_path = Path(args.rules)
    rules_arg = str(rules_path) if rules_path.exists() else None
    cat_svc = CategorizerService(rules_path=rules_arg) if args.categorize else None

    results: List[Union[Document, Transaction]] = []

    for src in _discover_sources(args.path):
        ocr_text, parsed_dict = _obtain_text_and_parsed(src)
        doc = adapter.build(source_path=str(src), ocr_text=ocr_text, parsed=parsed_dict)
        if cat_svc:
            results.append(cat_svc.categorize(doc))
        else:
            results.append(doc)

    if args.json:
        _print_json(results)
    else:
        _print_human(results)

    return 0


def main() -> int:
    return run(make_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
