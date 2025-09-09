# parser/extractor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import re
from datetime import datetime


@dataclass
class ParsedTotals:
    subtotal: Optional[float]
    tax: Optional[float]
    tip: Optional[float]
    total: Optional[float]
    reconciled_total_used: bool


@dataclass
class ParsedDoc:
    vendor: Optional[str]
    date: Optional[str]  # ISO "YYYY-MM-DD"
    line_items: List[Dict[str, Any]]
    totals: ParsedTotals
    sanity: Dict[str, float]
    meta: Dict[str, Any]


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _parse_money_line(label: str, text: str) -> Optional[float]:
    """
    Match amounts on their own line like:
      Subtotal: 12
      Tax 0.81
      Total - 9.81
    Allows optional decimals and trailing spaces.
    """
    pat = rf"^{label}\s*[:\-]?\s*\$?\s*([0-9]+(?:\.[0-9]+)?)\s*$"
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(pat, line, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _parse_date(text: str) -> Optional[str]:
    # ISO-like 2025-09-01 or 2025/09/01
    m = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            pass
    # US style 09/01/2025
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            pass
    return None


def _parse_vendor(text: str) -> Optional[str]:
    # First non-empty printable line under 50 chars with letters
    for raw in text.splitlines():
        s = raw.strip()
        if 0 < len(s) <= 50 and re.search(r"[A-Za-z]", s):
            return s
    return None


def _parse_line_items(text: str) -> List[Dict[str, Any]]:
    """
    Lines like:
      - Latte 1 x 4.50 = 4.50
      * Bread 2 x 2.49 = 4.98
      • Tea 1 @ 2.00 = 2.00
    """
    items: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(
            r"^[\-\*\u2022]\s*(.+?)\s+(\d+(?:\.\d+)?)\s*[x@]\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)$",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            desc = m.group(1).strip()
            qty = float(m.group(2))
            unit = float(m.group(3))
            amount = float(m.group(4))
            items.append(
                {"desc": desc, "qty": qty, "unit_price": unit, "amount": amount}
            )
    return items


def compute_sanity(
    line_items: List[Dict[str, Any]], subtotal: Optional[float]
) -> Dict[str, float]:
    li_sum = 0.0
    for li in line_items or []:
        qty = _safe_float(li.get("qty", 1))
        if "unit_price" in li:
            unit = _safe_float(li.get("unit_price", 0.0))
            li_sum += qty * unit
        else:
            li_sum += _safe_float(li.get("amount", 0.0))
    li_sum = round(li_sum, 2)
    sub = _safe_float(subtotal)
    diff = round(abs(li_sum - sub), 2)
    pct = round(diff / max(0.01, sub), 4) if sub > 0 else 0.0
    return {
        "items_subtotal_sum": li_sum,
        "items_subtotal_diff": diff,
        "items_subtotal_pct": pct,
    }


def extract(normalized_text: str, *, source_path: Optional[str] = None) -> ParsedDoc:
    vendor = _parse_vendor(normalized_text)
    date = _parse_date(normalized_text)
    subtotal = _parse_money_line("subtotal", normalized_text)
    tax = _parse_money_line("tax", normalized_text)
    tip = _parse_money_line("tip", normalized_text)
    total = _parse_money_line("total", normalized_text)

    reconciled_total_used = False  # wire real reconciliation later
    line_items = _parse_line_items(normalized_text)
    sanity = compute_sanity(line_items, subtotal)

    return ParsedDoc(
        vendor=vendor,
        date=date,
        line_items=line_items,
        totals=ParsedTotals(
            subtotal=subtotal,
            tax=tax,
            tip=tip,
            total=total,
            reconciled_total_used=reconciled_total_used,
        ),
        sanity=sanity,
        meta={"source_path": source_path or ""},
    )


def parsed_doc_as_row(doc: ParsedDoc) -> Dict[str, Any]:
    return {
        "vendor": doc.vendor,
        "date": doc.date,
        "subtotal": doc.totals.subtotal,
        "tax": doc.totals.tax,
        "tip": doc.totals.tip,
        "total": doc.totals.total,
        "reconciled_used": 1 if doc.totals.reconciled_total_used else 0,
        "items_subtotal_diff": doc.sanity.get("items_subtotal_diff", 0.0),
        "items_subtotal_pct": doc.sanity.get("items_subtotal_pct", 0.0),
    }
