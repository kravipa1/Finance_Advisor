# sfa_utils/normalizers.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ---------------- Currency OCR fix ----------------

# Only replace a leading S/5 with $ when it starts an amount token:
#   ok: " S17.94", "5 0.95"  -> "$17.94", "$0.95"
#   NOT ok inside a number: "1,234.56" -> keep it
_CURRENCY_OCR_FIX = re.compile(r"(?<![A-Za-z0-9$€₹.,])([S5])(?=\s?\d)")


def _fix_currency_ocr(s: str) -> str:
    return _CURRENCY_OCR_FIX.sub("$", s or "")


# ---------------- Amount normalization ----------------

CURRENCY_MAP = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "₹": "INR",
    "INR": "INR",
}

CUR_RX = re.compile(
    r"^\s*(?P<cur>US\$|USD|EUR|INR|[$€₹])\s*(?P<num>.*)$", re.IGNORECASE
)

NUM_RX = re.compile(
    r"""
    ^\s*
    (?P<sign>[-(]?)\s*
    (?P<int>\d{1,3}(?:,\d{3})*|\d+)
    (?P<dec>\.\d{2})?
    \s*\)?\s*$
    """,
    re.VERBOSE,
)


@dataclass
class Amount:
    raw: str
    value: Optional[float]
    currency: Optional[str]


def normalize_amount(raw: Optional[str]) -> Optional[Amount]:
    if raw is None:
        return None

    s = _fix_currency_ocr(str(raw)).strip()
    if not s:
        return Amount(raw="", value=None, currency=None)

    cur = None
    num_part = s

    mcur = CUR_RX.match(s)
    if mcur:
        cur_token = mcur.group("cur").upper()
        cur = CURRENCY_MAP.get(cur_token, None)
        num_part = mcur.group("num").strip()

    # Primary strict parse (dot decimal)
    m = NUM_RX.match(num_part)
    if m:
        num_str = (m.group("int") or "") + (m.group("dec") or "")
        sign = "-" if (m.group("sign") or "") in ("-", "(") else ""
    else:
        # Fallback 1: find a dot-decimal number anywhere
        mid = re.search(r"-?\d{1,3}(?:,\d{3})*(?:\.\d{2})", num_part)
        if mid:
            num_str = mid.group(0)
            sign = (
                "-"
                if num_part.strip().startswith("(") or num_part.strip().startswith("-")
                else ""
            )
        else:
            # Fallback 2: comma-decimal (e.g., "1,234,56")
            midc = re.search(r"-?\d{1,3}(?:,\d{3})*,\d{2}", num_part)
            if not midc:
                return Amount(raw=s, value=None, currency=cur)
            token = midc.group(0)
            sign = (
                "-"
                if token.strip().startswith("-") or num_part.strip().startswith("(")
                else ""
            )
            int_part, dec = token.rsplit(",", 1)
            num_str = int_part.replace(",", "") + "." + dec

    num_str = num_str.replace(",", "")
    try:
        val = float(sign + num_str)
    except Exception:
        val = None

    return Amount(raw=s, value=val, currency=cur)


# ---------------- Dates ----------------

MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "SEPT": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

MDY_RX = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\s*$")
YMD_RX = re.compile(r"^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*$")
MON_D_Y_RX = re.compile(r"^\s*([A-Za-z]{3,})\s+(\d{1,2}),?\s+(\d{2,4})\s*$")


def _clip_year(y: int) -> int:
    if y < 100:
        return 2000 + y if y < 70 else 1900 + y
    return y


def to_iso_date(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip()

    m = YMD_RX.match(s)
    if m:
        y = int(m.group(1))
        mnt = int(m.group(2))
        d = int(m.group(3))
        try:
            return datetime(y, mnt, d).date().isoformat()
        except Exception:
            return None

    m = MON_D_Y_RX.match(s)
    if m:
        mon = MONTHS.get(m.group(1).strip().upper()[:4].rstrip("."), None)
        if mon:
            d = int(m.group(2))
            y = _clip_year(int(m.group(3)))
            try:
                return datetime(y, mon, d).date().isoformat()
            except Exception:
                return None

    m = MDY_RX.match(s)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        y = _clip_year(int(m.group(3)))
        if a > 12 and b <= 12:
            d, mon = a, b
        else:
            mon, d = a, b
        try:
            return datetime(y, mon, d).date().isoformat()
        except Exception:
            return None

    return None
