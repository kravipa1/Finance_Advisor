# parser/extractor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import re
from datetime import datetime
from sfa_utils.normalizers import normalize_amount


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


# --- compatibility alias for older tests: return legacy dict, not ParsedDoc ---
def _as_amount_dict(a):
    # Handle dataclass-like objects (raw/value/currency) or mapping
    if a is None:
        return {"raw": "", "value": None, "currency": None}
    try:
        # dataclass attributes
        raw = getattr(a, "raw", "")
        val = getattr(a, "value", None)
        ccy = getattr(a, "currency", None)
        if raw or (val is not None) or ccy:
            return {"raw": raw, "value": val, "currency": ccy}
    except Exception:
        pass
    try:
        # mapping
        return {
            "raw": a.get("raw", ""),
            "value": a.get("value", None),
            "currency": a.get("currency", None),
        }
    except Exception:
        return {"raw": str(a), "value": None, "currency": None}


def _to_legacy_dict(doc):
    # Try common attributes; be defensive so tests don't crash
    g = getattr
    # kind: 'invoice' / 'paystub' / etc.
    kind = None
    try:
        kind = g(doc, "kind", None)
    except Exception:
        pass
    if kind is None and isinstance(doc, dict):
        kind = doc.get("kind")

    # total may live as doc.total or inside doc.totals['total']
    total_obj = None
    if hasattr(doc, "total"):
        total_obj = g(doc, "total")
    elif hasattr(doc, "totals"):
        totals_attr = g(doc, "totals")
        if isinstance(totals_attr, dict):
            total_obj = totals_attr.get("total") or totals_attr.get("grand_total")
    elif isinstance(doc, dict):
        total_obj = doc.get("total") or (doc.get("totals") or {}).get("total")

    out = {"kind": kind, "total": _as_amount_dict(total_obj)}
    return out


# --- compatibility helpers for legacy tests expecting a dict shape ---


def _as_amount_dict(a):
    if a is None:
        return {"raw": "", "value": None, "currency": None}
    raw = getattr(a, "raw", None)
    val = getattr(a, "value", None)
    ccy = getattr(a, "currency", None)
    if raw is not None or val is not None or ccy is not None:
        return {"raw": raw or "", "value": val, "currency": ccy}
    try:
        return {
            "raw": a.get("raw", ""),
            "value": a.get("value"),
            "currency": a.get("currency"),
        }
    except Exception:
        return {"raw": str(a), "value": None, "currency": None}


def _to_legacy_dict(doc):
    kind = getattr(doc, "kind", None)
    total_obj = getattr(doc, "total", None)
    if kind is None and isinstance(doc, dict):
        kind = doc.get("kind")
    if total_obj is None and hasattr(doc, "totals"):
        td = getattr(doc, "totals")
        if isinstance(td, dict):
            total_obj = td.get("total") or td.get("grand_total")
    if total_obj is None and isinstance(doc, dict):
        total_obj = doc.get("total") or (doc.get("totals") or {}).get("total")
    # Start with keys the old tests expect
    return {"kind": kind, "total": _as_amount_dict(total_obj), "net_pay": None}


# kind detectors
_KIND_INVOICE = re.compile(r"\binvoice\b", re.I)
_KIND_PAYSTUB = re.compile(r"\b(pay\s*stub|paystub|pay\s*period|net\s*pay)\b", re.I)

# ==== Legacy adapter for older tests (authoritative version) ====

_TOTAL_LABEL = r"(?:grand\s*total|amount\s*due|balance(?:\s*due)?|total(?!\s*sav(?:ing)?s?\b)(?!\s*discount\b)(?!\s*off\b))"

# Labeled totals like "Total: 17.94", "Grand Total 17.94", etc.
# Capture group now tolerates OCR-prefixed 'S' or misread '5' before the number.

_TOTAL_LINE_RX = re.compile(
    rf"""
    ^\s*
    {_TOTAL_LABEL}\b
    [^\d$€₹Ss5]*                        # allow OCR noise between label and number
    ([A-Za-z$€₹Ss5]?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2}))
    \b
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)

# Split cents on labeled total lines: e.g., "Total .... 17 94" (OCR gap between 17 and 94)
_TOTAL_SPLIT_RX = re.compile(
    rf"""
    ^\s*
    {_TOTAL_LABEL}\b
    .{0,80}?                             # tolerate filler like dots
    (\d{1,3}(?:,\d{3})*)\s+(\d{2})\b     # "17 94" -> groups: 17, 94
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)


# Net Pay anywhere (no line anchor). Use \W* so ':' or other punctuation/spaces are fine.
# Capture group also tolerates OCR 'S' or '5' before the amount.
_NETPAY_RX = re.compile(
    r"""
    net\W*pay\b
    [^\d$€₹Ss5]*                        # allow OCR noise between label and number
    ([A-Za-z$€₹Ss5]?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2}))
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Generic money token (used for fallback): accept '$', '€', '₹',
# AND common OCR quirks 'S' or '5' before the digits.
_MONEY_RX = re.compile(r"([A-Za-z$€₹Ss5]?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2}))")
_SPACY_DEC_RX = re.compile(r"(\d{1,3}(?:,\d{3})*)\s*[.,]\s*(\d{2})")
# Pure split cents anywhere (e.g., "17 94" -> 17.94), no label required.
_SPACY_PURE_RX = re.compile(r"(\d{1,3}(?:,\d{3})*)\s+(\d{2})\b")

# Split cents with any lightweight separator, anywhere in the doc.
# Examples it catches: "17 94", "17 . 94", "S 17 94", "$ 17-94"
_SPACY_ANYSEP_RX = re.compile(
    r"""
    [A-Za-z$€₹Ss5]?          # optional OCR/currency prefix
    \s*
    (\d{1,3}(?:,\d{3})*)     # integer part (e.g., 17 or 1,234)
    \s*[-–—·\.,]?\s*         # optional thin separator (space/dot/comma/hyphen/middot)
    (\d{2})\b                # cents
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Implied cents on labeled total lines, e.g. "Total .... 1794" -> 17.94
_TOTAL_IMPLIED_RX = re.compile(
    rf"""
    ^\s*
    {_TOTAL_LABEL}\b
    .{0,120}?                  # tolerate fillers/dot leaders
    (\d{3,6})\s*$              # 3–6 digits at end (e.g., 1794)
    """,
    re.IGNORECASE | re.VERBOSE | re.MULTILINE,
)

_IGNORE_TOTAL_CONTEXT = (
    "saving",
    "savings",
    "you saved",
    "discount",
    "coupon",
    "club",
    "just for u",
    "promo",
    "promotion",
    "cashback",
    "cash back",
    "% off",
    " percent off",
    "mfr coupon",
    "manufacturer coupon",
    "store coupon",
    "markdown",
    "deal",
)
_NUMERIC_ONLY_LINE_RX = re.compile(
    r"""
    ^\s*
    [A-Za-z$€₹Ss5]?              # optional OCR/currency char
    \s*
    (?:\d[\d,\s]*                # digits & commas & spaces
       (?:[.,]\s*\d{2})?         # optional decimal part
     |\d{3,6})                   # or plain 3–6 digits (implied cents)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_numeric_only_line(s: str) -> bool:
    return bool(_NUMERIC_ONLY_LINE_RX.match(s))


def _norm_amount_token(tok: str | None) -> dict:
    if not tok:
        return {"raw": "", "value": None, "currency": None}
    amt = normalize_amount(tok)
    raw = getattr(amt, "raw", tok)
    val = getattr(amt, "value", None)
    ccy = getattr(amt, "currency", None)
    return {"raw": raw, "value": val, "currency": ccy}


def _infer_kind(text: str) -> str | None:
    t = text.lower()
    if "net pay" in t or "pay period" in t or "paystub" in t or "pay stub" in t:
        return "paystub"
    if "invoice" in t or ("subtotal" in t and "total" in t):
        return "invoice"
    return None


def _find_total_in_text(text: str) -> dict:
    # 1) Prefer labeled total with a normal amount token
    m = _TOTAL_LINE_RX.search(text)
    if m:
        return _norm_amount_token(m.group(1))

    # 2) Labeled-but-split cents on the same line ("Total .... 17 94")
    m2 = _TOTAL_SPLIT_RX.search(text)
    if m2:
        whole, cents = m2.group(1), m2.group(2)
        return _norm_amount_token(f"{whole}.{cents}")

    # 3) Labeled implied cents on the same line ("Total .... 1794" -> 17.94)
    m3 = _TOTAL_IMPLIED_RX.search(text)
    if m3:
        digits = m3.group(1)
        if digits.isdigit():
            val = (
                f"{digits[:-2]}.{digits[-2:]}"
                if len(digits) > 2
                else f"0.{digits.zfill(2)}"
            )
            return _norm_amount_token(val)

    # 3a) NEW: Label on one line, amount on the next 1–2 lines (numeric-only)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        low = line.lower()
        if re.search(rf"\b{_TOTAL_LABEL}\b", low, re.IGNORECASE):
            # look ahead up to two lines for a numeric-only amount
            for j in (i + 1, i + 2):
                if j >= len(lines):
                    break
                nxt = lines[j].strip()
                if not _is_numeric_only_line(nxt):
                    continue
                # try normal money token first
                m_money = _MONEY_RX.search(nxt)
                if m_money:
                    return _norm_amount_token(m_money.group(1))
                # try spaced decimals with punctuation ("17 . 94")
                m_sp = _SPACY_DEC_RX.search(nxt)
                if m_sp:
                    intp, decp = m_sp.group(1), m_sp.group(2)
                    return _norm_amount_token(f"{intp}.{decp}")
                # try pure spaced decimals ("17 94")
                m_pure = _SPACY_PURE_RX.search(nxt)
                if m_pure:
                    intp, decp = m_pure.group(1), m_pure.group(2)
                    return _norm_amount_token(f"{intp}.{decp}")
                # try implied cents ("1794" -> 17.94)
                m_imp = re.match(r"^\s*(\d{3,6})\s*$", nxt)
                if m_imp:
                    d = m_imp.group(1)
                    return _norm_amount_token(f"{d[:-2]}.{d[-2:]}")

    # 4) Fallback: accumulate candidates from non-savings lines and pick MAX
    candidates = []

    prev_ctx = 0  # counts how many subsequent numeric-only lines to ignore
    for line in lines:
        low = line.lower().strip()

        if prev_ctx > 0 and _is_numeric_only_line(line):
            prev_ctx -= 1
            continue

        is_ctx = any(key in low for key in _IGNORE_TOTAL_CONTEXT)
        if is_ctx:
            prev_ctx = 2
            continue

        for m_tok in _MONEY_RX.finditer(line):
            candidates.append(m_tok.group(1))
        for m_sp in _SPACY_DEC_RX.finditer(line):
            intp, decp = m_sp.group(1), m_sp.group(2)
            candidates.append(f"{intp}.{decp}")
        for m_pure in _SPACY_PURE_RX.finditer(line):
            intp, decp = m_pure.group(1), m_pure.group(2)
            candidates.append(f"{intp}.{decp}")
        for m_any in _SPACY_ANYSEP_RX.finditer(line):
            intp, decp = m_any.group(1), m_any.group(2)
            candidates.append(f"{intp}.{decp}")

        if (
            ("total" in low)
            or ("amount due" in low)
            or ("grand total" in low)
            or ("balance" in low)
        ):
            m_tail_sp = re.search(r"(\d{1,3}(?:,\d{3})*)\s+(\d{2})\s*$", line)
            if m_tail_sp:
                candidates.append(f"{m_tail_sp.group(1)}.{m_tail_sp.group(2)}")
            m_tail_imp = re.search(r"(\d{3,6})\s*$", line)
            if m_tail_imp:
                d = m_tail_imp.group(1)
                candidates.append(f"{d[:-2]}.{d[-2:]}")

    best_tok, best_val = None, None
    for tok in candidates:
        amt = normalize_amount(tok)
        val = getattr(amt, "value", None)
        if val is not None and (best_val is None or val > best_val):
            best_val, best_tok = val, tok

    return _norm_amount_token(best_tok)


def _find_netpay_in_text(text: str) -> dict | None:
    # Primary: tolerant pattern (already handles OCR noise and optional currency)
    m = _NETPAY_RX.search(text)
    if m:
        return _norm_amount_token(m.group(1))

    # Backup: super-loose scan for a money token after "net pay"
    m2 = re.search(
        r"net\W*pay\b[^\d$€₹Ss5]*([A-Za-z$€₹Ss5]?\s*\d[\d,]*\s*(?:[.,]\s*\d{2}))",
        text,
        re.IGNORECASE,
    )
    if m2:
        tok = m2.group(1)
        # normalize common spacing issues like "1234 . 56" -> "1234.56"
        tok = tok.replace(" ", "")
        tok = tok.replace(",", "")
        tok = tok.replace(".,", ".").replace(",.", ".")
        return _norm_amount_token(tok)

    return None


def _as_amount_dict(a) -> dict:
    if a is None:
        return {"raw": "", "value": None, "currency": None}
    raw = getattr(a, "raw", None)
    val = getattr(a, "value", None)
    ccy = getattr(a, "currency", None)
    if raw is not None or val is not None or ccy is not None:
        return {"raw": raw or "", "value": val, "currency": ccy}
    try:
        return {
            "raw": a.get("raw", ""),
            "value": a.get("value"),
            "currency": a.get("currency"),
        }
    except Exception:
        return {"raw": str(a), "value": None, "currency": None}


def extract_from_text(text: str, source_path: str | None = None, **kwargs):
    """
    Legacy wrapper: use modern extract(), then project to old dict shape.
    Ensures keys: 'kind', 'total' (amount dict), 'net_pay' (amount dict or None).
    """
    doc = extract(text, source_path=source_path, **kwargs)

    # Start from modern result if present
    kind = getattr(doc, "kind", None)
    total = getattr(doc, "total", None)
    if total is None and hasattr(doc, "totals") and isinstance(doc.totals, dict):
        total = doc.totals.get("total") or doc.totals.get("grand_total")

    out = {
        "kind": kind,
        "total": _as_amount_dict(total),
        "net_pay": None,
    }

    # Backfill from raw text
    if out["kind"] is None:
        out["kind"] = _infer_kind(text)

    net = _find_netpay_in_text(text)
    if net:
        out["net_pay"] = net
        if out["kind"] is None:
            out["kind"] = "paystub"

    if out["total"]["value"] is None:
        # For paystubs, prefer net pay as the 'total'
        out["total"] = net or _find_total_in_text(text)

        # Ensure net_pay exists for paystubs
    if out["kind"] == "paystub" and out["net_pay"] is None:
        out["net_pay"] = out["total"]

    return out
