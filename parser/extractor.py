# parser/extractor.py
"""
Extractor v2:
- Scores doc type (invoice vs paystub)
- Normalizes amounts & dates
- Extracts invoice line items
- Emits structured JSON

CLI:
  python -m parser.extractor --input data/interim/normalized_text/June_Forex.txt --outdir data/interim/parsed
  python -m parser.extractor --indir data/interim/normalized_text --outdir data/interim/parsed
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from sfa_utils.normalizers import (
    detect_currency,
    normalize_amount,
    to_iso_date,
    DATE_RX,
)
from parser.doc_type import score as score_doc_type
from parser.lineitems import extract_line_items

RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RE_PHONE = re.compile(
    r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)?\d{3}[\s-]?\d{4}\b"
)

RE_INVOICE_NO = re.compile(
    r"\b(?:invoice|inv|bill)\s*(?:no|number|#|:)?\s*([A-Za-z0-9\-_/]+)", re.IGNORECASE
)
RE_PO_NO = re.compile(
    r"\b(?:po|purchase\s*order)\s*(?:no|number|#|:)?\s*([A-Za-z0-9\-_/]+)",
    re.IGNORECASE,
)

RE_TOTAL = re.compile(
    r"\b(?:total|amount\s*due|balance\s*due)\b[:\s]*([^\n]+)", re.IGNORECASE
)
RE_SUBTOTAL = re.compile(r"\bsubtotal\b[:\s]*([^\n]+)", re.IGNORECASE)
RE_TAX = re.compile(r"\b(?:tax|gst|vat)\b[:\s]*([^\n]+)", re.IGNORECASE)
RE_DISCOUNT = re.compile(r"\bdiscount\b[:\s]*([^\n]+)", re.IGNORECASE)

RE_PAY_PERIOD = re.compile(
    rf"\bpay\s*period\b[:\s-]*({DATE_RX.pattern})\s*(?:to|-|through|–|—)\s*({DATE_RX.pattern})",
    re.IGNORECASE,
)
RE_PAY_DATE = re.compile(rf"\bpay\s*date\b[:\s-]*({DATE_RX.pattern})", re.IGNORECASE)
RE_GROSS_PAY = re.compile(r"\bgross\s*pay\b[:\s]*([^\n]+)", re.IGNORECASE)
RE_NET_PAY = re.compile(r"\bnet\s*pay\b[:\s]*([^\n]+)", re.IGNORECASE)

ADDRESS_HINT = re.compile(
    r"\b(road|rd\.?|street|st\.?|avenue|ave\.?|lane|ln\.?|suite|ste\.?|floor|flr\.?|tempe|phoenix|hyderabad)\b",
    re.IGNORECASE,
)


def _lines(text: str) -> List[str]:
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def _first_match(rx: re.Pattern, text: str) -> Optional[str]:
    m = rx.search(text)
    if not m:
        return None
    return (m.group(1) or m.group(0)).strip()


def _all(rx: re.Pattern, text: str) -> List[str]:
    return list(
        dict.fromkeys(  # unique in order
            (m.group(1) if m.lastindex else m.group(0)).strip()
            for m in rx.finditer(text)
        )
    )


def _guess_header_name(lines: List[str]) -> Optional[str]:
    window = lines[:15]
    for i, line in enumerate(window):
        s = line.strip()
        if not s:
            continue
        if (
            len(s) <= 60
            and s.upper() == s
            and re.search(r"[A-Z]", s)
            and not re.search(r"\d", s)
        ):
            return s
        if i + 1 < len(window):
            nxt = window[i + 1].strip()
            if ADDRESS_HINT.search(nxt) and 2 <= len(s.split()) <= 6:
                return s
    for s in window:
        s = s.strip()
        if s:
            return s
    return None


@dataclass
class AmountJSON:
    raw: Optional[str]
    value: Optional[float]
    currency: Optional[str]


def _amount_json(s: Optional[str]) -> AmountJSON:
    a = normalize_amount(s or "")
    return AmountJSON(
        raw=a.raw or None,
        value=float(a.value) if a.value is not None else None,
        currency=a.currency,
    )


# --------------------- INVOICE ---------------------


def extract_invoice(text: str) -> Dict:
    lines = _lines(text)
    vendor = _guess_header_name(lines)

    emails = _all(RE_EMAIL, text)
    phones = _all(RE_PHONE, text)
    currency = detect_currency(text)

    invoice_no = _first_match(RE_INVOICE_NO, text)
    po_no = _first_match(RE_PO_NO, text)

    invoice_date_raw = _first_match(
        re.compile(
            rf"\b(?:invoice\s*date|date)\b[:\s-]*({DATE_RX.pattern})", re.IGNORECASE
        ),
        text,
    )
    due_date_raw = _first_match(
        re.compile(rf"\b(?:due\s*date)\b[:\s-]*({DATE_RX.pattern})", re.IGNORECASE),
        text,
    )

    subtotal = _amount_json(_first_match(RE_SUBTOTAL, text))
    tax = _amount_json(_first_match(RE_TAX, text))
    discount = _amount_json(_first_match(RE_DISCOUNT, text))
    total = _amount_json(_first_match(RE_TOTAL, text))

    items = extract_line_items(lines)

    return {
        "kind": "invoice",
        "vendor": vendor,
        "invoice_number": invoice_no,
        "po_number": po_no,
        "invoice_date": {"raw": invoice_date_raw, "iso": to_iso_date(invoice_date_raw)},
        "due_date": {"raw": due_date_raw, "iso": to_iso_date(due_date_raw)},
        "subtotal": asdict(subtotal),
        "tax": asdict(tax),
        "discount": asdict(discount),
        "total": asdict(total),
        "currency_hint": currency,
        "emails": emails,
        "phones": phones,
        "line_items": items,
    }


# --------------------- PAYSTUB ---------------------


def extract_paystub(text: str) -> Dict:
    lines = _lines(text)
    employer = _guess_header_name(lines)
    employee = None
    for i, ln in enumerate(lines[:40]):
        if re.search(r"\bemployee\b[:\s-]*", ln, re.IGNORECASE):
            after = re.sub(r"(?i)\bemployee\b[:\s-]*", "", ln).strip()
            if after:
                employee = after
            else:
                for j in range(i + 1, min(i + 5, len(lines))):
                    s = lines[j].strip()
                    if s:
                        employee = s
                        break
            break

    emails = _all(RE_EMAIL, text)
    phones = _all(RE_PHONE, text)
    currency = detect_currency(text)

    m = RE_PAY_PERIOD.search(text)
    p_start_raw = m.group(1) if m else None
    p_end_raw = m.group(2) if m else None
    pay_date_raw = _first_match(RE_PAY_DATE, text)

    gross = _amount_json(_first_match(RE_GROSS_PAY, text))
    net = _amount_json(_first_match(RE_NET_PAY, text))

    return {
        "kind": "paystub",
        "employer": employer,
        "employee": employee,
        "pay_period_start": {"raw": p_start_raw, "iso": to_iso_date(p_start_raw)},
        "pay_period_end": {"raw": p_end_raw, "iso": to_iso_date(p_end_raw)},
        "pay_date": {"raw": pay_date_raw, "iso": to_iso_date(pay_date_raw)},
        "gross_pay": asdict(gross),
        "net_pay": asdict(net),
        "currency_hint": currency,
        "emails": emails,
        "phones": phones,
    }


# --------------------- ENTRY ---------------------


def extract_from_text(text: str) -> Dict:
    s = score_doc_type(text)
    if s.kind == "invoice":
        out = extract_invoice(text)
    else:
        out = extract_paystub(text)
    out["_doc_type_score"] = {"invoice": s.invoice, "paystub": s.paystub}
    return out


def extract_file(input_path: Path, outdir: Path) -> Path:
    text = input_path.read_text(encoding="utf-8", errors="ignore")
    data = extract_from_text(text)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / (input_path.stem + ".json")
    out_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_path


def batch_extract(indir: Path, outdir: Path) -> List[Path]:
    outputs: List[Path] = []
    for p in sorted(indir.glob("*.txt")):
        outputs.append(extract_file(p, outdir))
    return outputs


def _cli():
    parser = argparse.ArgumentParser(
        description="Extract key fields from normalized OCR text (v2)"
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--input", help="Path to a single normalized .txt file")
    g.add_argument("--indir", help="Directory of normalized .txt files to batch")
    parser.add_argument(
        "--outdir", default="data/interim/parsed", help="Where to write JSON outputs"
    )
    args = parser.parse_args()

    outdir = Path(args.outdir)

    if args.input:
        inp = Path(args.input)
        if not inp.exists():
            raise FileNotFoundError(f"Input not found: {inp}")
        out = extract_file(inp, outdir)
        print(f"[OK] Parsed -> {out}")
    else:
        indir = Path(args.indir)
        if not indir.exists():
            raise FileNotFoundError(f"Input dir not found: {indir}")
        outs = batch_extract(indir, outdir)
        print(f"[OK] Parsed {len(outs)} files -> {outdir}")


if __name__ == "__main__":
    _cli()
