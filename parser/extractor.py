# parser/extractor.py
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from parser.doc_type import score as score_doc_type
from parser.lineitems import extract_line_items
from parser.vendor import guess_vendor
from sfa_utils.normalizers import normalize_amount, to_iso_date

# --------------------- regex helpers ---------------------

MONTHS = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATE_RX = re.compile(
    rf"\b(?:\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}}|\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|{MONTHS}\s+\d{{1,2}},?\s+\d{{2,4}})\b",
    re.IGNORECASE,
)

RE_INVOICE_NO = re.compile(
    r"\b(?:invoice|inv|bill)\s*(?:no|number|#|:)?\s*([A-Za-z0-9][A-Za-z0-9_.\-]{1,30})\b",
    re.IGNORECASE,
)
RE_PO_NO = re.compile(
    r"\b(?:po|purchase\s*order)\s*(?:no|number|#|:)?\s*([A-Za-z0-9][A-Za-z0-9_.\-]{1,30})\b",
    re.IGNORECASE,
)

RE_SUBTOTAL = re.compile(r"\b(?:sub\s*total|subtotal)\b[:\s]*([^\n]+)", re.IGNORECASE)
RE_TAX = re.compile(r"\b(?:tax|taxes)\b[:\s]*([^\n]+)", re.IGNORECASE)
RE_SALES_TAX = re.compile(r"\b(?:sales\s*tax)\b[:\s]*([^\n]+)", re.IGNORECASE)
RE_DISCOUNT = re.compile(
    r"\b(?:discount|promo|coupon|savings)\b[:\s]*([^\n]+)", re.IGNORECASE
)

# Ignore "Total Items/Savings/Price"
RE_TOTAL = re.compile(
    r"\b(?:order\s*total|amount\s*due|balance\s*due|total)\b(?!\s*(?:items|savings|price))[:\s]*([^\n]+)",
    re.IGNORECASE,
)
RE_RECEIPT_DATE = re.compile(
    rf"\b(?:receipt|order)\b.*?\b({DATE_RX.pattern})", re.IGNORECASE
)
RE_RECEIPT_FROM = re.compile(rf"\breceipt\s+from\s+({DATE_RX.pattern})", re.IGNORECASE)

# Prefer price-like amounts (currency symbol or mandatory decimals)
MONEY_PRICE_RX = re.compile(
    r"(?:[$€₹]|US\$|USD|EUR|INR)\s*-?\d{1,3}(?:,\d{3})*(?:\.\d{2})"
    r"|"
    r"\b-?\d{1,3}(?:,\d{3})*\.\d{2}\b",
    re.IGNORECASE,
)

# "Total" context bonus; include 'amount' so "Amount 17.94" can help
TOTAL_NEAR_RX = re.compile(
    r"\b(total|amount\s*due|balance\s*due|payable|amount)\b", re.I
)

# contexts to avoid choosing as total (added 'calculated')
NEG_TOTAL_CONTEXT = re.compile(
    r"(?:items|savings|authorization|auth|change|tip\s?suggest|barcode|reference|subtotal|coupon|price|calculated)",
    re.IGNORECASE,
)

# --------------------- tiny helpers ---------------------


def _first(rx: re.Pattern, text: str) -> Optional[str]:
    m = rx.search(text)
    if not m or (m.lastindex or 0) < 1:
        return None
    g = m.group(1)
    return g.strip() if g is not None else None


def _amt_json(raw: Optional[str]) -> Dict[str, Any]:
    a = normalize_amount(raw) if raw else None
    return {
        "raw": (a.raw if a else raw),
        "value": (float(a.value) if (a and a.value is not None) else None),
        "currency": (a.currency if a else None),
    }


def _coalesce(*vals):
    for v in vals:
        if v:
            return v
    return None


# --------------------- labelled totals (bottom-up) ---------------------


def _labelled_total_from_bottom(lines: List[str]) -> Optional[str]:
    for raw in reversed(lines[-60:]):
        s = " ".join(raw.strip().split())
        if not re.search(r"\btotal\b", s, re.I):
            continue
        if re.search(r"\b(items|savings|price)\b", s, re.I):
            continue
        m = MONEY_PRICE_RX.search(s)
        if m:
            return m.group(0)
    return None


def _labelled_total_split(lines: List[str]) -> Optional[str]:
    """
    Find 'Total' on one line and the amount on one of the next two lines.
    """
    lo = max(0, len(lines) - 60)
    for i in range(len(lines) - 1, lo - 1, -1):
        s = " ".join(lines[i].strip().split())
        if not re.search(r"\btotal\b", s, re.I):
            continue
        if re.search(r"\b(items|savings|price)\b", s, re.I):
            continue
        # same line?
        m0 = MONEY_PRICE_RX.search(s)
        if m0:
            return m0.group(0)
        # next lines
        for k in (1, 2):
            j = i + k
            if j >= len(lines):
                break
            nxt = lines[j]
            if re.search(r"\b(items|savings|price)\b", nxt, re.I):
                continue
            m = MONEY_PRICE_RX.search(nxt)
            if m:
                return m.group(0)
    return None


# --------------------- amount-first fallback ---------------------


def _all_amounts_with_lines(
    lines: List[str],
) -> List[tuple[int, float, str, str, bool]]:
    hits: List[tuple[int, float, str, str, bool]] = []
    for i, ln in enumerate(lines):
        for m in MONEY_PRICE_RX.finditer(ln):
            raw = m.group(0)
            has_symbol = bool(re.match(r"\s*(?:[$€₹]|US\$|USD|EUR|INR)", raw, re.I))
            a = normalize_amount(raw)
            if a and a.value is not None:
                hits.append((i, float(a.value), ln, raw, has_symbol))
    return hits


def _pick_total_fallback(lines: List[str]) -> Optional[str]:
    hits = _all_amounts_with_lines(lines)
    if not hits:
        return None

    n = max(1, len(lines) - 1)
    scored: List[tuple[float, str]] = []
    for i, val, ln, raw, has_symbol in hits:
        near = " ".join(lines[max(0, i - 1) : min(len(lines), i + 2)])
        if NEG_TOTAL_CONTEXT.search(ln) or NEG_TOTAL_CONTEXT.search(near):
            continue
        depth = i / n
        tot_bonus = 0.35 if TOTAL_NEAR_RX.search(near) else 0.0
        sym_bonus = 0.15 if has_symbol else 0.0
        mag = min(1.0, (val / 500.0)) ** 0.5
        score = 0.6 * depth + 0.25 * mag + tot_bonus + sym_bonus
        scored.append((score, raw))
    if not scored:
        return None
    return max(scored, key=lambda t: t[0])[1]


# --------------------- reconciliation ---------------------


def _amount_appears_in_text(value: float, lines: List[str]) -> bool:
    """Check if a formatted amount (xx.xx) appears anywhere in the text."""
    pat = re.compile(rf"\b{value:.2f}\b")
    for ln in lines[-120:]:
        if pat.search(ln):
            return True
    return False


def _reconcile_total(
    subtotal: Dict[str, Any],
    tax: Dict[str, Any],
    discount: Dict[str, Any],
    total: Dict[str, Any],
    lines: List[str],
) -> Dict[str, Any]:
    """
    Prefer arithmetic if subtotal+tax looks reliable; avoid double-discount.
    Strategy:
      - If s and t present, compute EXPECTED_ST = s + t.
      - If d present, also compute EXPECTED_STD = s + t + d.
      - If the labelled/fallback total is missing or far from EXPECTED_ST,
        and EXPECTED_ST appears in text, choose EXPECTED_ST.
      - Otherwise, if EXPECTED_STD appears and total is missing, choose it.
    """
    s = subtotal.get("value")
    t = tax.get("value")
    d = discount.get("value")
    tv = total.get("value")

    expected_st = None
    if s is not None and t is not None:
        expected_st = round((s or 0.0) + (t or 0.0), 2)

    expected_std = None
    if s is not None and t is not None and d is not None:
        expected_std = round((s or 0.0) + (t or 0.0) + (d or 0.0), 2)

    # If total missing, try best candidate by presence in text.
    if tv is None:
        cand = None
        if expected_st is not None and _amount_appears_in_text(expected_st, lines):
            cand = expected_st
        elif expected_std is not None and _amount_appears_in_text(expected_std, lines):
            cand = expected_std
        if cand is not None:
            ccy = (
                total.get("currency")
                or subtotal.get("currency")
                or tax.get("currency")
                or discount.get("currency")
            )
            return {"raw": f"{cand:.2f}", "value": cand, "currency": ccy}
        return total

    # If total present but deviates strongly from expected_st (most receipts: total = s + t),
    # and expected_st appears in text, trust expected_st.
    if (
        expected_st is not None
        and abs(tv - expected_st) > 0.5
        and _amount_appears_in_text(expected_st, lines)
    ):
        ccy = total.get("currency") or subtotal.get("currency") or tax.get("currency")
        return {"raw": f"{expected_st:.2f}", "value": expected_st, "currency": ccy}

    return total


# --------------------- core extractors ---------------------


def extract_invoice(text: str) -> Dict[str, Any]:
    lines = [ln for ln in text.splitlines() if ln.strip()]

    # vendor (no whitelist)
    vendor = guess_vendor(lines)

    # IDs
    inv_no = _first(RE_INVOICE_NO, text)
    po_no = _first(RE_PO_NO, text)

    # dates (single assignment; includes "receipt from ...")
    invoice_date_raw = _coalesce(
        _first(
            re.compile(
                rf"\b(?:invoice\s*date|date)\b[:\s-]*({DATE_RX.pattern})", re.IGNORECASE
            ),
            text,
        ),
        _first(RE_RECEIPT_DATE, text),
        _first(RE_RECEIPT_FROM, text),
    )
    due_date_raw = _first(
        re.compile(rf"\b(?:due\s*date)\b[:\s-]*({DATE_RX.pattern})", re.IGNORECASE),
        text,
    )
    invoice_date = {"raw": invoice_date_raw, "iso": to_iso_date(invoice_date_raw)}
    due_date = {"raw": due_date_raw, "iso": to_iso_date(due_date_raw)}

    # amounts (keyword first)
    subtotal = _amt_json(_first(RE_SUBTOTAL, text))
    tax = _amt_json(_coalesce(_first(RE_TAX, text), _first(RE_SALES_TAX, text)))
    discount = _amt_json(_first(RE_DISCOUNT, text))
    total = _amt_json(_first(RE_TOTAL, text))

    # totals sequence: labelled (same line) → split-line → fallback → reconcile
    if total["value"] is None:
        labelled_bottom = _labelled_total_from_bottom(lines)
        if labelled_bottom:
            total = _amt_json(labelled_bottom)
    if total["value"] is None:
        split_total = _labelled_total_split(lines)
        if split_total:
            total = _amt_json(split_total)
    if total["value"] is None:
        fallback = _pick_total_fallback(lines)
        if fallback:
            total = _amt_json(fallback)

    total = _reconcile_total(subtotal, tax, discount, total, lines)

    # line items
    line_items = extract_line_items(lines)

    # currency hint
    any_amount = next(
        (a for a in [subtotal, tax, discount, total] if a["currency"]), None
    )
    currency_hint = any_amount["currency"] if any_amount else None

    # sanity
    amount_hits = re.findall(
        r"(?:[$€₹]|US\$|USD|EUR|INR)?\s?-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?", text
    )
    has_money = any("." in a or "$" in a or "€" in a or "₹" in a for a in amount_hits)
    sanity = {
        "low_confidence": (
            total["value"] is None
            and subtotal["value"] is None
            and tax["value"] is None
        )
        and not has_money,
        "amount_hits": len(amount_hits),
    }

    return {
        "kind": "invoice",
        "vendor": vendor,
        "invoice_number": inv_no,
        "po_number": po_no,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "subtotal": subtotal,
        "tax": tax,
        "discount": discount,
        "total": total,
        "currency_hint": currency_hint,
        "emails": [],
        "phones": [],
        "line_items": line_items,
        "sanity": sanity,
    }


def extract_paystub(text: str) -> Dict[str, Any]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    employer = guess_vendor(lines)

    pay_period = _first(
        re.compile(
            rf"\bpay\s*period\b.*?({DATE_RX.pattern}).*?({DATE_RX.pattern})",
            re.IGNORECASE,
        ),
        text,
    )
    net = _amt_json(
        _first(re.compile(r"\bnet\s*pay\b[:\s]*([^\n]+)", re.IGNORECASE), text)
    )
    gross = _amt_json(
        _first(re.compile(r"\bgross\s*pay\b[:\s]*([^\n]+)", re.IGNORECASE), text)
    )

    amount_hits = re.findall(
        r"(?:[$€₹]|US\$|USD|EUR|INR)?\s?-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?", text
    )
    has_money = any("." in a or "$" in a or "€" in a or "₹" in a for a in amount_hits)

    sanity = {
        "low_confidence": (net["value"] is None and gross["value"] is None)
        and not has_money,
        "amount_hits": len(amount_hits),
    }

    return {
        "kind": "paystub",
        "employer": employer,
        "pay_period": pay_period,
        "gross_pay": gross,
        "net_pay": net,
        "line_items": [],
        "sanity": sanity,
    }


# --------------------- public API ---------------------


def extract_from_text(text: str) -> Dict[str, Any]:
    sc = score_doc_type(text)
    if sc.kind == "invoice":
        data = extract_invoice(text)
    elif sc.kind == "paystub":
        data = extract_paystub(text)
    else:
        data = extract_invoice(text)
    data["_doc_type_score"] = {"invoice": sc.invoice, "paystub": sc.paystub}
    return data


def extract_file(input_txt: Path, outdir: Path) -> Path:
    text = Path(input_txt).read_text(encoding="utf-8", errors="ignore")
    data = extract_from_text(text)
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(input_txt).stem + ".json")
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# --------------------- CLI (optional) ---------------------


def _cli():
    ap = argparse.ArgumentParser(
        description="Parse normalized .txt into structured JSON (invoice/paystub)."
    )
    ap.add_argument("--input", required=True, help="Path to a normalized .txt file")
    ap.add_argument("--outdir", required=True, help="Directory to write .json")
    args = ap.parse_args()
    p = extract_file(Path(args.input), Path(args.outdir))
    print(f"[OK] Extracted -> {p}")


if __name__ == "__main__":
    _cli()
