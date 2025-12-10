# tests/test_schema_migrations.py
"""
Tests for database schema and migrations.
"""
import sqlite3
import tempfile
import os
import pytest

from storage.schema import (
    SCHEMA_VERSION,
    CREATE_DOCUMENTS,
    DEFAULT_CATEGORIES,
)
from storage.migrations import (
    get_schema_version,
    set_schema_version,
    table_exists,
    view_exists,
    normalize_merchant_key,
    ensure_current_schema,
    check_integrity,
    migrate_receipts_to_documents,
    initialize_fresh_db,
)
from storage.sqlite_store import (
    SQLiteStore,
    ensure_schema,
    insert_receipt,
)


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    # Windows workaround: give time for connections to fully close
    import time

    time.sleep(0.1)
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows sometimes holds file locks


@pytest.fixture
def fresh_conn(temp_db):
    """Create a fresh database connection."""
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
    # Force garbage collection to release file handles on Windows
    import gc

    gc.collect()


@pytest.fixture
def store(temp_db):
    """Create a SQLiteStore instance."""
    with SQLiteStore(temp_db) as s:
        s.ensure_schema()
        yield s


class TestMerchantNormalization:
    """Tests for merchant key normalization."""

    def test_basic_lowercase(self):
        assert normalize_merchant_key("Starbucks") == "starbucks"

    def test_remove_punctuation(self):
        assert normalize_merchant_key("McDonald's") == "mcdonalds"

    def test_remove_store_number(self):
        assert normalize_merchant_key("Walmart #1234") == "walmart"
        assert normalize_merchant_key("Target Store 567") == "target"

    def test_remove_suffixes(self):
        assert normalize_merchant_key("Acme Inc") == "acme"
        assert normalize_merchant_key("Widget Corp.") == "widget"
        assert normalize_merchant_key("Services LLC") == "services"

    def test_collapse_whitespace(self):
        assert normalize_merchant_key("Best   Buy") == "bestbuy"

    def test_empty_string(self):
        assert normalize_merchant_key("") == ""
        assert normalize_merchant_key(None) == ""


class TestSchemaVersion:
    """Tests for schema version tracking."""

    def test_fresh_db_version_zero(self, fresh_conn):
        assert get_schema_version(fresh_conn) == 0

    def test_set_and_get_version(self, fresh_conn):
        fresh_conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        set_schema_version(fresh_conn, 4)
        assert get_schema_version(fresh_conn) == 4


class TestTableDetection:
    """Tests for table/view existence detection."""

    def test_table_not_exists(self, fresh_conn):
        assert not table_exists(fresh_conn, "documents")

    def test_table_exists(self, fresh_conn):
        fresh_conn.execute("CREATE TABLE test_table (id INTEGER)")
        assert table_exists(fresh_conn, "test_table")

    def test_view_not_exists(self, fresh_conn):
        assert not view_exists(fresh_conn, "documents_v")

    def test_view_exists(self, fresh_conn):
        fresh_conn.execute("CREATE TABLE t (id INTEGER)")
        fresh_conn.execute("CREATE VIEW t_v AS SELECT * FROM t")
        assert view_exists(fresh_conn, "t_v")


class TestFreshInitialization:
    """Tests for initializing a fresh database."""

    def test_initialize_creates_all_tables(self, fresh_conn):
        initialize_fresh_db(fresh_conn)

        assert table_exists(fresh_conn, "documents")
        assert table_exists(fresh_conn, "line_items")
        assert table_exists(fresh_conn, "transactions")
        assert table_exists(fresh_conn, "merchants")
        assert table_exists(fresh_conn, "categories")
        assert table_exists(fresh_conn, "schema_version")

    def test_initialize_creates_views(self, fresh_conn):
        initialize_fresh_db(fresh_conn)

        assert view_exists(fresh_conn, "documents_v")
        assert view_exists(fresh_conn, "line_items_v")
        assert view_exists(fresh_conn, "transactions_v")
        assert view_exists(fresh_conn, "receipts_v")

    def test_initialize_seeds_categories(self, fresh_conn):
        stats = initialize_fresh_db(fresh_conn)

        cur = fresh_conn.cursor()
        cur.execute("SELECT COUNT(*) FROM categories")
        count = cur.fetchone()[0]

        assert count == len(DEFAULT_CATEGORIES)
        assert stats["categories_seeded"] == len(DEFAULT_CATEGORIES)

    def test_initialize_sets_version(self, fresh_conn):
        initialize_fresh_db(fresh_conn)
        assert get_schema_version(fresh_conn) == SCHEMA_VERSION


class TestMigrationFromLegacy:
    """Tests for migrating from legacy receipts table."""

    def test_migrate_receipts_to_documents(self, fresh_conn):
        # Create legacy receipts table
        ensure_schema(fresh_conn)

        # Insert a receipt
        insert_receipt(
            fresh_conn,
            {
                "vendor": "Starbucks",
                "date": "2024-01-15",
                "total": 5.50,
                "subtotal": 5.00,
                "tax": 0.50,
                "norm_hash": "abc123",
                "raw_text": "Starbucks receipt...",
            },
        )

        # Create new documents table
        fresh_conn.execute(CREATE_DOCUMENTS)
        fresh_conn.commit()

        # Migrate
        stats = migrate_receipts_to_documents(fresh_conn)

        assert stats["migrated"] == 1
        assert stats["skipped"] == 0
        assert stats["errors"] == 0

        # Verify migration
        cur = fresh_conn.cursor()
        cur.execute("SELECT * FROM documents")
        doc = cur.fetchone()

        assert doc["vendor"] == "Starbucks"
        assert doc["vendor_norm"] == "starbucks"
        assert doc["date"] == "2024-01-15"
        assert doc["total"] == 5.50
        assert doc["doc_type"] == "receipt"

    def test_migrate_skips_duplicates(self, fresh_conn):
        # Create legacy receipts table
        ensure_schema(fresh_conn)
        insert_receipt(
            fresh_conn,
            {
                "vendor": "Coffee Shop",
                "date": "2024-01-01",
                "total": 3.00,
                "norm_hash": "hash1",
            },
        )
        insert_receipt(
            fresh_conn,
            {
                "vendor": "Coffee Shop 2",
                "date": "2024-01-02",
                "total": 4.00,
                "norm_hash": "hash2",  # Different hash
            },
        )

        # Create documents table and insert one to create conflict
        fresh_conn.execute(CREATE_DOCUMENTS)
        fresh_conn.commit()

        # Pre-insert one document with same hash to cause skip
        fresh_conn.execute(
            """
            INSERT INTO documents (doc_id, doc_type, vendor, norm_hash)
            VALUES ('existing', 'receipt', 'Pre-existing', 'hash1')
        """
        )
        fresh_conn.commit()

        stats = migrate_receipts_to_documents(fresh_conn)

        # First skipped (hash conflict), second migrates
        assert stats["migrated"] == 1
        assert stats["skipped"] == 1


class TestEnsureCurrentSchema:
    """Tests for ensure_current_schema entry point."""

    def test_fresh_db_gets_initialized(self, fresh_conn):
        result = ensure_current_schema(fresh_conn)

        assert result["status"] == "initialized"
        assert get_schema_version(fresh_conn) == SCHEMA_VERSION

    def test_current_db_stays_current(self, fresh_conn):
        initialize_fresh_db(fresh_conn)

        result = ensure_current_schema(fresh_conn)

        assert result["status"] == "current"
        assert result["version"] == SCHEMA_VERSION

    def test_legacy_db_gets_migrated(self, fresh_conn):
        # Create legacy schema
        ensure_schema(fresh_conn)
        insert_receipt(
            fresh_conn,
            {
                "vendor": "Test",
                "date": "2024-01-01",
                "total": 10.00,
                "norm_hash": "testhash",
            },
        )

        result = ensure_current_schema(fresh_conn)

        assert result["status"] == "migrated"
        assert table_exists(fresh_conn, "documents")
        assert get_schema_version(fresh_conn) == SCHEMA_VERSION


class TestIntegrityCheck:
    """Tests for database integrity checking."""

    def test_fresh_db_integrity_ok(self, fresh_conn):
        initialize_fresh_db(fresh_conn)

        result = check_integrity(fresh_conn)

        assert result["status"] == "ok"
        assert result["integrity_check"] == "ok"
        assert "documents" in result["tables"]

    def test_missing_table_warning(self, fresh_conn):
        # Create partial schema
        fresh_conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        fresh_conn.execute(CREATE_DOCUMENTS)
        fresh_conn.commit()
        set_schema_version(fresh_conn, SCHEMA_VERSION)

        result = check_integrity(fresh_conn)

        assert result["status"] == "warning"
        assert any("Missing table" in issue for issue in result["issues"])


class TestSQLiteStore:
    """Tests for SQLiteStore class."""

    def test_insert_and_get_document(self, store):
        doc_id = store.insert_document(
            vendor="Test Store",
            date="2024-01-15",
            total=25.00,
            subtotal=23.00,
            tax=2.00,
            raw_text="Test receipt",
            norm_hash="unique_hash_123",
        )

        assert doc_id > 0

        # Get by numeric ID
        doc = store.get_document_by_id(doc_id)
        assert doc["vendor"] == "Test Store"
        assert doc["vendor_norm"] == "teststore"
        assert doc["total"] == 25.00

    def test_document_exists(self, store):
        store.insert_document(
            vendor="Exists",
            norm_hash="exists_hash",
        )

        assert store.document_exists("exists_hash")
        assert not store.document_exists("not_exists")

    def test_insert_line_items(self, store):
        doc_id = store.insert_document(vendor="Test", norm_hash="h1")

        items = [
            {"description": "Coffee", "quantity": 1, "amount": 3.50},
            {"description": "Muffin", "quantity": 2, "amount": 5.00},
        ]
        item_ids = store.insert_line_items_batch(doc_id, items)

        assert len(item_ids) == 2

        retrieved = store.get_line_items(doc_id)
        assert len(retrieved) == 2
        assert retrieved[0]["description"] == "Coffee"
        assert retrieved[1]["description"] == "Muffin"

    def test_insert_transaction(self, store):
        doc_id = store.insert_document(
            vendor="Starbucks",
            date="2024-01-15",
            total=5.50,
            norm_hash="txn_hash",
        )

        txn_id = store.insert_transaction(
            document_id=doc_id,
            amount=5.50,
            date="2024-01-15",
            merchant_norm="starbucks",
            primary_category="Food & Drink",
            secondary_category="Coffee",
            confidence=0.95,
            tags=["coffee", "beverage"],
            rule_name="coffee_rule",
        )

        assert txn_id > 0

        txn = store.get_transaction(txn_id)
        assert txn["primary_category"] == "Food & Drink"
        assert txn["confidence"] == 0.95
        assert txn["tags"] == ["coffee", "beverage"]

    def test_upsert_merchant(self, store):
        # Insert
        store.upsert_merchant(
            merchant_key="starbucks",
            display_name="Starbucks Coffee",
            default_category="Coffee",
        )

        merchant = store.get_merchant("starbucks")
        assert merchant["display_name"] == "Starbucks Coffee"

        # Update
        store.upsert_merchant(
            merchant_key="starbucks",
            aliases=["sbux", "starbucks coffee"],
        )

        merchant = store.get_merchant("starbucks")
        assert merchant["display_name"] == "Starbucks Coffee"  # Preserved
        assert "sbux" in merchant["aliases"]

    def test_list_documents_with_filters(self, store):
        store.insert_document(vendor="A", date="2024-01-01", total=10, norm_hash="h1")
        store.insert_document(vendor="B", date="2024-02-01", total=20, norm_hash="h2")
        store.insert_document(vendor="C", date="2024-03-01", total=30, norm_hash="h3")

        # Filter by date range
        docs = store.list_documents(date_from="2024-02-01", date_to="2024-02-28")
        assert len(docs) == 1
        assert docs[0]["vendor"] == "B"

    def test_spending_by_category(self, store):
        # Create documents and transactions
        doc1 = store.insert_document(
            vendor="A", date="2024-01-01", total=10, norm_hash="s1"
        )
        doc2 = store.insert_document(
            vendor="B", date="2024-01-02", total=20, norm_hash="s2"
        )
        doc3 = store.insert_document(
            vendor="C", date="2024-01-03", total=15, norm_hash="s3"
        )

        store.insert_transaction(doc1, 10, "2024-01-01", primary_category="Food")
        store.insert_transaction(doc2, 20, "2024-01-02", primary_category="Food")
        store.insert_transaction(doc3, 15, "2024-01-03", primary_category="Transport")

        spending = store.spending_by_category()

        food = next(s for s in spending if s["category"] == "Food")
        transport = next(s for s in spending if s["category"] == "Transport")

        assert food["total"] == 30
        assert food["count"] == 2
        assert transport["total"] == 15

    def test_get_stats(self, store):
        store.insert_document(vendor="Test", norm_hash="st1")
        store.insert_document(vendor="Test2", norm_hash="st2")

        stats = store.get_stats()

        assert stats["documents"] == 2
        assert stats["line_items"] == 0
        assert stats["transactions"] == 0


class TestViewQueries:
    """Tests for compatibility views."""

    def test_documents_v_query(self, store):
        store.insert_document(
            vendor="View Test",
            date="2024-01-01",
            total=100,
            norm_hash="view_hash",
        )

        cur = store.conn.cursor()
        cur.execute("SELECT * FROM documents_v")
        row = cur.fetchone()

        assert row["vendor"] == "View Test"
        assert row["document_id"] == row["id"]  # Alias works

    def test_line_items_v_joins_document(self, store):
        doc_id = store.insert_document(
            vendor="Line View",
            date="2024-01-01",
            norm_hash="lv_hash",
        )
        store.insert_line_item(doc_id, description="Item 1", amount=10)

        cur = store.conn.cursor()
        cur.execute("SELECT * FROM line_items_v")
        row = cur.fetchone()

        assert row["description"] == "Item 1"
        assert row["vendor"] == "Line View"

    def test_transactions_v_joins_merchant(self, store):
        doc_id = store.insert_document(
            vendor="Txn View",
            date="2024-01-01",
            norm_hash="tv_hash",
        )
        store.upsert_merchant("txnview", "Txn View Display")
        store.insert_transaction(
            doc_id,
            50,
            "2024-01-01",
            merchant_norm="txnview",
            primary_category="Test",
        )

        cur = store.conn.cursor()
        cur.execute("SELECT * FROM transactions_v")
        row = cur.fetchone()

        assert row["merchant_display"] == "Txn View Display"
        assert row["primary_category"] == "Test"
