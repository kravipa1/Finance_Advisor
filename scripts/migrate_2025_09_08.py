# scripts/migrate_2025_09_08.py
from __future__ import annotations
import sqlite3
from storage.sqlite_store import (
    ensure_schema,
    migrate_add_sanity_flags,
    migrate_add_norm_hash,
    backfill_norm_hashes,
)


def normalize_text(s: str) -> str:
    return " ".join((s or "").split())


if __name__ == "__main__":
    db = "data/finance.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # 1) make sure base table exists
    ensure_schema(conn)
    # 2) add columns/indexes if missing
    migrate_add_sanity_flags(conn)
    migrate_add_norm_hash(conn)
    # 3) try backfill
    try:
        backfill_norm_hashes(conn, has_normalize_fn=normalize_text)
    except Exception as e:
        print("Backfill skipped:", e)

    conn.close()
    print("✅ migration complete")
