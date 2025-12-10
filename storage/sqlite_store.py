# storage/sqlite_store.py
"""
SQLite storage layer for Smart Finance Advisor.

Provides CRUD operations for:
- Documents (receipts, invoices, paystubs)
- Line items
- Transactions (categorized)
- Merchants
- Categories
"""
from __future__ import annotations

import sqlite3
import json
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime

from .migrations import (
    ensure_current_schema,
    normalize_merchant_key,
    check_integrity,
    get_table_stats,
    refresh_views,
    table_exists,
)


def open_conn(path: str = "data/finance.sqlite") -> sqlite3.Connection:
    """Open a database connection with row factory."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def generate_doc_id() -> str:
    """Generate a unique document ID."""
    return str(uuid.uuid4())[:12]


# =============================================================================
# Legacy compatibility functions (keep existing tests working)
# =============================================================================

# Import legacy schema for backward compatibility
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
    """Legacy: ensure basic receipts table exists."""
    cur = conn.cursor()
    cur.execute(CREATE_RECEIPTS)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(date)")
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_norm_hash ON receipts(norm_hash)"
    )
    conn.commit()


def exists_by_hash(conn: sqlite3.Connection, norm_hash: str) -> bool:
    """Check if document/receipt exists by normalized hash."""
    cur = conn.cursor()
    # Try documents first (new schema), fall back to receipts
    if table_exists(conn, "documents"):
        cur.execute("SELECT 1 FROM documents WHERE norm_hash = ? LIMIT 1", (norm_hash,))
        if cur.fetchone():
            return True
    if table_exists(conn, "receipts"):
        cur.execute("SELECT 1 FROM receipts WHERE norm_hash = ? LIMIT 1", (norm_hash,))
        if cur.fetchone():
            return True
    return False


def delete_by_hash(conn: sqlite3.Connection, norm_hash: str) -> int:
    """Delete document/receipt by normalized hash."""
    cur = conn.cursor()
    total_deleted = 0

    if table_exists(conn, "documents"):
        cur.execute("DELETE FROM documents WHERE norm_hash = ?", (norm_hash,))
        total_deleted += cur.rowcount

    if table_exists(conn, "receipts"):
        cur.execute("DELETE FROM receipts WHERE norm_hash = ?", (norm_hash,))
        total_deleted += cur.rowcount

    conn.commit()
    return total_deleted


def insert_receipt(conn: sqlite3.Connection, row: Dict[str, Any]) -> int:
    """Legacy: insert into receipts table."""
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
    """Legacy: Update parsed fields for an existing receipt by id."""
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
    """Legacy: fetch receipts, trying documents first."""
    cur = conn.cursor()

    # Try new schema first
    if table_exists(conn, "documents"):
        cur.execute(
            """
            SELECT id, vendor, date, total, subtotal, tax, tip,
                   reconciled_used, items_subtotal_diff, items_subtotal_pct,
                   norm_hash, raw_text
            FROM documents
            ORDER BY date DESC NULLS LAST, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()

    # Fall back to legacy receipts
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
    """Legacy: backfill norm_hash for receipts without one."""
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


# Legacy migration stubs
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
    """Legacy migration: add sanity flag columns."""
    cur = conn.cursor()
    for stmt in SCHEMA_ALTER_SANITY:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def migrate_add_norm_hash(conn: sqlite3.Connection) -> None:
    """Legacy migration: add norm_hash column."""
    cur = conn.cursor()
    for stmt in SCHEMA_ALTER_HASH:
        try:
            cur.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()


# =============================================================================
# New Schema Operations
# =============================================================================


class SQLiteStore:
    """
    Main storage class for new schema operations.
    Provides typed CRUD for documents, line_items, transactions, merchants.
    """

    def __init__(self, db_path: str = "data/finance.sqlite"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = open_conn(self.db_path)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def ensure_schema(self) -> Dict[str, Any]:
        """Ensure database has current schema."""
        return ensure_current_schema(self.conn)

    def check_integrity(self) -> Dict[str, Any]:
        """Run integrity checks."""
        return check_integrity(self.conn)

    def get_stats(self) -> Dict[str, int]:
        """Get row counts for all tables."""
        return get_table_stats(self.conn)

    def refresh_views(self) -> None:
        """Refresh compatibility views."""
        refresh_views(self.conn)

    # =========================================================================
    # Document Operations
    # =========================================================================

    def insert_document(
        self,
        vendor: Optional[str] = None,
        date: Optional[str] = None,
        total: Optional[float] = None,
        subtotal: Optional[float] = None,
        tax: Optional[float] = None,
        tip: Optional[float] = None,
        raw_text: Optional[str] = None,
        norm_hash: Optional[str] = None,
        doc_type: str = "receipt",
        source_file: Optional[str] = None,
        currency: str = "USD",
        extraction_confidence: Optional[float] = None,
        reconciled_used: int = 0,
        items_subtotal_diff: float = 0.0,
        items_subtotal_pct: float = 0.0,
    ) -> int:
        """Insert a new document. Returns the document ID."""
        doc_id = generate_doc_id()
        vendor_norm = normalize_merchant_key(vendor) if vendor else None

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO documents (
                doc_id, doc_type, source_file, vendor, vendor_norm, date,
                total, subtotal, tax, tip, currency, raw_text, norm_hash,
                extraction_confidence, reconciled_used,
                items_subtotal_diff, items_subtotal_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                doc_type,
                source_file,
                vendor,
                vendor_norm,
                date,
                total,
                subtotal,
                tax,
                tip,
                currency,
                raw_text,
                norm_hash,
                extraction_confidence,
                reconciled_used,
                items_subtotal_diff,
                items_subtotal_pct,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get document by doc_id."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_document_by_id(self, id: int) -> Optional[Dict[str, Any]]:
        """Get document by numeric id."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM documents WHERE id = ?", (id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_document_by_hash(self, norm_hash: str) -> Optional[Dict[str, Any]]:
        """Get document by normalized hash."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM documents WHERE norm_hash = ?", (norm_hash,))
        row = cur.fetchone()
        return dict(row) if row else None

    def document_exists(self, norm_hash: str) -> bool:
        """Check if document exists by hash."""
        return self.get_document_by_hash(norm_hash) is not None

    def update_document(self, doc_id: str, **fields) -> bool:
        """Update document fields. Returns True if updated."""
        if not fields:
            return False

        # Handle vendor_norm auto-update
        if "vendor" in fields and "vendor_norm" not in fields:
            fields["vendor_norm"] = normalize_merchant_key(fields["vendor"])

        fields["updated_at"] = datetime.utcnow().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [doc_id]

        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE documents SET {set_clause} WHERE doc_id = ?",
            values,
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete_document(self, doc_id: str) -> bool:
        """Delete document and cascade to line_items/transactions."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_documents(
        self,
        limit: int = 100,
        offset: int = 0,
        doc_type: Optional[str] = None,
        vendor_norm: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List documents with optional filters."""
        conditions = []
        params = []

        if doc_type:
            conditions.append("doc_type = ?")
            params.append(doc_type)
        if vendor_norm:
            conditions.append("vendor_norm = ?")
            params.append(vendor_norm)
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT * FROM documents
            {where}
            ORDER BY date DESC NULLS LAST, id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        )
        return [dict(row) for row in cur.fetchall()]

    # =========================================================================
    # Line Item Operations
    # =========================================================================

    def insert_line_item(
        self,
        document_id: int,
        description: Optional[str] = None,
        quantity: Optional[float] = None,
        unit_price: Optional[float] = None,
        amount: Optional[float] = None,
        line_number: Optional[int] = None,
        weight_qty: Optional[float] = None,
        weight_unit: Optional[str] = None,
        raw_line: Optional[str] = None,
    ) -> int:
        """Insert a line item. Returns the line item ID."""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO line_items (
                document_id, line_number, description, quantity,
                unit_price, amount, weight_qty, weight_unit, raw_line
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                line_number,
                description,
                quantity,
                unit_price,
                amount,
                weight_qty,
                weight_unit,
                raw_line,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def insert_line_items_batch(
        self, document_id: int, items: List[Dict[str, Any]]
    ) -> List[int]:
        """Insert multiple line items. Returns list of IDs."""
        ids = []
        for i, item in enumerate(items):
            item_id = self.insert_line_item(
                document_id=document_id,
                line_number=item.get("line_number", i + 1),
                description=item.get("description"),
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                amount=item.get("amount") or item.get("total"),
                weight_qty=item.get("weight_qty"),
                weight_unit=item.get("weight_unit"),
                raw_line=item.get("raw_line"),
            )
            ids.append(item_id)
        return ids

    def get_line_items(self, document_id: int) -> List[Dict[str, Any]]:
        """Get all line items for a document."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM line_items
            WHERE document_id = ?
            ORDER BY line_number, id
            """,
            (document_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    def delete_line_items(self, document_id: int) -> int:
        """Delete all line items for a document. Returns count deleted."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM line_items WHERE document_id = ?", (document_id,))
        self.conn.commit()
        return cur.rowcount

    # =========================================================================
    # Transaction Operations
    # =========================================================================

    def insert_transaction(
        self,
        document_id: int,
        amount: float,
        date: Optional[str] = None,
        merchant_norm: Optional[str] = None,
        primary_category: Optional[str] = None,
        secondary_category: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[List[str]] = None,
        rule_name: Optional[str] = None,
        line_item_id: Optional[int] = None,
    ) -> int:
        """Insert a transaction. Returns the transaction ID."""
        tags_json = json.dumps(tags) if tags else None

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO transactions (
                document_id, line_item_id, merchant_norm, amount, date,
                primary_category, secondary_category, confidence, tags, rule_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                line_item_id,
                merchant_norm,
                amount,
                date,
                primary_category,
                secondary_category,
                confidence,
                tags_json,
                rule_name,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_transaction(self, txn_id: int) -> Optional[Dict[str, Any]]:
        """Get transaction by ID."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,))
        row = cur.fetchone()
        if row:
            result = dict(row)
            if result.get("tags"):
                result["tags"] = json.loads(result["tags"])
            return result
        return None

    def get_transactions_for_document(self, document_id: int) -> List[Dict[str, Any]]:
        """Get all transactions for a document."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM transactions WHERE document_id = ? ORDER BY id",
            (document_id,),
        )
        results = []
        for row in cur.fetchall():
            result = dict(row)
            if result.get("tags"):
                result["tags"] = json.loads(result["tags"])
            results.append(result)
        return results

    def update_transaction_category(
        self,
        txn_id: int,
        primary_category: Optional[str] = None,
        secondary_category: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[List[str]] = None,
        rule_name: Optional[str] = None,
    ) -> bool:
        """Update transaction categorization. Returns True if updated."""
        fields = {"updated_at": datetime.utcnow().isoformat()}

        if primary_category is not None:
            fields["primary_category"] = primary_category
        if secondary_category is not None:
            fields["secondary_category"] = secondary_category
        if confidence is not None:
            fields["confidence"] = confidence
        if tags is not None:
            fields["tags"] = json.dumps(tags)
        if rule_name is not None:
            fields["rule_name"] = rule_name

        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [txn_id]

        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE transactions SET {set_clause} WHERE id = ?",
            values,
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete_transactions_for_document(self, document_id: int) -> int:
        """Delete all transactions for a document. Returns count deleted."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM transactions WHERE document_id = ?", (document_id,))
        self.conn.commit()
        return cur.rowcount

    def list_transactions(
        self,
        limit: int = 100,
        offset: int = 0,
        category: Optional[str] = None,
        merchant_norm: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        uncategorized_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List transactions with optional filters."""
        conditions = []
        params = []

        if category:
            conditions.append("primary_category = ?")
            params.append(category)
        if merchant_norm:
            conditions.append("merchant_norm = ?")
            params.append(merchant_norm)
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)
        if uncategorized_only:
            conditions.append(
                "(primary_category IS NULL OR primary_category = 'Uncategorized')"
            )

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT * FROM transactions
            {where}
            ORDER BY date DESC NULLS LAST, id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        )

        results = []
        for row in cur.fetchall():
            result = dict(row)
            if result.get("tags"):
                result["tags"] = json.loads(result["tags"])
            results.append(result)
        return results

    # =========================================================================
    # Merchant Operations
    # =========================================================================

    def upsert_merchant(
        self,
        merchant_key: str,
        display_name: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        default_category: Optional[str] = None,
    ) -> int:
        """Insert or update merchant. Returns merchant ID."""
        aliases_json = json.dumps(aliases) if aliases else None

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO merchants (merchant_key, display_name, aliases, default_category)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(merchant_key) DO UPDATE SET
                display_name = COALESCE(excluded.display_name, merchants.display_name),
                aliases = COALESCE(excluded.aliases, merchants.aliases),
                default_category = COALESCE(excluded.default_category, merchants.default_category)
            """,
            (merchant_key, display_name, aliases_json, default_category),
        )
        self.conn.commit()

        # Get the ID
        cur.execute("SELECT id FROM merchants WHERE merchant_key = ?", (merchant_key,))
        return cur.fetchone()[0]

    def get_merchant(self, merchant_key: str) -> Optional[Dict[str, Any]]:
        """Get merchant by key."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM merchants WHERE merchant_key = ?", (merchant_key,))
        row = cur.fetchone()
        if row:
            result = dict(row)
            if result.get("aliases"):
                result["aliases"] = json.loads(result["aliases"])
            return result
        return None

    def list_merchants(self) -> List[Dict[str, Any]]:
        """List all merchants."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM merchants ORDER BY display_name, merchant_key")
        results = []
        for row in cur.fetchall():
            result = dict(row)
            if result.get("aliases"):
                result["aliases"] = json.loads(result["aliases"])
            results.append(result)
        return results

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def normalize_all_merchants(self) -> Dict[str, int]:
        """
        Backfill vendor_norm for all documents missing it.
        Also populates merchants table.
        Returns stats.
        """
        stats = {"updated": 0, "merchants_added": 0}
        cur = self.conn.cursor()

        # Update documents missing vendor_norm
        cur.execute(
            "SELECT id, vendor FROM documents WHERE vendor IS NOT NULL AND vendor_norm IS NULL"
        )
        for row in cur.fetchall():
            doc_id = row[0]
            vendor = row[1]
            vendor_norm = normalize_merchant_key(vendor)
            if vendor_norm:
                cur.execute(
                    "UPDATE documents SET vendor_norm = ? WHERE id = ?",
                    (vendor_norm, doc_id),
                )
                stats["updated"] += 1

        self.conn.commit()

        # Populate merchants table from unique vendor_norms
        cur.execute(
            """
            SELECT DISTINCT vendor_norm, vendor
            FROM documents
            WHERE vendor_norm IS NOT NULL
        """
        )
        for row in cur.fetchall():
            vendor_norm, vendor = row
            try:
                cur.execute(
                    """
                    INSERT INTO merchants (merchant_key, display_name)
                    VALUES (?, ?)
                    """,
                    (vendor_norm, vendor),
                )
                stats["merchants_added"] += 1
            except sqlite3.IntegrityError:
                pass

        self.conn.commit()
        return stats

    def get_uncategorized_documents(self) -> List[Dict[str, Any]]:
        """Get documents that don't have transactions yet."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT d.*
            FROM documents d
            LEFT JOIN transactions t ON d.id = t.document_id
            WHERE t.id IS NULL
            ORDER BY d.date DESC, d.id DESC
        """
        )
        return [dict(row) for row in cur.fetchall()]

    # =========================================================================
    # Analytics Queries
    # =========================================================================

    def spending_by_category(
        self, date_from: Optional[str] = None, date_to: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get spending totals by category."""
        conditions = []
        params = []

        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT
                COALESCE(primary_category, 'Uncategorized') as category,
                COUNT(*) as count,
                SUM(amount) as total
            FROM transactions
            {where}
            GROUP BY primary_category
            ORDER BY total DESC
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]

    def spending_by_merchant(
        self,
        limit: int = 10,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get top merchants by spending."""
        conditions = ["merchant_norm IS NOT NULL"]
        params = []

        if date_from:
            conditions.append("t.date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("t.date <= ?")
            params.append(date_to)

        where = f"WHERE {' AND '.join(conditions)}"

        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT
                t.merchant_norm,
                COALESCE(m.display_name, t.merchant_norm) as merchant_display,
                COUNT(*) as count,
                SUM(t.amount) as total
            FROM transactions t
            LEFT JOIN merchants m ON t.merchant_norm = m.merchant_key
            {where}
            GROUP BY t.merchant_norm
            ORDER BY total DESC
            LIMIT ?
            """,
            params + [limit],
        )
        return [dict(row) for row in cur.fetchall()]

    def spending_over_time(
        self,
        group_by: str = "day",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get spending over time, grouped by day/week/month."""
        conditions = ["date IS NOT NULL"]
        params = []

        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)

        where = f"WHERE {' AND '.join(conditions)}"

        if group_by == "month":
            date_expr = "strftime('%Y-%m', date)"
        elif group_by == "week":
            date_expr = "strftime('%Y-%W', date)"
        else:  # day
            date_expr = "date"

        cur = self.conn.cursor()
        cur.execute(
            f"""
            SELECT
                {date_expr} as period,
                COUNT(*) as count,
                SUM(amount) as total
            FROM transactions
            {where}
            GROUP BY {date_expr}
            ORDER BY period
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]
