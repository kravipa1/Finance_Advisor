# storage/migrations.py
"""
Database migration utilities for Smart Finance Advisor.

Handles schema upgrades from any version to current, including:
- Fresh database initialization
- Migration from legacy receipts table to documents
- Adding new tables (line_items, transactions, merchants, categories)
- Creating/refreshing compatibility views
"""
from __future__ import annotations

import sqlite3
import uuid
import re
from typing import Dict, List, Any
from datetime import datetime

from .schema import (
    SCHEMA_VERSION,
    ALL_TABLES,
    ALL_VIEWS,
    CREATE_INDEXES,
    DEFAULT_CATEGORIES,
)


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version, or 0 if not initialized."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT MAX(version) FROM schema_version")
        row = cur.fetchone()
        return row[0] if row and row[0] else 0
    except sqlite3.OperationalError:
        # schema_version table doesn't exist
        return 0


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Record schema version."""
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
        (version, datetime.utcnow().isoformat()),
    )
    conn.commit()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cur.fetchone() is not None


def view_exists(conn: sqlite3.Connection, view_name: str) -> bool:
    """Check if a view exists."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
        (view_name,),
    )
    return cur.fetchone() is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    """Get list of column names for a table."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]


def detect_legacy_schema(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Detect what legacy schema elements exist.
    Returns info about what needs to be migrated.
    """
    info = {
        "has_receipts": table_exists(conn, "receipts"),
        "has_documents": table_exists(conn, "documents"),
        "has_line_items": table_exists(conn, "line_items"),
        "has_transactions": table_exists(conn, "transactions"),
        "has_merchants": table_exists(conn, "merchants"),
        "has_categories": table_exists(conn, "categories"),
        "has_schema_version": table_exists(conn, "schema_version"),
        "receipts_columns": [],
        "receipts_count": 0,
    }

    if info["has_receipts"]:
        info["receipts_columns"] = get_table_columns(conn, "receipts")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM receipts")
        info["receipts_count"] = cur.fetchone()[0]

    return info


def normalize_merchant_key(raw: str) -> str:
    """
    Normalize merchant name to a stable key.
    "McDonald's #1234" -> "mcdonalds"
    "WAL-MART SUPERCENTER" -> "walmart"
    """
    if not raw:
        return ""

    # Lowercase
    key = raw.lower()

    # Remove store numbers (#1234, Store 567, etc.)
    key = re.sub(r"#\s*\d+", "", key)
    key = re.sub(r"store\s*\d+", "", key, flags=re.IGNORECASE)

    # Remove common suffixes
    key = re.sub(r"\b(inc|llc|corp|ltd|co)\b\.?", "", key, flags=re.IGNORECASE)

    # Remove punctuation and special chars
    key = re.sub(r"[^\w\s]", "", key)

    # Collapse whitespace and strip
    key = re.sub(r"\s+", "", key).strip()

    return key


def generate_doc_id() -> str:
    """Generate a unique document ID."""
    return str(uuid.uuid4())[:12]


def migrate_receipts_to_documents(conn: sqlite3.Connection) -> Dict[str, int]:
    """
    Migrate data from legacy receipts table to new documents table.
    Returns stats about migration.
    """
    stats = {"migrated": 0, "skipped": 0, "errors": 0}

    cur = conn.cursor()

    # Get all receipts
    cur.execute(
        """
        SELECT id, vendor, date, total, subtotal, tax, tip,
               reconciled_used, items_subtotal_diff, items_subtotal_pct,
               norm_hash, raw_text
        FROM receipts
    """
    )
    receipts = cur.fetchall()

    for row in receipts:
        try:
            doc_id = generate_doc_id()
            vendor = row[1]
            vendor_norm = normalize_merchant_key(vendor) if vendor else None

            cur.execute(
                """
                INSERT INTO documents (
                    doc_id, doc_type, vendor, vendor_norm, date,
                    total, subtotal, tax, tip,
                    reconciled_used, items_subtotal_diff, items_subtotal_pct,
                    norm_hash, raw_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    doc_id,
                    "receipt",
                    vendor,
                    vendor_norm,
                    row[2],  # date
                    row[3],  # total
                    row[4],  # subtotal
                    row[5],  # tax
                    row[6],  # tip
                    row[7],  # reconciled_used
                    row[8],  # items_subtotal_diff
                    row[9],  # items_subtotal_pct
                    row[10],  # norm_hash
                    row[11],  # raw_text
                ),
            )
            stats["migrated"] += 1
        except sqlite3.IntegrityError:
            # Duplicate norm_hash - skip
            stats["skipped"] += 1
        except Exception:
            stats["errors"] += 1

    conn.commit()
    return stats


def seed_default_categories(conn: sqlite3.Connection) -> int:
    """Insert default categories. Returns count inserted."""
    cur = conn.cursor()
    inserted = 0

    for name, parent, desc, icon, color in DEFAULT_CATEGORIES:
        try:
            cur.execute(
                """
                INSERT INTO categories (name, parent_category, description, icon, color)
                VALUES (?, ?, ?, ?, ?)
            """,
                (name, parent, desc, icon, color),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # Already exists
            pass

    conn.commit()
    return inserted


def create_all_tables(conn: sqlite3.Connection) -> None:
    """Create all tables defined in schema."""
    cur = conn.cursor()
    for ddl in ALL_TABLES:
        cur.execute(ddl)
    conn.commit()


def create_all_indexes(conn: sqlite3.Connection) -> None:
    """Create all indexes."""
    cur = conn.cursor()
    for ddl in CREATE_INDEXES:
        try:
            cur.execute(ddl)
        except sqlite3.OperationalError:
            pass  # Index already exists
    conn.commit()


def drop_views(conn: sqlite3.Connection) -> None:
    """Drop all compatibility views (for refresh)."""
    cur = conn.cursor()
    views = ["documents_v", "line_items_v", "transactions_v", "receipts_v"]
    for view in views:
        cur.execute(f"DROP VIEW IF EXISTS {view}")
    conn.commit()


def create_all_views(conn: sqlite3.Connection) -> None:
    """Create all compatibility views."""
    cur = conn.cursor()
    for ddl in ALL_VIEWS:
        cur.execute(ddl)
    conn.commit()


def refresh_views(conn: sqlite3.Connection) -> None:
    """Drop and recreate all views."""
    drop_views(conn)
    create_all_views(conn)


def initialize_fresh_db(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Initialize a fresh database with full schema.
    Returns initialization stats.
    """
    stats = {
        "tables_created": 0,
        "indexes_created": 0,
        "views_created": 0,
        "categories_seeded": 0,
    }

    # Create tables
    create_all_tables(conn)
    stats["tables_created"] = len(ALL_TABLES)

    # Create indexes
    create_all_indexes(conn)
    stats["indexes_created"] = len(CREATE_INDEXES)

    # Create views
    create_all_views(conn)
    stats["views_created"] = len(ALL_VIEWS)

    # Seed categories
    stats["categories_seeded"] = seed_default_categories(conn)

    # Set version
    set_schema_version(conn, SCHEMA_VERSION)

    return stats


def migrate_to_v4(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Migrate from any earlier version to v4 (full schema).
    Handles:
    - Fresh DB (no tables)
    - Legacy receipts table only
    - Partial schema
    """
    stats = {
        "from_version": get_schema_version(conn),
        "to_version": SCHEMA_VERSION,
        "receipts_migrated": 0,
        "tables_created": [],
        "views_created": [],
    }

    legacy = detect_legacy_schema(conn)

    # Create schema_version table first if missing
    if not legacy["has_schema_version"]:
        conn.execute(ALL_TABLES[0])  # CREATE_SCHEMA_VERSION
        conn.commit()

    # Create core tables if missing
    if not legacy["has_documents"]:
        conn.execute(ALL_TABLES[1])  # CREATE_DOCUMENTS
        stats["tables_created"].append("documents")
        conn.commit()

    if not legacy["has_line_items"]:
        conn.execute(ALL_TABLES[2])  # CREATE_LINE_ITEMS
        stats["tables_created"].append("line_items")
        conn.commit()

    if not legacy["has_transactions"]:
        conn.execute(ALL_TABLES[3])  # CREATE_TRANSACTIONS
        stats["tables_created"].append("transactions")
        conn.commit()

    if not legacy["has_merchants"]:
        conn.execute(ALL_TABLES[4])  # CREATE_MERCHANTS
        stats["tables_created"].append("merchants")
        conn.commit()

    if not legacy["has_categories"]:
        conn.execute(ALL_TABLES[5])  # CREATE_CATEGORIES
        stats["tables_created"].append("categories")
        seed_default_categories(conn)
        conn.commit()

    # Migrate receipts if they exist and documents table was just created
    if legacy["has_receipts"] and "documents" in stats["tables_created"]:
        migration_result = migrate_receipts_to_documents(conn)
        stats["receipts_migrated"] = migration_result["migrated"]

    # Create indexes
    create_all_indexes(conn)

    # Refresh views
    refresh_views(conn)
    stats["views_created"] = [
        "documents_v",
        "line_items_v",
        "transactions_v",
        "receipts_v",
    ]

    # Update version
    set_schema_version(conn, SCHEMA_VERSION)

    return stats


def ensure_current_schema(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Ensure database has current schema. Migrate if needed.
    This is the main entry point for schema management.
    """
    current_version = get_schema_version(conn)

    if current_version == SCHEMA_VERSION:
        # Already current - just ensure views exist
        if not all(
            [
                view_exists(conn, "documents_v"),
                view_exists(conn, "line_items_v"),
                view_exists(conn, "transactions_v"),
            ]
        ):
            refresh_views(conn)
            return {"status": "views_refreshed", "version": SCHEMA_VERSION}
        return {"status": "current", "version": SCHEMA_VERSION}

    if current_version == 0 and not detect_legacy_schema(conn)["has_receipts"]:
        # Fresh database
        stats = initialize_fresh_db(conn)
        return {"status": "initialized", **stats}

    # Need migration
    stats = migrate_to_v4(conn)
    return {"status": "migrated", **stats}


def check_integrity(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Run integrity checks on the database.
    Returns detailed status report.
    """
    result = {
        "status": "ok",
        "version": get_schema_version(conn),
        "tables": {},
        "views": {},
        "integrity_check": None,
        "issues": [],
    }

    cur = conn.cursor()

    # SQLite integrity check
    cur.execute("PRAGMA integrity_check")
    integrity = cur.fetchone()[0]
    result["integrity_check"] = integrity
    if integrity != "ok":
        result["status"] = "error"
        result["issues"].append(f"Integrity check failed: {integrity}")

    # Check tables
    expected_tables = [
        "documents",
        "line_items",
        "transactions",
        "merchants",
        "categories",
    ]
    for table in expected_tables:
        if table_exists(conn, table):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            result["tables"][table] = {
                "exists": True,
                "rows": count,
                "empty": count == 0,
            }
        else:
            result["tables"][table] = {"exists": False, "rows": 0, "empty": True}
            result["status"] = "warning"
            result["issues"].append(f"Missing table: {table}")

    # Check views
    expected_views = ["documents_v", "line_items_v", "transactions_v"]
    for view_name in expected_views:
        result["views"][view_name] = view_exists(conn, view_name)
        if not result["views"][view_name]:
            result["status"] = "warning"
            result["issues"].append(f"Missing view: {view_name}")

    # Check for empties that shouldn't be empty
    if result["tables"].get("documents", {}).get("rows", 0) > 0:
        if result["tables"].get("transactions", {}).get("rows", 0) == 0:
            result["issues"].append(
                "Documents exist but no transactions - run categorize"
            )

    return result


def get_table_stats(conn: sqlite3.Connection) -> Dict[str, int]:
    """Get row counts for all tables."""
    stats = {}
    cur = conn.cursor()

    tables = ["documents", "line_items", "transactions", "merchants", "categories"]
    for table in tables:
        if table_exists(conn, table):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cur.fetchone()[0]
        else:
            stats[table] = -1  # Doesn't exist

    # Also check legacy receipts
    if table_exists(conn, "receipts"):
        cur.execute("SELECT COUNT(*) FROM receipts")
        stats["receipts_legacy"] = cur.fetchone()[0]

    return stats
