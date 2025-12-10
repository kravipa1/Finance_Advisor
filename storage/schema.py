# storage/schema.py
"""
Database schema definitions for Smart Finance Advisor.

Schema version history:
  v1: Original receipts table
  v2: Added sanity flags (reconciled_used, items_subtotal_diff, items_subtotal_pct)
  v3: Added norm_hash for deduplication
  v4: Full schema with documents, line_items, transactions, merchants, categories
"""
from __future__ import annotations

SCHEMA_VERSION = 4

# =============================================================================
# Core Tables
# =============================================================================

CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT UNIQUE NOT NULL,
    doc_type TEXT NOT NULL DEFAULT 'receipt',
    source_file TEXT,
    vendor TEXT,
    vendor_norm TEXT,
    date TEXT,
    total REAL,
    subtotal REAL,
    tax REAL,
    tip REAL,
    currency TEXT DEFAULT 'USD',
    raw_text TEXT,
    norm_hash TEXT UNIQUE,
    extraction_confidence REAL,
    reconciled_used INTEGER DEFAULT 0,
    items_subtotal_diff REAL DEFAULT 0.0,
    items_subtotal_pct REAL DEFAULT 0.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_LINE_ITEMS = """
CREATE TABLE IF NOT EXISTS line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    line_number INTEGER,
    description TEXT,
    quantity REAL,
    unit_price REAL,
    amount REAL,
    weight_qty REAL,
    weight_unit TEXT,
    raw_line TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);
"""

CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    line_item_id INTEGER,
    merchant_norm TEXT,
    amount REAL NOT NULL,
    date TEXT,
    primary_category TEXT,
    secondary_category TEXT,
    confidence REAL,
    tags TEXT,
    rule_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (line_item_id) REFERENCES line_items(id) ON DELETE CASCADE
);
"""

CREATE_MERCHANTS = """
CREATE TABLE IF NOT EXISTS merchants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_key TEXT UNIQUE NOT NULL,
    display_name TEXT,
    aliases TEXT,
    default_category TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CATEGORIES = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    parent_category TEXT,
    description TEXT,
    icon TEXT,
    color TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Schema version tracking
CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Legacy receipts table (for migration reference)
CREATE_RECEIPTS_LEGACY = """
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

# =============================================================================
# Indexes
# =============================================================================

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(date);",
    "CREATE INDEX IF NOT EXISTS idx_documents_vendor_norm ON documents(vendor_norm);",
    "CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents(doc_type);",
    "CREATE INDEX IF NOT EXISTS idx_documents_norm_hash ON documents(norm_hash);",
    "CREATE INDEX IF NOT EXISTS idx_line_items_document_id ON line_items(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_document_id ON transactions(document_id);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(primary_category);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant_norm);",
    "CREATE INDEX IF NOT EXISTS idx_merchants_key ON merchants(merchant_key);",
]

# =============================================================================
# Compatibility Views
# =============================================================================

CREATE_DOCUMENTS_VIEW = """
CREATE VIEW IF NOT EXISTS documents_v AS
SELECT
    id,
    doc_id,
    id as document_id,
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
    created_at,
    updated_at
FROM documents;
"""

CREATE_LINE_ITEMS_VIEW = """
CREATE VIEW IF NOT EXISTS line_items_v AS
SELECT
    li.id,
    li.document_id,
    d.doc_id,
    li.line_number,
    li.description,
    li.quantity,
    li.unit_price,
    li.amount,
    li.weight_qty,
    li.weight_unit,
    li.raw_line,
    d.vendor,
    d.vendor_norm,
    d.date,
    li.created_at
FROM line_items li
JOIN documents d ON li.document_id = d.id;
"""

CREATE_TRANSACTIONS_VIEW = """
CREATE VIEW IF NOT EXISTS transactions_v AS
SELECT
    t.id,
    t.document_id,
    d.doc_id,
    t.line_item_id,
    t.merchant_norm,
    COALESCE(m.display_name, d.vendor, t.merchant_norm) as merchant_display,
    t.amount,
    t.date,
    t.primary_category,
    t.secondary_category,
    t.confidence,
    t.tags,
    t.rule_name,
    d.vendor,
    d.doc_type,
    d.source_file,
    t.created_at,
    t.updated_at
FROM transactions t
JOIN documents d ON t.document_id = d.id
LEFT JOIN merchants m ON t.merchant_norm = m.merchant_key;
"""

# For backward compatibility - map receipts queries to documents
CREATE_RECEIPTS_VIEW = """
CREATE VIEW IF NOT EXISTS receipts_v AS
SELECT
    id,
    vendor,
    date,
    total,
    subtotal,
    tax,
    tip,
    reconciled_used,
    items_subtotal_diff,
    items_subtotal_pct,
    norm_hash,
    raw_text
FROM documents;
"""

# =============================================================================
# Default Categories
# =============================================================================

DEFAULT_CATEGORIES = [
    ("Food & Drink", None, "Restaurants, cafes, bars", "🍔", "#FF6B6B"),
    ("Groceries", None, "Supermarkets, grocery stores", "🛒", "#4ECDC4"),
    ("Transportation", None, "Gas, rideshare, public transit", "🚗", "#45B7D1"),
    ("Shopping", None, "Retail, online shopping", "🛍️", "#96CEB4"),
    ("Entertainment", None, "Movies, games, streaming", "🎬", "#DDA0DD"),
    ("Bills & Utilities", None, "Electric, water, internet", "💡", "#FFE66D"),
    ("Healthcare", None, "Medical, pharmacy, dental", "🏥", "#98D8C8"),
    ("Travel", None, "Hotels, flights, vacation", "✈️", "#F7DC6F"),
    ("Income", None, "Salary, wages, payments received", "💰", "#82E0AA"),
    ("Uncategorized", None, "Not yet categorized", "❓", "#BDC3C7"),
    # Subcategories
    ("Coffee", "Food & Drink", "Coffee shops", "☕", "#D4A574"),
    ("Fast Food", "Food & Drink", "Quick service restaurants", "🍟", "#F39C12"),
    ("Gas", "Transportation", "Fuel purchases", "⛽", "#3498DB"),
    ("Rideshare", "Transportation", "Uber, Lyft, etc.", "🚕", "#9B59B6"),
    ("Pharmacy", "Healthcare", "Prescriptions, OTC medicine", "💊", "#1ABC9C"),
]

# =============================================================================
# All DDL statements in order
# =============================================================================

ALL_TABLES = [
    CREATE_SCHEMA_VERSION,
    CREATE_DOCUMENTS,
    CREATE_LINE_ITEMS,
    CREATE_TRANSACTIONS,
    CREATE_MERCHANTS,
    CREATE_CATEGORIES,
]

ALL_VIEWS = [
    CREATE_DOCUMENTS_VIEW,
    CREATE_LINE_ITEMS_VIEW,
    CREATE_TRANSACTIONS_VIEW,
    CREATE_RECEIPTS_VIEW,
]
