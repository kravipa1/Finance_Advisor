# parser/extractor.py
"""
Basic rule-based field extractor for invoices/paystubs from normalized OCR text.

Usage (CLI):
  # Single file
  python -m parser.extractor --input data/interim/normalized_text/June_Forex.txt --outdir data/interim/parsed

  # Or batch a whole folder of normalized .txt files
  python -m parser.extractor --indir data/interim/normalized_text --outdir data/interim/parsed
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ------------------------- helpers: common regex -------------------------

CURRENCY_SIGNS = {
    "USD": ["$", "US$", "USD"],
    "INR": ["₹", "Rs", "INR", "Rs.", "रु"],
}

# Date patterns (very permissive). We'll keep the raw string and also
# try to normalize to YYYY-MM-DD when obvious.
DATE_PATTERNS = [
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",  # 12/31/2024 or 12-31-24
    r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2})\b",  # 2024-12-31
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4}\b",  # Dec 31, 2024
]

RE_DATE = re.compile("|".join(DATE_PATTERNS), flags=re.IGNORECASE)

RE_INVOICE_NO = re.compile(
    r"\b(?:invoice|inv|bill)\s*(?:no|number|#|:)?\s*([A-Za-z0-9\-_/]+)", re.IGNORECASE
)
RE_PO_NO = re.compile(
    r"\b(?:po|purchase\s*order)\s*(?:no|number|#|:)?\s*([A-Za-z0-9\-_/]+)",
    re.IGNORECASE,
)

RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RE_PHONE = re.compile(
    r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)?\d{3}[\s-]?\d{4}\b"
)

# Totals: look for labels near amounts
RE_AMOUNT = r"(?:[$₹]|INR|USD|Rs\.?|US\$)?\s*[\d{1,3}(,\d{3})*]+(?:\.\d{2})?"
RE_TOTAL = re.compile(
    rf"\b(?:total|amount\s*due|balance\s*due)\b[:\s]*({RE_AMOUNT})", re.IGNORECASE
)
RE_SUBTOTAL = re.compile(rf"\b(?:subtotal)\b[:\s]*({RE_AMOUNT})", re.IGNORECASE)
RE_TAX = re.compile(rf"\b(?:tax|gst|vat)\b[:\s]*({RE_AMOUNT})", re.IGNORECASE)
RE_DISCOUNT = re.compile(rf"\b(?:discount)\b[:\s]*(-?\s*{RE_AMOUNT})", re.IGNORECASE)

# Pay stub signals
RE_PAY_PERIOD = re.compile(
    rf"\bpay\s*period\b[:\s-]*({RE_DATE.pattern})\s*(?:to|-|through|–|—)\s*({RE_DATE.pattern})",
    re.IGNORECASE,
)
RE_PAY_DATE = re.compile(rf"\bpay\s*date\b[:\s-]*({RE_DATE.pattern})", re.IGNORECASE)
RE_GROSS_PAY = re.compile(rf"\bgross\s*pay\b[:\s]*({RE_AMOUNT})", re.IGNORECASE)
RE_NET_PAY = re.compile(rf"\bnet\s*pay\b[:\s]*({RE_AMOUNT})", re.IGNORECASE)

# Vendor/employer heuristics: lines starting with NAME and address-like patterns
RE_ADDRESS_HINT = re.compile(
    r"\b(?:road|rd\.?|street|st\.?|avenue|ave\.?|lane|ln\.?|suite|ste\.?|floor|flr\.?|tempe|phoenix|hyderabad)\b",
    re.IGNORECASE,
)


@dataclass
class ExtractedInvoice:
    kind: str  # "invoice"
    vendor: Optional[str]
    invoice_number: Optional[str]
    po_number: Optional[str]
    invoice_date: Optional[str]
    due_date: Optional[str]
    subtotal: Optional[str]
    tax: Optional[str]
    discount: Optional[str]
    total: Optional[str]
    currency: Optional[str]
    emails: List[str]
    phones: List[str]
    raw: Dict[str, str]  # small stash of raw hits


@dataclass
class ExtractedPaystub:
    kind: str  # "paystub"
    employer: Optional[str]
    employee: Optional[str]
    pay_period_start: Optional[str]
    pay_period_end: Optional[str]
    pay_date: Optional[str]
    gross_pay: Optional[str]
    net_pay: Optional[str]
    currency: Optional[str]
    emails: List[str]
    phones: List[str]
    raw: Dict[str, str]


# ---------------------------- core functions -----------------------------


def detect_currency(text: str) -> Optional[str]:
    for ccy, markers in CURRENCY_SIGNS.items():
        for m in markers:
            if m in text:
                return ccy
    return None


def capture_first(regex: re.Pattern, text: str) -> Optional[str]:
    m = regex.search(text)
    if not m:
        return None
    # Prefer the first capturing group if present; else the whole match
    return m.group(1) if m.lastindex else m.group(0)


def capture_all(regex: re.Pattern, text: str) -> List[str]:
    return list(
        dict.fromkeys(
            m[0] if m and not m.lastindex else m[1] for m in regex.finditer(text)
        )
    )  # unique order


def guess_vendor(lines: List[str]) -> Optional[str]:
    """
    Heuristic: first 15 lines, pick a line that looks like a company header
    (uppercase words, or a line followed by address-like content).
    """
    window = lines[:15]
    for i, line in enumerate(window):
        s = line.strip()
        if not s:
            continue
        # Strong signal: big upper-case name without digits
        if (
            len(s) <= 60
            and s.upper() == s
            and re.search(r"[A-Z]", s)
            and not re.search(r"\d", s)
        ):
            return s
        # Next: a title case name followed by an address-ish line
        if i + 1 < len(window):
            nxt = window[i + 1].strip()
            if RE_ADDRESS_HINT.search(nxt) and 2 <= len(s.split()) <= 6:
                return s
    # Fallback: first non-empty line
    for s in window:
        s = s.strip()
        if s:
            return s
    return None


def guess_employer_employee(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Naive: top-of-document block likely employer; look for 'Employee' label for employee.
    """
    employer = guess_vendor(lines)
    # Employee line
    for i, line in enumerate(lines[:40]):
        if re.search(r"\bemployee\b[:\s-]*", line, re.IGNORECASE):
            # pick label's value or next non-empty line
            after = re.sub(r"(?i)\bemployee\b[:\s-]*", "", line).strip()
            if after:
                return employer, after
            # else next non-empty
            for j in range(i + 1, min(i + 5, len(lines))):
                s = lines[j].strip()
                if s:
                    return employer, s
    return employer, None


def looks_like_paystub(text: str) -> bool:
    return any(
        kw in text.lower()
        for kw in [
            "pay period",
            "net pay",
            "gross pay",
            "ytd",
            "taxable",
            "hours",
            "earnings",
            "deductions",
            "leave balance",
            "employee id",
            "pay date",
        ]
    )


def extract_invoice(text: str, lines: List[str]) -> ExtractedInvoice:
    emails = capture_all(RE_EMAIL, text)
    phones = capture_all(RE_PHONE, text)
    currency = detect_currency(text)

    invoice_no = capture_first(RE_INVOICE_NO, text)
    po_no = capture_first(RE_PO_NO, text)

    # Dates: try labels
    invoice_date = capture_first(
        re.compile(
            rf"\b(?:invoice\s*date|date)\b[:\s-]*({RE_DATE.pattern})", re.IGNORECASE
        ),
        text,
    )
    due_date = capture_first(
        re.compile(rf"\b(?:due\s*date)\b[:\s-]*({RE_DATE.pattern})", re.IGNORECASE),
        text,
    )

    # Amounts
    subtotal = capture_first(RE_SUBTOTAL, text)
    tax = capture_first(RE_TAX, text)
    discount = capture_first(RE_DISCOUNT, text)
    total = capture_first(RE_TOTAL, text)

    vendor = guess_vendor(lines)

    return ExtractedInvoice(
        kind="invoice",
        vendor=vendor,
        invoice_number=invoice_no,
        po_number=po_no,
        invoice_date=invoice_date,
        due_date=due_date,
        subtotal=subtotal,
        tax=tax,
        discount=discount,
        total=total,
        currency=currency,
        emails=emails,
        phones=phones,
        raw={
            "first_date_hit": capture_first(RE_DATE, text) or "",
            "first_amount_like_total": total or "",
        },
    )


def extract_paystub(text: str, lines: List[str]) -> ExtractedPaystub:
    emails = capture_all(RE_EMAIL, text)
    phones = capture_all(RE_PHONE, text)
    currency = detect_currency(text)

    pay_period_m = RE_PAY_PERIOD.search(text)
    p_start = pay_period_m.group(1) if pay_period_m else None
    p_end = pay_period_m.group(2) if pay_period_m else None
    pay_date = capture_first(RE_PAY_DATE, text)

    gross = capture_first(RE_GROSS_PAY, text)
    net = capture_first(RE_NET_PAY, text)

    employer, employee = guess_employer_employee(lines)

    return ExtractedPaystub(
        kind="paystub",
        employer=employer,
        employee=employee,
        pay_period_start=p_start,
        pay_period_end=p_end,
        pay_date=pay_date,
        gross_pay=gross,
        net_pay=net,
        currency=currency,
        emails=emails,
        phones=phones,
        raw={
            "first_date_hit": capture_first(RE_DATE, text) or "",
        },
    )


def extract_from_text(text: str) -> Dict:
    # Lines help with vendor/employer heuristics
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]

    if looks_like_paystub(text):
        return asdict(extract_paystub(text, lines))
    else:
        return asdict(extract_invoice(text, lines))


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


# ---------------------------------- CLI ----------------------------------


def _cli():
    parser = argparse.ArgumentParser(
        description="Extract key fields from normalized OCR text"
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
