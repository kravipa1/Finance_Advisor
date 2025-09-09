# storage/sqlite_store.py
from __future__ import annotations
import sqlite3
from typing import Any, Dict, List


def open_conn(path: str = "data/finance.sqlite") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


CREATE_RECEIPTS = """
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor TEXT,
    date TEXT,
    total REAL,
    subtotal REAL,
    tax REAL,
    tip REAL,
    reconciled_used INTEGER DEFAULT 0,
    items_subtotal_diff REAL DEFAULT 0.0,
    items_subtotal_pct REAL DEFAULT 0.0,
    norm_hash TEXT UNIQUE,
    raw_text TEXT
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(CREATE_RECEIPTS)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(date)")
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_norm_hash ON receipts(norm_hash)"
    )
    conn.commit()


SCHEMA_ALTER_SANITY = [
    "ALTER TABLE receipts ADD COLUMN reconciled_used INTEGER DEFAULT 0;",
    "ALTER TABLE receipts ADD COLUMN items_subtotal_diff REAL DEFAULT 0.0;",
    "ALTER TABLE receipts ADD COLUMN items_subtotal_pct REAL DEFAULT 0.0;",
]

SCHEMA_ALTER_HASH = [
    "ALTER TABLE receipts ADD COLUMN norm_hash TEXT;",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_norm_hash ON receipts(norm_hash);",
]


def migrate_add_sanity_flags(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for stmt in SCHEMA_ALTER_SANITY:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def migrate_add_norm_hash(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for stmt in SCHEMA_ALTER_HASH:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def exists_by_hash(conn: sqlite3.Connection, norm_hash: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM receipts WHERE norm_hash = ? LIMIT 1", (norm_hash,))
    return cur.fetchone() is not None


def delete_by_hash(conn: sqlite3.Connection, norm_hash: str) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM receipts WHERE norm_hash = ?", (norm_hash,))
    conn.commit()
    return cur.rowcount


def insert_receipt(conn: sqlite3.Connection, row: Dict[str, Any]) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO receipts
            (vendor, date, total, subtotal, tax, tip,
             reconciled_used, items_subtotal_diff, items_subtotal_pct,
             norm_hash, raw_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("vendor"),
            row.get("date"),
            row.get("total"),
            row.get("subtotal"),
            row.get("tax"),
            row.get("tip"),
            row.get("reconciled_used", 0),
            row.get("items_subtotal_diff", 0.0),
            row.get("items_subtotal_pct", 0.0),
            row.get("norm_hash"),
            row.get("raw_text"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_receipt_fields(
    conn: sqlite3.Connection, rid: int, row: Dict[str, Any]
) -> None:
    """
    Update parsed fields for an existing receipt by id.
    Does NOT change norm_hash or raw_text.
    """
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE receipts
        SET vendor=?,
            date=?,
            total=?,
            subtotal=?,
            tax=?,
            tip=?,
            reconciled_used=?,
            items_subtotal_diff=?,
            items_subtotal_pct=?
        WHERE id=?
        """,
        (
            row.get("vendor"),
            row.get("date"),
            row.get("total"),
            row.get("subtotal"),
            row.get("tax"),
            row.get("tip"),
            row.get("reconciled_used", 0),
            row.get("items_subtotal_diff", 0.0),
            row.get("items_subtotal_pct", 0.0),
            rid,
        ),
    )
    conn.commit()


def fetch_receipts(conn: sqlite3.Connection, limit: int = 200) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, vendor, date, total, subtotal, tax, tip,
               reconciled_used, items_subtotal_diff, items_subtotal_pct,
               norm_hash, raw_text
        FROM receipts
        ORDER BY date DESC NULLS LAST, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cur.fetchall()


def backfill_norm_hashes(conn: sqlite3.Connection, *, has_normalize_fn=None) -> None:
    from sfa_utils.fingerprint import normalized_text_fingerprint

    cur = conn.cursor()
    cur.execute("SELECT id, raw_text FROM receipts WHERE norm_hash IS NULL")
    rows = cur.fetchall()
    for r in rows:
        rid, raw = r["id"], r["raw_text"]
        if not raw:
            continue
        text = has_normalize_fn(raw) if has_normalize_fn else raw
        nh = normalized_text_fingerprint(text)
        try:
            cur.execute("UPDATE receipts SET norm_hash=? WHERE id=?", (nh, rid))
        except sqlite3.IntegrityError:
            pass
    conn.commit()
