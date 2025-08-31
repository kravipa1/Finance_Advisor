# utils/normalizers.py
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Optional


try:
    from dateutil import parser as date_parser  # pip install python-dateutil
except Exception:  # pragma: no cover
    date_parser = None  # We’ll still return raw if unavailable


CURRENCY_SIGNS = {
    "USD": ["$", "US$", "USD"],
    "INR": ["₹", "Rs", "Rs.", "INR", "रु"],
}

AMOUNT_CLEAN = re.compile(r"[^\d\.,\-]")  # strip everything except digits, . , -
THREE_COMMA = re.compile(r"(?<=\d),(?=\d{3}\b)")  # 1,234 keep, but remove other commas


@dataclass
class Amount:
    raw: str
    value: Optional[Decimal]
    currency: Optional[str]


def detect_currency(text: str) -> Optional[str]:
    for ccy, markers in CURRENCY_SIGNS.items():
        for m in markers:
            if m in text:
                return ccy
    return None


def normalize_amount(raw: Optional[str]) -> Amount:
    if not raw:
        return Amount(raw="", value=None, currency=None)

    currency = detect_currency(raw)

    # remove all symbols except digits, dot, comma, minus
    s = AMOUNT_CLEAN.sub("", raw)

    # Cases:
    # 1) If there's a dot anywhere, assume dot is decimal separator -> remove commas.
    # 2) If there is no dot, but one or more commas:
    #    - If exactly one comma -> treat comma as decimal (e.g., "1234,56" -> "1234.56").
    #    - If multiple commas -> treat the LAST comma as decimal, others as thousands.
    #      Example: "1,234,56" -> "1234.56"
    if "." in s:
        # US-style: remove all commas as thousands separators
        s = s.replace(",", "")
    elif "," in s:
        comma_count = s.count(",")
        if comma_count == 1:
            s = s.replace(",", ".")
        else:
            last = s.rfind(",")
            # left side: remove all commas; right side: keep digits after last comma
            left = s[:last].replace(",", "")
            right = s[last + 1 :]
            s = f"{left}.{right}"

    try:
        val = Decimal(s)
    except InvalidOperation:
        val = None

    return Amount(raw=raw.strip(), value=val, currency=currency)


# ------------------ Dates ------------------

MONTHS = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"

DATE_RX = re.compile(
    rf"\b(?:\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}}|\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|{MONTHS}\s+\d{{1,2}},?\s+\d{{2,4}})\b",
    re.IGNORECASE,
)


def to_iso_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    if date_parser is None:
        return None
    try:
        dt = date_parser.parse(raw, dayfirst=False, yearfirst=False, fuzzy=True)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None
