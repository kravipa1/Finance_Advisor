# parser/lineitems.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sfa_utils.normalizers import _fix_currency_ocr, normalize_amount


# --------- Patterns ---------

# Weighted grocery rows:
#   "Bananas 2.97 lb @ 0.59/lb .... 1.75"
#   "Jojo Potato Wedges Hot 1.06 lb @ 3.97/lb ... 4.21"
ROW_RX_WEIGHTED = re.compile(
    r"""
    ^\s*
    (?P<desc>.+?)\s+
    (?P<qty>\d+(?:\.\d+)?)
    \s*(lb|kg)\s*@\s*
    (?P<unit>\d+(?:\.\d+))\s*/\s*(lb|kg)
    .*?
    (?P<total>[S$€₹]?\s?\d{1,3}(?:,\d{3})*\.\d{2})
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Generic: "qty desc unit total"  →  "2 Widget A 19.99 39.98"
ROW_RX_QTY_UNIT_TOTAL = re.compile(
    r"""
    ^\s*
    (?P<qty>\d+(?:\.\d+)?)\s+
    (?P<desc>.+?)\s+
    (?P<unit>[S$€₹]?\s?\d{1,3}(?:,\d{3})*\.\d{2})\s+
    (?P<total>[S$€₹]?\s?\d{1,3}(?:,\d{3})*\.\d{2})
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Multiplicative form: "desc $unit x qty ... $total"
ROW_RX_XFORM = re.compile(
    r"""
    ^\s*
    (?P<desc>.+?)\s+
    (?P<unit>[S$€₹]?\s?\d{1,3}(?:,\d{3})*\.\d{2})\s*
    [x×]\s*
    (?P<qty>\d+(?:\.\d+)?)\s+.*?
    (?P<total>[S$€₹]?\s?\d{1,3}(?:,\d{3})*\.\d{2})
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Simple "desc .... amount"
ROW_RX_SIMPLE = re.compile(
    r"""
    ^\s*
    (?P<desc>.+?)\s+
    (?P<total>[S$€₹]?\s?\d{1,3}(?:,\d{3})*\.\d{2})
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Quantity on its own line (attach to previous)
QTY_NEXT_RX = re.compile(
    r"^\s*(?:qty|quantity)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*$", re.IGNORECASE
)

# Section headers commonly present on grocery receipts
SECTION_RX = re.compile(
    r"^\s*(DELI|PRODUCE|BAKERY|MEAT|SEAFOOD|DAIRY|FROZEN|GROCERY|HOUSEHOLD|BEVERAGES|SNACKS|PANTRY|BULK|BAKED\s+GOODS)\s*:?\s*$",
    re.IGNORECASE,
)


# --------- Helpers ---------


def _amt_triplet(raw_amount: str) -> Dict[str, Any]:
    amt = normalize_amount(_fix_currency_ocr(raw_amount))
    currency = amt.currency if amt else None
    value = float(amt.value) if (amt and amt.value is not None) else None
    raw_out = amt.raw if amt else raw_amount
    return {"raw": raw_out, "value": value, "currency": currency}


# --------- Matchers ---------


def _match_weighted(line: str) -> Optional[Dict[str, Any]]:
    m = ROW_RX_WEIGHTED.match(line.strip())
    if not m:
        return None
    desc = m.group("desc").strip()
    qty = float(m.group("qty"))
    unit_price = float(m.group("unit"))
    total = _amt_triplet(m.group("total"))
    return {
        "qty": qty,
        "desc": desc,
        "unit_price": {
            "raw": f"{unit_price:.2f}",
            "value": unit_price,
            "currency": total["currency"],
        },
        "line_total": total,
    }


def _match_qty_unit_total(line: str) -> Optional[Dict[str, Any]]:
    m = ROW_RX_QTY_UNIT_TOTAL.match(line.strip())
    if not m:
        return None
    qty = float(m.group("qty"))
    desc = m.group("desc").strip()
    unit_amt = normalize_amount(_fix_currency_ocr(m.group("unit")))
    total = _amt_triplet(m.group("total"))
    unit_value = (
        float(unit_amt.value) if (unit_amt and unit_amt.value is not None) else None
    )
    unit_raw = unit_amt.raw if unit_amt else m.group("unit")
    unit_ccy = unit_amt.currency if unit_amt else total["currency"]
    return {
        "qty": qty,
        "desc": desc,
        "unit_price": {"raw": unit_raw, "value": unit_value, "currency": unit_ccy},
        "line_total": total,
    }


def _match_xform(line: str) -> Optional[Dict[str, Any]]:
    m = ROW_RX_XFORM.match(line.strip())
    if not m:
        return None
    desc = m.group("desc").strip()
    qty = float(m.group("qty"))
    unit_amt = normalize_amount(_fix_currency_ocr(m.group("unit")))
    total = _amt_triplet(m.group("total"))
    unit_value = (
        float(unit_amt.value) if (unit_amt and unit_amt.value is not None) else None
    )
    unit_raw = unit_amt.raw if unit_amt else m.group("unit")
    unit_ccy = unit_amt.currency if unit_amt else total["currency"]
    return {
        "qty": qty,
        "desc": desc,
        "unit_price": {"raw": unit_raw, "value": unit_value, "currency": unit_ccy},
        "line_total": total,
    }


def _match_simple(line: str) -> Optional[Dict[str, Any]]:
    m = ROW_RX_SIMPLE.match(line.strip())
    if not m:
        return None
    desc = m.group("desc").strip()
    total = _amt_triplet(m.group("total"))
    return {
        "qty": None,
        "desc": desc,
        "unit_price": {"raw": "", "value": None, "currency": total["currency"]},
        "line_total": total,
    }


# --------- Public API ---------


def extract_line_items(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Very lightweight line-item extraction for receipts:
    - detect section headers and tag items with 'section'
    - qty/desc/unit/total
    - multiplicative form: desc $unit x qty ... $total
    - weighted rows (lb/kg)
    - simple "desc ... amount"
    - attach 'Quantity: N' lines to previous item
    """
    items: List[Dict[str, Any]] = []
    last_idx: Optional[int] = None
    current_section: Optional[str] = None

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        # Section header?
        ms = SECTION_RX.match(line)
        if ms:
            current_section = ms.group(1).upper()
            continue

        # Quantity-only lines attach to previous item
        mq = QTY_NEXT_RX.match(line)
        if mq and last_idx is not None and items:
            try:
                qv = float(mq.group(1))
            except Exception:
                qv = None
            if qv is not None:
                items[last_idx]["qty"] = qv
            continue

        # Try matchers in order
        for matcher in (
            _match_qty_unit_total,
            _match_xform,
            _match_weighted,
            _match_simple,
        ):
            item = matcher(line)
            if item:
                if current_section:
                    item["section"] = current_section
                items.append(item)
                last_idx = len(items) - 1
                break

    return items
