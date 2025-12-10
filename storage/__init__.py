# storage/__init__.py
"""
Storage layer for Smart Finance Advisor.

Provides SQLite-based persistence for documents, line items,
transactions, merchants, and categories.
"""

from .sqlite_store import (
    # New schema class
    SQLiteStore,
    # Legacy functions (backward compatibility)
    open_conn,
    ensure_schema,
    exists_by_hash,
    delete_by_hash,
    insert_receipt,
    update_receipt_fields,
    fetch_receipts,
    backfill_norm_hashes,
    migrate_add_sanity_flags,
    migrate_add_norm_hash,
    generate_doc_id,
)

from .migrations import (
    ensure_current_schema,
    check_integrity,
    get_table_stats,
    refresh_views,
    normalize_merchant_key,
    migrate_to_v4,
    initialize_fresh_db,
    SCHEMA_VERSION,
)

from .schema import (
    SCHEMA_VERSION as CURRENT_SCHEMA_VERSION,
    DEFAULT_CATEGORIES,
)

__all__ = [
    # Main class
    "SQLiteStore",
    # Schema info
    "SCHEMA_VERSION",
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_CATEGORIES",
    # Migration functions
    "ensure_current_schema",
    "check_integrity",
    "get_table_stats",
    "refresh_views",
    "normalize_merchant_key",
    "migrate_to_v4",
    "initialize_fresh_db",
    # Legacy functions
    "open_conn",
    "ensure_schema",
    "exists_by_hash",
    "delete_by_hash",
    "insert_receipt",
    "update_receipt_fields",
    "fetch_receipts",
    "backfill_norm_hashes",
    "migrate_add_sanity_flags",
    "migrate_add_norm_hash",
    "generate_doc_id",
]
