# parser/doc_type.py
from __future__ import annotations
from dataclasses import dataclass

INVOICE_TOKENS = {
    "invoice": 3,
    "subtotal": 1,
    "tax": 1,
    "gst": 1,
    "vat": 1,
    "amount due": 2,
    "balance due": 2,
    "purchase order": 2,
    "po #": 2,
    "bill to": 2,
    "ship to": 1,
}
PAYSTUB_TOKENS = {
    "pay period": 3,
    "gross pay": 2,
    "net pay": 3,
    "ytd": 1,
    "earnings": 1,
    "deductions": 1,
    "employee": 1,
    "pay date": 2,
    "hours": 1,
    "rate": 1,
}


@dataclass
class DocTypeScore:
    invoice: int
    paystub: int
    kind: str


def score(text: str) -> DocTypeScore:
    t = text.lower()
    inv = sum(w for k, w in INVOICE_TOKENS.items() if k in t)
    pay = sum(w for k, w in PAYSTUB_TOKENS.items() if k in t)
    kind = "invoice" if inv >= pay else "paystub"
    return DocTypeScore(invoice=inv, paystub=pay, kind=kind)
