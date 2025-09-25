# adapters/legacy.py
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Dict, Any, List

from adapters.base import BaseAdapter
from sfa_core.models import Document, LineItem


DATE_PATTERNS = [
    r"\b(\d{4}-\d{2}-\d{2})\b",  # 2025-09-01
    r"\b(\d{2}/\d{2}/\d{4})\b",  # 09/01/2025
    r"\b(\d{2}-\d{2}-\d{4})\b",  # 09-01-2025
]

TOTAL_PATTERNS = [
    r"\bTOTAL\s*[:\-]?\s*\$?\s*([0-9]+(?:\.[0-9]{2})?)\b",
    r"\bAMOUNT\s+DUE\s*[:\-]?\s*\$?\s*([0-9]+(?:\.[0-9]{2})?)\b",
    r"\bBALANCE\s*[:\-]?\s*\$?\s*([0-9]+(?:\.[0-9]{2})?)\b",
]


def _extract_vendor(text: str | None) -> Optional[str]:
    if not text:
        return None
    # very light heuristic: first uppercase word chunk >= 3 letters
    m = re.search(r"\b([A-Z][A-Z'\-& ]{2,})\b", text)
    vendor = m.group(1).strip() if m else None
    # collapse repeated spaces
    if vendor:
        vendor = re.sub(r"\s{2,}", " ", vendor)
    return vendor


def _extract_date(text: str | None) -> Optional[str]:
    if not text:
        return None
    for pat in DATE_PATTERNS:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _parse_date(dt_raw: Optional[str]):
    if not dt_raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(dt_raw, fmt).date()
        except Exception:
            continue
    return None


def _extract_totals(text: str | None) -> Dict[str, Any]:
    if not text:
        return {}
    for pat in TOTAL_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                return {"total": float(m.group(1)), "currency": "USD"}
            except ValueError:
                pass
    # fallback: any dollar amount, take last match
    m_all = list(re.finditer(r"\$([0-9]+(?:\.[0-9]{2})?)", text))
    if m_all:
        try:
            return {"total": float(m_all[-1].group(1)), "currency": "USD"}
        except ValueError:
            pass
    return {}


def _extract_line_items(text: str | None) -> List[Dict[str, Any]]:
    if not text:
        return []
    # naive: split by line, treat each non-empty part as a description candidate
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # keep short list; in tests a single "Latte" token exists
    items: List[Dict[str, Any]] = []
    for ln in lines:
        # skip lines that are obviously totals
        if re.search(r"\b(total|amount due|balance)\b", ln, flags=re.IGNORECASE):
            continue
        items.append({"description": ln})
    # If nothing, try to pluck a trailing word token (e.g., "Latte")
    if not items:
        tail = re.findall(r"\b([A-Za-z]{3,})\b", text)
        if tail:
            items = [{"description": tail[-1]}]
    return items


class LegacyAdapter(BaseAdapter):
    """
    Legacy adapter:
    - If `parsed` dict is provided, use it directly (assumes keys: vendor, date, totals, line_items, etc.)
    - Else, derive a minimal parsed dict from OCR text using regex heuristics.
    This avoids tight coupling to parser.extractor.* function names.
    """

    def build(
        self,
        *,
        source_path: str,
        ocr_text: str | None = None,
        parsed: dict | None = None,
    ) -> Document:
        if parsed is None and ocr_text is None:
            raise ValueError("LegacyAdapter requires either parsed or ocr_text")

        data = parsed or {
            "vendor": _extract_vendor(ocr_text),
            "date": _extract_date(ocr_text),
            "totals": _extract_totals(ocr_text),
            "line_items": _extract_line_items(ocr_text),
        }

        vendor = data.get("vendor")
        doc_date = _parse_date(data.get("date"))

        totals = data.get("totals") or {}
        items_in = data.get("line_items") or []

        line_items = [
            LineItem(
                description=str(i.get("description", "")).strip(),
                quantity=i.get("qty") or i.get("quantity"),
                unit_price=i.get("unit_price"),
                total=i.get("total"),
                meta={
                    k: v
                    for k, v in i.items()
                    if k
                    not in {"description", "qty", "quantity", "unit_price", "total"}
                },
            )
            for i in items_in
        ]

        return Document(
            doc_id=data.get("doc_id") or source_path,
            source_path=source_path,
            vendor=vendor,
            doc_date=doc_date,
            subtotal=totals.get("subtotal"),
            tax=totals.get("tax"),
            total=totals.get("total"),
            currency=totals.get("currency") or "USD",
            line_items=line_items,
            raw_ocr_text=ocr_text,
            raw_blocks=data.get("raw_blocks"),
        )
