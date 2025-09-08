# parser/lineitems.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from sfa_utils.normalizers import normalize_amount

# money tokens like $12.34 or 1,234.56 (currency symbol optional)
MONEY = r"(?:[$₹]|US\$|USD|INR)?\s?-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?"

# Strict pattern: "2 Widget A 19.99 39.98"
ROW_RX_STRICT = re.compile(
    rf"""^
    (?P<qty>\d+(?:\.\d+)?)\s+                 # quantity
    (?P<desc>.+?)\s+                          # description
    (?P<unit>{MONEY})\s+                      # unit price
    (?P<total>{MONEY})\s*$                    # line total
    """,
    re.VERBOSE,
)

# Loose pattern: "2 x Widget A ... 39.98"  (qty and trailing total)
ROW_RX_LOOSE = re.compile(
    rf"""^
    (?P<qty>\d+(?:\.\d+)?)\s*(?:x|\*)?\s+     # quantity with optional 'x'
    (?P<desc>.+?)\s+                          # description
    (?P<total>{MONEY})\s*$                    # trailing total
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Fallback: "desc ... 39.98" (no qty or unit price, typical on receipts)
ROW_RX_DESC_TOTAL = re.compile(
    rf"""^(?P<desc>.+?)\s+(?P<total>{MONEY})\s*$""",
    re.VERBOSE,
)

# Inline or next-line quantity
QTY_INLINE = re.compile(r"(?i)\b(?:qty|quantity)\b[:\s]*([0-9]+)")


@dataclass
class LineItem:
    qty: Optional[float]
    desc: str
    unit_price: Optional[Dict[str, Any]]
    line_total: Optional[Dict[str, Any]]
    category: Optional[str] = None  # may be filled later

    def to_dict(self) -> Dict[str, Any]:
        return {
            "qty": self.qty,
            "desc": self.desc,
            "unit_price": self.unit_price
            or {"raw": "", "value": None, "currency": None},
            "line_total": self.line_total
            or {"raw": "", "value": None, "currency": None},
            **({"category": self.category} if self.category else {}),
        }


def _amt_json(raw: Optional[str]) -> Dict[str, Any]:
    a = normalize_amount(raw) if raw else None
    return {
        "raw": (a.raw if a else raw),
        "value": (float(a.value) if (a and a.value is not None) else None),
        "currency": (a.currency if a else None),
    }


def extract_line_items(lines: List[str]) -> List[Dict[str, Any]]:
    items: List[LineItem] = []

    for raw in lines:
        s = " ".join(raw.strip().split())
        if not s:
            continue

        # attach "Quantity: N" to last item lacking qty
        qm = QTY_INLINE.search(s)
        if qm and items:
            try:
                qv = float(qm.group(1))
            except Exception:
                qv = None
            if qv is not None:
                for idx in range(len(items) - 1, -1, -1):
                    if items[idx].qty is None:
                        items[idx].qty = qv
                        break
            continue

        m1 = ROW_RX_STRICT.match(s)
        if m1:
            qty = float(m1.group("qty"))
            desc = m1.group("desc").strip().rstrip(" .:-")
            unit = _amt_json(m1.group("unit"))
            total = _amt_json(m1.group("total"))
            items.append(
                LineItem(qty=qty, desc=desc, unit_price=unit, line_total=total)
            )
            continue

        m2 = ROW_RX_LOOSE.match(s)
        if m2:
            qty = float(m2.group("qty"))
            desc = m2.group("desc").strip().rstrip(" .:-")
            total = _amt_json(m2.group("total"))
            items.append(
                LineItem(qty=qty, desc=desc, unit_price=None, line_total=total)
            )
            continue

        m3 = ROW_RX_DESC_TOTAL.match(s)
        if m3:
            desc = m3.group("desc").strip().rstrip(" .:-")
            total = _amt_json(m3.group("total"))
            items.append(
                LineItem(qty=None, desc=desc, unit_price=None, line_total=total)
            )
            continue

    return [it.to_dict() for it in items]
