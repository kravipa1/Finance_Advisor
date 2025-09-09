# parser/extractor.py
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

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
RE_SALES_TAX = re.compile(r"\b(?:sales?\s*tax)\b[:\s]*([^\n]+)", re.IGNORECASE)
RE_DISCOUNT = re.compile(
    r"\b(?:discount|promo|coupon|savings)\b[:\s]*([^\n]+)", re.IGNORECASE
)

RE_TOTAL = re.compile(
    r"\b(?:order\s*total|amount\s*due|balance\s*due|total)\b(?!\s*(?:items|savings|price))[:\s]*([^\n]+)",
    re.IGNORECASE,
)
RE_RECEIPT_DATE = re.compile(
    rf"\b(?:receipt|order)\b.*?\b({DATE_RX.pattern})", re.IGNORECASE
)
RE_RECEIPT_FROM = re.compile(rf"\breceipt\s+from\s+({DATE_RX.pattern})", re.IGNORECASE)

MONEY_PRICE_RX = re.compile(
    r"(?:[$€₹]|US\$|USD|EUR|INR)\s*-?\d{1,3}(?:,\d{3})*(?:\.\d{2})"
    r"|"
    r"\b-?\d{1,3}(?:,\d{3})*\.\d{2}\b",
    re.IGNORECASE,
)

# OCR-robust labels
LBL_TOTAL_FUZZY = re.compile(r"\bt[o0]ta[l1I|]\b", re.I)
LBL_SUBTOTAL = re.compile(
    r"\bsub\s*tot[a-z]*\b", re.I
)  # matches 'subtot', 'subtotal', 'sub total'
LBL_SALES_TAX = re.compile(r"\b(?:sales?\s*ta[xk]|tax)\b", re.I)

TOTAL_NEAR_RX = re.compile(
    r"\b(total|grand\s*total|amount\s*due|balance\s*due|payable|amount)\b", re.I
)

NEG_TOTAL_CONTEXT = re.compile(
    r"(?:item|items|saving|savings|save|saved|authorization|auth|change|tip\s?suggest|barcode|reference|"
    r"subtotal|coupon|price|calculated|reward|rewards|promo|promotion|offer|points|earned|thanks\s+for\s+shopping)",
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


def _window(lines: List[str], i: int, back: int, fwd: int) -> str:
    lo = max(0, i - back)
    hi = min(len(lines), i + fwd + 1)
    return " ".join(s.strip() for s in lines[lo:hi])


# --------------------- split-line label grabbers ---------------------


def _labelled_amount_split(
    label_rx: re.Pattern, lines: List[str], look_ahead: int = 5, window: int = 120
) -> Optional[str]:
    lo = max(0, len(lines) - window)
    for i in range(len(lines) - 1, lo - 1, -1):
        s = " ".join(lines[i].strip().split())
        if not label_rx.search(s):
            continue
        # same line?
        m0 = MONEY_PRICE_RX.search(s)
        if m0 and not NEG_TOTAL_CONTEXT.search(_window(lines, i, 1, 1)):
            return m0.group(0)
        # next few lines
        for k in range(1, look_ahead + 1):
            j = i + k
            if j >= len(lines):
                break
            win = _window(lines, j, 1, 1)
            if NEG_TOTAL_CONTEXT.search(win):
                continue
            m = MONEY_PRICE_RX.search(lines[j])
            if m:
                return m.group(0)
    return None


def _labelled_total_from_bottom(lines: List[str]) -> Optional[str]:
    for idx, raw in enumerate(reversed(lines[-80:])):
        s = " ".join(raw.strip().split())
        if not LBL_TOTAL_FUZZY.search(s):
            continue
        if NEG_TOTAL_CONTEXT.search(_window(lines, len(lines) - 1 - idx, 1, 1)):
            continue
        m = MONEY_PRICE_RX.search(s)
        if m:
            return m.group(0)
    return None


def _labelled_total_split(lines: List[str]) -> Optional[str]:
    lo = max(0, len(lines) - 120)
    for i in range(len(lines) - 1, lo - 1, -1):
        s = " ".join(lines[i].strip().split())
        if not LBL_TOTAL_FUZZY.search(s):
            continue
        m0 = MONEY_PRICE_RX.search(s)
        if m0 and not NEG_TOTAL_CONTEXT.search(_window(lines, i, 1, 1)):
            return m0.group(0)
        for k in range(1, 6):
            j = i + k
            if j >= len(lines):
                break
            if NEG_TOTAL_CONTEXT.search(_window(lines, j, 2, 2)):
                continue
            m = MONEY_PRICE_RX.search(lines[j])
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
        near = _window(lines, i, 6, 6)  # wider neighborhood to exclude 'saved' blocks
        if NEG_TOTAL_CONTEXT.search(near):
            continue
        depth = i / n
        tot_bonus = 0.45 if TOTAL_NEAR_RX.search(near) else 0.0
        sym_bonus = 0.15 if has_symbol else 0.0
        mag = min(1.0, (val / 500.0)) ** 0.5
        score = 0.5 * depth + 0.3 * mag + tot_bonus + sym_bonus
        scored.append((score, raw))
    if not scored:
        return None
    return max(scored, key=lambda t: t[0])[1]


# --------------------- block-aware total (after Subtotal/Tax) ---------------------


def _last_indices_of(
    labels: List[re.Pattern], lines: List[str]
) -> Dict[re.Pattern, int]:
    idx: Dict[re.Pattern, int] = {}
    for i, ln in enumerate(lines):
        for rx in labels:
            if rx.search(ln):
                idx[rx] = i
    return idx


def _total_after_subtotaltax(lines: List[str]) -> Optional[str]:
    idx = _last_indices_of([LBL_SUBTOTAL, LBL_SALES_TAX], lines)
    if LBL_SUBTOTAL in idx and LBL_SALES_TAX in idx:
        start = max(idx[LBL_SUBTOTAL], idx[LBL_SALES_TAX])
        for j in range(start, min(len(lines), start + 12)):
            win = _window(lines, j, 2, 2)
            if NEG_TOTAL_CONTEXT.search(win):
                continue
            m = MONEY_PRICE_RX.search(lines[j])
            if m:
                return m.group(0)
    return None


# --------------------- consistency-based pick ---------------------


def _collect_total_candidates(
    lines: List[str], window: int = 160
) -> List[tuple[int, float, str, str, bool]]:
    lo = max(0, len(lines) - window)
    hits: List[tuple[int, float, str, str, bool]] = []
    for i in range(lo, len(lines)):
        ln = lines[i]
        for m in MONEY_PRICE_RX.finditer(ln):
            raw = m.group(0)
            has_symbol = bool(re.match(r"\s*(?:[$€₹]|US\$|USD|EUR|INR)", raw, re.I))
            a = normalize_amount(raw)
            if a and a.value is not None:
                hits.append((i, float(a.value), ln, raw, has_symbol))
    return hits


def _choose_total_with_consistency(
    subtotal: Dict[str, Any],
    tax: Dict[str, Any],
    discount: Dict[str, Any],
    lines: List[str],
) -> Optional[str]:
    s = subtotal.get("value")
    t = tax.get("value")
    d = discount.get("value")
    if s is None or t is None:
        return None
    expected = round(
        (s or 0.0)
        + (t or 0.0)
        + ((d if isinstance(d, (int, float)) and d < 0 else 0.0)),
        2,
    )

    cands = []
    for i, val, ln, raw, has_sym in _collect_total_candidates(lines, window=160):
        hood = _window(lines, i, 6, 6)
        if NEG_TOTAL_CONTEXT.search(hood):
            continue
        diff = abs(val - expected)
        if diff > 20.0:
            continue
        score = (-diff, i, 1 if has_sym else 0)
        cands.append((score, raw, val))
    if not cands:
        return None
    cands.sort(reverse=True)
    best_raw, best_val = cands[0][1], cands[0][2]
    if abs(best_val - expected) <= 1.00:
        return best_raw
    return None


# --------------------- reconciliation ---------------------


def _find_value_index(lines: List[str], value: float) -> Optional[int]:
    pat = re.compile(rf"\b{value:.2f}\b")
    for i, ln in enumerate(lines):
        if pat.search(ln):
            return i
    return None


def _reconcile_total(
    subtotal: Dict[str, Any],
    tax: Dict[str, Any],
    discount: Dict[str, Any],
    total: Dict[str, Any],
    lines: List[str],
) -> Dict[str, Any]:
    s = subtotal.get("value")
    t = tax.get("value")
    d = discount.get("value")
    tv = total.get("value")

    expected_st = (
        round((s or 0.0) + (t or 0.0), 2) if (s is not None and t is not None) else None
    )
    expected_std = (
        round((s or 0.0) + (t or 0.0) + (d or 0.0), 2)
        if (s is not None and t is not None and d is not None)
        else None
    )

    if tv is None and expected_st is not None:
        ccy = (
            total.get("currency")
            or subtotal.get("currency")
            or tax.get("currency")
            or discount.get("currency")
        )
        return {"raw": f"{expected_st:.2f}", "value": expected_st, "currency": ccy}
    if tv is None and expected_std is not None:
        ccy = (
            total.get("currency")
            or subtotal.get("currency")
            or tax.get("currency")
            or discount.get("currency")
        )
        return {"raw": f"{expected_std:.2f}", "value": expected_std, "currency": ccy}

    if tv is not None and expected_st is not None and abs(tv - expected_st) > 0.5:
        idx_tv = _find_value_index(lines, tv)
        idx_expected = _find_value_index(lines, expected_st)
        if idx_expected is not None:
            if (
                idx_tv is None
                or idx_expected >= (len(lines) - 15)
                or idx_expected > (idx_tv + 2)
            ):
                ccy = (
                    total.get("currency")
                    or subtotal.get("currency")
                    or tax.get("currency")
                )
                return {
                    "raw": f"{expected_st:.2f}",
                    "value": expected_st,
                    "currency": ccy,
                }

    return total


# --------------------- core extractors ---------------------


def extract_invoice(text: str) -> Dict[str, Any]:
    lines = [ln for ln in text.splitlines() if ln.strip()]

    vendor = guess_vendor(lines)

    inv_no = _first(RE_INVOICE_NO, text)
    po_no = _first(RE_PO_NO, text)

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

    # Prefer Sales Tax first (avoid grabbing "Taxes and Fees")
    subtotal = _amt_json(_first(RE_SUBTOTAL, text))
    tax = _amt_json(_first(RE_SALES_TAX, text))
    if tax["value"] is None:
        tax = _amt_json(_first(RE_TAX, text))
    discount = _amt_json(_first(RE_DISCOUNT, text))
    total = _amt_json(_first(RE_TOTAL, text))

    # split-line rescue for subtotal/tax
    if subtotal["value"] is None:
        st_split = _labelled_amount_split(LBL_SUBTOTAL, lines, look_ahead=5, window=200)
        if st_split:
            subtotal = _amt_json(st_split)
    if tax["value"] is None:
        tx_split = _labelled_amount_split(
            LBL_SALES_TAX, lines, look_ahead=5, window=200
        )
        if tx_split:
            tax = _amt_json(tx_split)

    # totals sequence: labelled (same line) → split-line → after Subtotal/Tax block → consistency → fallback
    if total["value"] is None:
        labelled_bottom = _labelled_total_from_bottom(lines)
        if labelled_bottom:
            total = _amt_json(labelled_bottom)
    if total["value"] is None:
        split_total = _labelled_total_split(lines)
        if split_total:
            total = _amt_json(split_total)
    if total["value"] is None:
        after_block = _total_after_subtotaltax(lines)
        if after_block:
            total = _amt_json(after_block)
    if total["value"] is None:
        consistent = _choose_total_with_consistency(subtotal, tax, discount, lines)
        if consistent:
            total = _amt_json(consistent)
    if total["value"] is None:
        fallback = _pick_total_fallback(lines)
        if fallback:
            total = _amt_json(fallback)

    total = _reconcile_total(subtotal, tax, discount, total, lines)

    line_items = extract_line_items(lines)

    any_amount = next(
        (a for a in [subtotal, tax, discount, total] if a["currency"]), None
    )
    currency_hint = any_amount["currency"] if any_amount else None

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
