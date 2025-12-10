# Smart Finance Advisor

A local, privacy-first personal finance tool that:
- Ingests receipts, invoices, and paystubs (images, PDFs, text files)
- Extracts data using OCR (EasyOCR) and smart parsing
- Categorizes transactions using configurable rule-based matching
- Stores everything in a local SQLite database
- Provides a Streamlit dashboard for visualization

## Quick Start

```bash
# Run the demo (ingests samples, categorizes, shows stats)
python demo.py --reset

# Or step by step:
python -m finproc db --init                           # Initialize database
python -m finproc ingest-batch data/samples/invoices  # Ingest sample files
python -m finproc categorize --rules config/rules.yaml  # Categorize
python -m finproc db --stats                          # Show statistics

# Launch the dashboard
streamlit run ui/app.py
```

## Setup

```bash
git clone <repo-url>
cd smart-finance-advisor
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

## CLI Commands

### Ingest Files

```bash
# Single file
python -m finproc ingest path/to/receipt.txt
python -m finproc ingest path/to/receipt.png

# Batch (entire directory)
python -m finproc ingest-batch path/to/receipts/

# With options
python -m finproc ingest-batch path/to/receipts/ --ext .pdf,.png,.txt --recurse

# Watch mode (auto-ingest new files)
python -m finproc ingest-batch path/to/inbox/ --watch --interval 5
```

### Database Management

```bash
# Initialize database with full schema
python -m finproc db --init

# Check database health
python -m finproc db --check

# Show table statistics
python -m finproc db --stats

# Normalize merchant names (backfill vendor_norm)
python -m finproc db --merchant-normalize

# Refresh compatibility views
python -m finproc db --compat-views

# Use custom database path
python -m finproc db --init --db path/to/custom.sqlite
```

### Categorize Transactions

```bash
# Categorize uncategorized documents
python -m finproc categorize

# Re-categorize all documents
python -m finproc categorize --refresh

# Use custom rules file
python -m finproc categorize --rules config/my_rules.yaml

# Dry run (show what would happen)
python -m finproc categorize --dry-run

# JSON output
python -m finproc categorize --json
```

## Database Schema

The database uses a normalized schema with these tables:

- **documents**: Source documents (receipts, invoices, paystubs)
- **line_items**: Individual items extracted from documents
- **transactions**: Categorized spending records
- **merchants**: Normalized merchant registry
- **categories**: Category definitions

Compatibility views provide stable querying:
- `documents_v`, `line_items_v`, `transactions_v`, `receipts_v`

## Rules Configuration

Rules are defined in YAML (`config/rules.yaml`):

```yaml
rules:
  - name: "Starbucks"
    priority: 100
    if_vendor_matches: ["STARBUCKS", "SBUX"]
    assign:
      primary_category: "Food & Drink"
      secondary_category: "Coffee"
      confidence: 0.95
      tags: ["coffee", "beverage"]

  - name: "Gas stations"
    priority: 85
    if_vendor_matches: ["SHELL", "CHEVRON", "EXXON"]
    if_amount_between: [20, 150]
    assign:
      primary_category: "Transportation"
      secondary_category: "Gas"
      confidence: 0.90

  - name: "Groceries by keywords"
    priority: 50
    if_lineitem_contains: ["milk", "bread", "eggs"]
    assign:
      primary_category: "Groceries"
      confidence: 0.75

defaults:
  primary_category: "Uncategorized"
  confidence: 0.10
```

### Rule Conditions

- `if_vendor_matches`: List of vendor name patterns (case-insensitive)
- `if_lineitem_contains`: Keywords to match in line items or raw text
- `if_amount_gt`: Amount greater than threshold
- `if_amount_lt`: Amount less than threshold
- `if_amount_between`: Amount within range [min, max]
- `if_weekday`: Day of week (0=Monday, 6=Sunday)
- `if_date_from`, `if_date_to`: Date range filters

Higher priority rules are evaluated first. First matching rule wins.

## Dashboard

The Streamlit dashboard provides:

- **Overview**: Spending charts by category, merchant, and time
- **Documents**: Browse ingested documents with filters
- **Transactions**: View categorized transactions
- **Categories**: Spending breakdown by category
- **Merchants**: Top merchants by spending
- **Database**: Health checks and statistics

```bash
streamlit run ui/app.py
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_rules_enhanced.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html
```

## Project Structure

```
smart-finance-advisor/
├── categorizer/        # Rule-based categorization
│   ├── rules.py        # Rules engine
│   └── service.py      # Categorizer service
├── config/
│   └── rules.yaml      # Categorization rules
├── data/
│   └── samples/        # Sample receipts/invoices
├── ocr/
│   └── reader.py       # EasyOCR integration
├── parser/
│   └── extractor.py    # Receipt parsing
├── storage/
│   ├── schema.py       # Database schema
│   ├── migrations.py   # Schema migrations
│   └── sqlite_store.py # CRUD operations
├── ui/
│   └── app.py          # Streamlit dashboard
├── tests/              # Test suite (75+ tests)
├── finproc.py          # CLI entry point
├── demo.py             # Demo script
└── requirements.txt
```

## Sample Usage

```bash
# Full pipeline demo
python demo.py --reset --dashboard

# Manual workflow
python -m finproc db --init
python -m finproc ingest receipt.png
python -m finproc categorize
python -m finproc db --stats
streamlit run ui/app.py
```
