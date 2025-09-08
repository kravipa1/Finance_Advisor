# storage/sqlite_store.py
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, List


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")  # <— add this
        cur = con.cursor()
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            vendor_or_employer TEXT,
            invoice_number TEXT,
            po_number TEXT,
            invoice_date_iso TEXT,
            due_date_iso TEXT,
            gross_pay REAL,
            net_pay REAL,
            subtotal REAL,
            tax REAL,
            discount REAL,
            total REAL,
            currency_hint TEXT,
            category TEXT,
            raw_json TEXT NOT NULL
        )"""
        )
        cur.execute(
            """
        CREATE TABLE IF NOT EXISTS line_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            idx INTEGER,
            qty REAL,
            description TEXT,
            unit_price_value REAL,
            unit_price_currency TEXT,
            line_total_value REAL,
            line_total_currency TEXT,
            category TEXT
        )"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_line_items_doc ON line_items(document_id)"
        )
        con.commit()


def _num(val: Any) -> Optional[float]:
    try:
        if val is None:
            return None
        return float(val)
    except Exception:
        return None


def _amount_val(d: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(d, dict):
        return None
    return _num(d.get("value"))


def _amount_ccy(d: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(d, dict):
        return None
    return d.get("currency")


def save_document(db_path: Path, doc: Dict[str, Any]) -> int:
    init_db(db_path)

    # >>> define all values FIRST
    kind = doc.get("kind")
    vendor_or_employer = (
        doc.get("vendor") if kind == "invoice" else doc.get("employer")
    ) or None

    invoice_number = doc.get("invoice_number") or None
    po_number = doc.get("po_number") or None
    invoice_date_iso = (doc.get("invoice_date") or {}).get("iso")
    due_date_iso = (doc.get("due_date") or {}).get("iso")

    gross_pay = _amount_val(doc.get("gross_pay"))
    net_pay = _amount_val(doc.get("net_pay"))
    subtotal = _amount_val(doc.get("subtotal"))
    tax = _amount_val(doc.get("tax"))
    discount = _amount_val(doc.get("discount"))
    total = _amount_val(doc.get("total"))

    currency_hint = doc.get("currency_hint")
    category = doc.get("category")
    raw_json = json.dumps(doc, ensure_ascii=False)

    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        cur = con.cursor()
        cur.execute(
            """
        INSERT INTO documents (
            kind, vendor_or_employer, invoice_number, po_number,
            invoice_date_iso, due_date_iso, gross_pay, net_pay,
            subtotal, tax, discount, total, currency_hint, category, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                kind,
                vendor_or_employer,
                invoice_number,
                po_number,
                invoice_date_iso,
                due_date_iso,
                gross_pay,
                net_pay,
                subtotal,
                tax,
                discount,
                total,
                currency_hint,
                category,
                raw_json,
            ),
        )

        # guard Optional[int]
        doc_id_val: Optional[int] = cur.lastrowid
        if doc_id_val is None:
            raise RuntimeError("SQLite did not return lastrowid after insert.")
        doc_id = int(doc_id_val)

        # line items
        for idx, it in enumerate(doc.get("line_items") or []):
            desc = it.get("description") or it.get("desc")
            qty = _num(it.get("qty"))
            upv = _amount_val(it.get("unit_price"))
            upc = _amount_ccy(it.get("unit_price"))
            ltv = _amount_val(it.get("line_total"))
            ltc = _amount_ccy(it.get("line_total"))
            cat = it.get("category")
            cur.execute(
                """
            INSERT INTO line_items (
                document_id, idx, qty, description,
                unit_price_value, unit_price_currency,
                line_total_value, line_total_currency, category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (doc_id, idx, qty, desc, upv, upc, ltv, ltc, cat),
            )

        con.commit()
    return doc_id


def fetch_recent(db_path: Path, limit: int = 5) -> List[Dict[str, Any]]:
    init_db(db_path)  # ensure tables exist
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(
            "SELECT id, kind, vendor_or_employer, total, net_pay, category "
            "FROM documents ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]
