# Smart Finance Advisor - Implementation Plan

## Status: ALL PHASES COMPLETE

**Completed:**
- [x] Phase 1: Database Schema Expansion
- [x] Phase 2: Storage Layer Updates
- [x] Phase 3: CLI Subcommands
- [x] Phase 4: Pipeline Integration (OCR wired, ingest uses new schema)
- [x] Phase 5: Enhanced Categorization (priority rules, amount/date conditions, tag accumulation)
- [x] Phase 6: Dashboard Enhancement (multi-page Streamlit with charts and filters)
- [x] Phase 7: Quality & Polish (demo.py script, comprehensive README)

## Overview

This plan transforms the current working prototype into the complete system described in the project spec. The foundation is solid (OCR, parsing, categorization, tests all working), so we're building on proven components.

---

## Phase 1: Database Schema Expansion (Foundation)
**Priority: CRITICAL - Everything else depends on this**

### 1.1 Create Full Schema

Current state: Single `receipts` table
Target state: Normalized schema with proper relationships

```sql
-- Core document storage (replaces receipts)
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT UNIQUE NOT NULL,        -- UUID or hash-based ID
    doc_type TEXT NOT NULL,             -- 'invoice', 'paystub', 'receipt'
    source_file TEXT,                   -- original filename
    vendor TEXT,
    vendor_norm TEXT,                   -- normalized merchant key
    date TEXT,                          -- ISO YYYY-MM-DD
    total REAL,
    subtotal REAL,
    tax REAL,
    tip REAL,
    currency TEXT DEFAULT 'USD',
    raw_text TEXT,
    norm_hash TEXT UNIQUE,              -- dedup fingerprint
    extraction_confidence REAL,
    reconciled_used INTEGER DEFAULT 0,
    items_subtotal_diff REAL,
    items_subtotal_pct REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Line items extracted from documents
CREATE TABLE line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    line_number INTEGER,                -- order in document
    description TEXT,
    quantity REAL,
    unit_price REAL,
    amount REAL,
    weight_qty REAL,                    -- for weighted items (lb/kg)
    weight_unit TEXT,
    raw_line TEXT,                      -- original text
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Categorized transactions (one per document or line item)
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    line_item_id INTEGER REFERENCES line_items(id) ON DELETE CASCADE,
    merchant_norm TEXT,
    amount REAL NOT NULL,
    date TEXT,
    primary_category TEXT,
    secondary_category TEXT,
    confidence REAL,
    tags TEXT,                          -- JSON array
    rule_name TEXT,                     -- which rule matched
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Normalized merchant registry
CREATE TABLE merchants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_key TEXT UNIQUE NOT NULL,  -- lowercase alphanumeric
    display_name TEXT,                  -- preferred display name
    aliases TEXT,                       -- JSON array of known variations
    default_category TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Category definitions
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    parent_category TEXT,               -- for hierarchy
    description TEXT,
    icon TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_documents_date ON documents(date);
CREATE INDEX idx_documents_vendor_norm ON documents(vendor_norm);
CREATE INDEX idx_line_items_document_id ON line_items(document_id);
CREATE INDEX idx_transactions_document_id ON transactions(document_id);
CREATE INDEX idx_transactions_date ON transactions(date);
CREATE INDEX idx_transactions_category ON transactions(primary_category);
CREATE INDEX idx_merchants_key ON merchants(merchant_key);
```

### 1.2 Create Compat Views

For stable querying regardless of column naming:

```sql
-- Document compatibility view
CREATE VIEW documents_v AS
SELECT
    id,
    doc_id,
    id as document_id,          -- alias for joins
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

-- Line items compatibility view
CREATE VIEW line_items_v AS
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
    d.date,
    li.created_at
FROM line_items li
JOIN documents d ON li.document_id = d.id;

-- Transactions compatibility view
CREATE VIEW transactions_v AS
SELECT
    t.id,
    t.document_id,
    d.doc_id,
    t.line_item_id,
    t.merchant_norm,
    COALESCE(m.display_name, t.merchant_norm) as merchant_display,
    t.amount,
    t.date,
    t.primary_category,
    t.secondary_category,
    t.confidence,
    t.tags,
    t.rule_name,
    d.vendor,
    d.doc_type,
    t.created_at,
    t.updated_at
FROM transactions t
JOIN documents d ON t.document_id = d.id
LEFT JOIN merchants m ON t.merchant_norm = m.merchant_key;
```

### 1.3 Migration Script

Create `storage/migrations.py`:
- Detect current schema version
- Migrate `receipts` → `documents` if exists
- Create missing tables
- Create/refresh views
- Backfill `vendor_norm` from existing vendors

### Tasks:
- [ ] Create `storage/schema.py` with table definitions
- [ ] Create `storage/migrations.py` with version detection and migration logic
- [ ] Update `storage/sqlite_store.py` to use new schema
- [ ] Add migration tests
- [ ] Migrate existing test databases

---

## Phase 2: Storage Layer Updates
**Priority: HIGH - Enables all downstream features**

### 2.1 Update SQLite Store

Modify `storage/sqlite_store.py`:

```python
class SQLiteStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    # Document operations
    def insert_document(self, doc: Document) -> int: ...
    def get_document(self, doc_id: str) -> Document: ...
    def update_document(self, doc_id: str, **fields) -> bool: ...

    # Line item operations
    def insert_line_items(self, document_id: int, items: list[LineItem]) -> list[int]: ...
    def get_line_items(self, document_id: int) -> list[LineItem]: ...

    # Transaction operations
    def insert_transaction(self, txn: Transaction) -> int: ...
    def update_transaction_category(self, txn_id: int, category_info: dict) -> bool: ...
    def get_transactions(self, filters: dict = None) -> list[Transaction]: ...

    # Merchant operations
    def upsert_merchant(self, key: str, display_name: str, aliases: list = None): ...
    def normalize_merchant(self, raw_vendor: str) -> str: ...
    def get_merchant(self, key: str) -> dict: ...

    # Bulk operations
    def refresh_all_categories(self) -> dict: ...  # re-run categorizer on all docs
    def normalize_all_merchants(self) -> dict: ...  # backfill vendor_norm

    # Health checks
    def check_integrity(self) -> dict: ...
    def get_table_stats(self) -> dict: ...
    def find_empties(self) -> dict: ...
```

### 2.2 Merchant Normalization

Create `sfa_utils/merchant_normalizer.py`:

```python
def normalize_merchant_key(raw: str) -> str:
    """
    "McDonald's" -> "mcdonalds"
    "MCDONALDS #1234" -> "mcdonalds"
    "Wal-Mart Supercenter" -> "walmart"
    """
    # Lowercase
    # Remove punctuation
    # Remove store numbers (#1234, Store 567)
    # Remove common suffixes (Inc, LLC, Corp)
    # Collapse whitespace
    return normalized_key
```

### Tasks:
- [ ] Refactor `sqlite_store.py` for new schema
- [ ] Add document CRUD operations
- [ ] Add line_items CRUD operations
- [ ] Add transaction CRUD operations
- [ ] Add merchant normalization
- [ ] Add bulk operations (refresh categories, normalize merchants)
- [ ] Add health check methods
- [ ] Update tests for new storage layer

---

## Phase 3: CLI Subcommands
**Priority: HIGH - User-facing interface**

### 3.1 Expand CLI with New Subcommands

Update `cli/finproc.py` or create new CLI entry point:

```bash
# Existing (keep working)
finproc ingest <file>           # OCR/parse single file
finproc ingest-batch <dir>      # Batch process directory

# New subcommands
finproc categorize              # Apply rules to all uncategorized
finproc categorize --refresh    # Re-run on all documents

# SQLite management
finproc --sqlite-init           # Initialize fresh database with full schema
finproc --sqlite-check          # Validate integrity, report stats
finproc --sqlite-seed           # Load sample/test data
finproc --sqlite-compat-views   # Create/refresh compatibility views
finproc --sqlite-merchant-normalize  # Backfill vendor_norm column

# Output formats
finproc ingest <file> --format json    # JSON output
finproc ingest <file> --format jsonl   # JSONL streaming
finproc ingest <file> --format csv     # CSV output (new)
```

### 3.2 Exit Codes

```
0 = Success
1 = General error
2 = Warning (e.g., some files skipped)
3 = Database error
4 = Parse error
5 = Validation error
```

### 3.3 Output Formats

For `--sqlite-check`:
```json
{
  "status": "ok",
  "tables": {
    "documents": {"rows": 150, "empty": false},
    "line_items": {"rows": 892, "empty": false},
    "transactions": {"rows": 150, "empty": false},
    "merchants": {"rows": 45, "empty": false}
  },
  "integrity": "ok",
  "schema_version": 2,
  "issues": []
}
```

### Tasks:
- [ ] Add `categorize` subcommand
- [ ] Add `--sqlite-init` flag
- [ ] Add `--sqlite-check` flag with JSON/human output
- [ ] Add `--sqlite-seed` flag
- [ ] Add `--sqlite-compat-views` flag
- [ ] Add `--sqlite-merchant-normalize` flag
- [ ] Implement CSV export
- [ ] Add exit code handling
- [ ] Add CLI tests for new commands

---

## Phase 4: Fix Pipeline Integration
**Priority: MEDIUM - Cleanup tech debt**

### 4.1 Fix Broken Import

`pipeline/runner.py` imports `extract_file` which doesn't exist.

Options:
1. **Create `extract_file()` function** in `parser/extractor.py`
2. **Update pipeline to use existing functions** (`extract_from_text()`)
3. **Deprecate pipeline/runner.py** and standardize on `sfa_cli/process.py`

Recommendation: Option 2 - minimal change, keeps existing code.

### 4.2 Wire Real OCR in finproc.py

Current stub returns `(bytes=12345)` for non-.txt files.

Fix:
```python
# In finproc.py
from ocr.reader import read_image, read_pdf

def read_file_content(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == '.txt':
        return path.read_text(encoding='utf-8')
    elif suffix == '.pdf':
        return read_pdf(str(path))
    elif suffix in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff'):
        return read_image(str(path))
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
```

### Tasks:
- [ ] Fix `pipeline/runner.py` import error
- [ ] Wire real OCR into `finproc.py`
- [ ] Test image/PDF ingestion end-to-end
- [ ] Update batch processing for all file types

---

## Phase 5: Enhanced Categorization
**Priority: MEDIUM - Better accuracy**

### 5.1 Rules Engine v2

Enhance `categorizer/rules.py`:

```yaml
rules:
  # Priority ordering (first match wins)
  - name: "Starbucks"
    priority: 100
    if_vendor_matches: ["starbucks", "sbux"]
    assign:
      primary_category: "Food & Drink"
      secondary_category: "Coffee"
      confidence: 0.95
      tags: ["coffee", "beverage"]

  - name: "Gas stations"
    priority: 90
    if_vendor_matches: ["shell", "chevron", "exxon", "mobil", "bp"]
    if_amount_between: [20, 150]  # typical gas purchase
    assign:
      primary_category: "Transportation"
      secondary_category: "Gas"
      confidence: 0.90

  - name: "Grocery by items"
    priority: 50
    if_lineitem_contains: ["milk", "bread", "eggs", "produce"]
    assign:
      primary_category: "Groceries"
      confidence: 0.75

  - name: "Large purchases"
    priority: 10
    if_amount_gt: 500
    assign:
      tags: ["large-purchase", "review"]

defaults:
  primary_category: "Uncategorized"
  secondary_category: null
  confidence: 0.1
  tags: []
```

### 5.2 Categorizer Service Updates

```python
class CategorizerService:
    def categorize(self, doc: Document) -> Transaction:
        # 1. Load rules (cached)
        # 2. Sort by priority
        # 3. Evaluate conditions
        # 4. Return first match or defaults
        # 5. Store result in transactions table

    def recategorize_all(self) -> dict:
        # Re-run all documents through rules
        # Return stats: {updated: N, unchanged: M, errors: []}
```

### Tasks:
- [ ] Add priority ordering to rules
- [ ] Add amount conditions (`if_amount_between`, `if_amount_gt`)
- [ ] Add date conditions (`if_date_between`, `if_weekday`)
- [ ] Persist categorization results to transactions table
- [ ] Add `recategorize_all()` method
- [ ] Update rules.yaml with comprehensive patterns

---

## Phase 6: Dashboard Enhancement
**Priority: MEDIUM - User visibility**

### 6.1 Streamlit Dashboard Features

Update `ui/app.py`:

```python
# Pages
1. Overview Dashboard
   - Total spend this month/year
   - Spend by category (pie chart)
   - Spend over time (line chart)
   - Top merchants (bar chart)

2. Documents Browser
   - Filterable table (date range, vendor, category)
   - Click to expand details + line items
   - Sanity check badges

3. Categories View
   - Category breakdown with drill-down
   - Uncategorized items list
   - Quick categorize buttons

4. Merchants View
   - Merchant spending summary
   - Alias management
   - Category assignment

5. Line Items Search
   - Full-text search across all items
   - Filter by category/merchant/date
```

### 6.2 Queries for Dashboard

```sql
-- Spend by category this month
SELECT primary_category, SUM(amount) as total
FROM transactions_v
WHERE date >= date('now', 'start of month')
GROUP BY primary_category
ORDER BY total DESC;

-- Spend over time (daily)
SELECT date, SUM(amount) as daily_total
FROM transactions_v
WHERE date >= date('now', '-30 days')
GROUP BY date
ORDER BY date;

-- Top merchants
SELECT merchant_display, COUNT(*) as txn_count, SUM(amount) as total
FROM transactions_v
GROUP BY merchant_norm
ORDER BY total DESC
LIMIT 10;
```

### Tasks:
- [ ] Add overview dashboard with charts
- [ ] Add date range filter
- [ ] Add vendor/category filters
- [ ] Add line items search page
- [ ] Add category breakdown view
- [ ] Add merchant management page
- [ ] Add export functionality

---

## Phase 7: Quality & Polish
**Priority: LOW - Nice to have**

### 7.1 Additional Tests

- [ ] Integration tests for full pipeline (file → DB → query)
- [ ] CLI integration tests with real DB
- [ ] Migration tests (schema v1 → v2)
- [ ] Dashboard component tests

### 7.2 Documentation

- [ ] Update README with full usage examples
- [ ] Add CONTRIBUTING.md
- [ ] Document rules file format
- [ ] Add troubleshooting guide

### 7.3 Sample Data

- [ ] Create diverse sample set (10-20 receipts)
- [ ] Include edge cases (weighted items, multi-page, poor OCR)
- [ ] Add paystub samples
- [ ] Create "one-command demo" script

---

## Implementation Order

```
Week 1: Foundation
├── Phase 1.1: Schema definitions
├── Phase 1.2: Compat views
├── Phase 1.3: Migration script
└── Phase 2: Storage layer updates

Week 2: CLI & Pipeline
├── Phase 3: CLI subcommands
├── Phase 4.1: Fix pipeline import
└── Phase 4.2: Wire real OCR

Week 3: Features
├── Phase 5: Enhanced categorization
└── Phase 6.1-6.2: Basic dashboard

Week 4: Polish
├── Phase 6 (complete): Full dashboard
├── Phase 7: Tests & docs
└── Final testing & cleanup
```

---

## Success Criteria

The project is "done" when:

1. **CLI works end-to-end:**
   ```bash
   finproc ingest-batch ./receipts --db finance.db
   finproc categorize --db finance.db
   finproc --sqlite-check --db finance.db  # returns 0
   ```

2. **Database is complete:**
   - All 5 tables populated (documents, line_items, transactions, merchants, categories)
   - Compat views queryable
   - Integrity check passes

3. **Dashboard shows:**
   - Spend by category/time/merchant
   - Drill-through to documents
   - Filter by date/vendor/category

4. **Tests pass:**
   - All existing tests (27+)
   - New tests for CLI commands
   - Migration tests

5. **Sample demo works:**
   ```bash
   ./demo.sh  # drops sample receipts, ingests, categorizes, opens dashboard
   ```

---

## Notes

- Keep backward compatibility with existing `receipts` table during migration
- All new features should have tests before implementation
- Prefer small, incremental PRs over large changes
- Run full test suite after each phase completion
