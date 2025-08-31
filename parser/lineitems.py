# parser/lineitems.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Optional
from sfa_utils.normalizers import normalize_amount, Amount

NUM = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
MONEY = rf"(?:\$|₹|INR|USD|Rs\.?)?\s*{NUM}"

ROW_RX = re.compile(
    rf"""^
        \s*(?P<qty>{NUM})\s+                                  # quantity
        (?P<desc>[A-Za-z0-9].*?[A-Za-z0-9])\s+                # description (loose)
        (?P<unit>{MONEY})\s+                                  # unit price
        (?P<total>{MONEY})\s*$                                # line total
    """,
    re.VERBOSE,
)

# Fallback: rows ending with an amount, with a qty somewhere at the start
ROW_RX_LOOSE = re.compile(
    rf"""^
        \s*(?P<qty>{NUM})\s+(?P<desc>.*?)(?P<total>{MONEY})\s*$
    """,
    re.VERBOSE,
)


@dataclass
class LineItem:
    qty: Optional[float]
    desc: str
    unit_price: Optional[Amount]
    line_total: Optional[Amount]


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def extract_line_items(lines: List[str]) -> List[Dict]:
    """
    Greedy: scan all lines for patterns, deduplicate obvious junk.
    """
    items: List[LineItem] = []
    for raw in lines:
        s = " ".join(raw.strip().split())  # collapse internal spaces
        m = ROW_RX.match(s)
        if m:
            qty = _to_float(m.group("qty"))
            desc = m.group("desc").strip()
            unit = normalize_amount(m.group("unit"))
            total = normalize_amount(m.group("total"))
            items.append(
                LineItem(qty=qty, desc=desc, unit_price=unit, line_total=total)
            )
            continue

        # looser pattern
        m2 = ROW_RX_LOOSE.match(s)
        if m2:
            qty = _to_float(m2.group("qty"))
            desc = m2.group("desc").strip().rstrip(" .:-")
            total = normalize_amount(m2.group("total"))
            items.append(
                LineItem(qty=qty, desc=desc, unit_price=None, line_total=total)
            )
            continue

    # Deduplicate by (desc, line_total.raw) to reduce repeats
    seen = set()
    dedup: List[Dict] = []
    for it in items:
        key = (it.desc.lower(), (it.line_total.raw if it.line_total else ""))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(
            {
                "qty": it.qty,
                "desc": it.desc,
                "unit_price": {
                    "raw": it.unit_price.raw if it.unit_price else "",
                    "value": (
                        float(it.unit_price.value)
                        if (it.unit_price and it.unit_price.value is not None)
                        else None
                    ),
                    "currency": it.unit_price.currency if it.unit_price else None,
                },
                "line_total": {
                    "raw": it.line_total.raw if it.line_total else "",
                    "value": (
                        float(it.line_total.value)
                        if (it.line_total and it.line_total.value is not None)
                        else None
                    ),
                    "currency": it.line_total.currency if it.line_total else None,
                },
            }
        )
    return dedup
