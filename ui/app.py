# ui/app.py
"""
Smart Finance Advisor - Complete Dashboard Application

A polished end-product UI with:
- Drag-and-drop file upload
- Real-time OCR processing
- Interactive spending visualizations
- Document management
- Category insights
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any

import streamlit as st
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from storage.sqlite_store import SQLiteStore  # noqa: E402
from storage.migrations import normalize_merchant_key  # noqa: E402

# Page configuration
st.set_page_config(
    page_title="Smart Finance Advisor",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for polished look
st.markdown(
    """
<style>
    /* Main header styling */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        color: white;
    }
    .main-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
    }
    .main-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
    }

    /* Card styling */
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border: 1px solid #e5e7eb;
        text-align: center;
    }
    .metric-card .value {
        font-size: 2rem;
        font-weight: 700;
        color: #1f2937;
    }
    .metric-card .label {
        font-size: 0.875rem;
        color: #6b7280;
        margin-top: 0.25rem;
    }

    /* Upload area styling */
    .upload-area {
        border: 2px dashed #cbd5e1;
        border-radius: 12px;
        padding: 3rem 2rem;
        text-align: center;
        background: #f8fafc;
        transition: all 0.2s;
    }
    .upload-area:hover {
        border-color: #667eea;
        background: #f0f4ff;
    }

    /* Category chip */
    .category-chip {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 500;
        margin: 2px;
    }
    .category-food { background: #fef3c7; color: #92400e; }
    .category-transport { background: #dbeafe; color: #1e40af; }
    .category-groceries { background: #d1fae5; color: #065f46; }
    .category-shopping { background: #fce7f3; color: #9d174d; }
    .category-healthcare { background: #ede9fe; color: #5b21b6; }
    .category-default { background: #f3f4f6; color: #374151; }

    /* Success/info messages */
    .success-box {
        background: #d1fae5;
        border: 1px solid #10b981;
        border-radius: 8px;
        padding: 1rem;
        color: #065f46;
    }
    .info-box {
        background: #dbeafe;
        border: 1px solid #3b82f6;
        border-radius: 8px;
        padding: 1rem;
        color: #1e40af;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: #f8fafc;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Better table styling */
    .dataframe {
        font-size: 0.9rem !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Default database path
DB_PATH = os.environ.get("SFA_DB_PATH", "data/finance.sqlite")


# =============================================================================
# Helper Functions
# =============================================================================


def get_store() -> SQLiteStore:
    """Get or create SQLiteStore instance."""
    if "store" not in st.session_state:
        # Ensure data directory exists
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        st.session_state.store = SQLiteStore(DB_PATH)
        try:
            st.session_state.store.ensure_schema()
        except Exception:
            pass
    return st.session_state.store


def format_currency(value: float) -> str:
    """Format value as currency."""
    if value is None:
        return "$0.00"
    return f"${value:,.2f}"


def get_category_class(category: str) -> str:
    """Get CSS class for category chip."""
    if not category:
        return "category-default"
    cat_lower = category.lower()
    if "food" in cat_lower or "drink" in cat_lower:
        return "category-food"
    if "transport" in cat_lower:
        return "category-transport"
    if "grocer" in cat_lower:
        return "category-groceries"
    if "shop" in cat_lower:
        return "category-shopping"
    if "health" in cat_lower:
        return "category-healthcare"
    return "category-default"


def process_uploaded_file(uploaded_file) -> Dict[str, Any]:
    """Process an uploaded file through the pipeline."""
    from sfa_utils.fingerprint import normalized_text_fingerprint
    from parser.extractor import extract, parsed_doc_as_row

    # Save to temp file
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        # Read/OCR the file
        raw_text = read_file_content(tmp_path, suffix)

        # Normalize
        norm_text = normalize_text(raw_text)
        norm_hash = normalized_text_fingerprint(norm_text)

        # Parse
        parsed = extract(norm_text, source_path=uploaded_file.name)
        row = parsed_doc_as_row(parsed)

        return {
            "success": True,
            "raw_text": raw_text,
            "norm_hash": norm_hash,
            "parsed": row,
            "line_items": parsed.line_items if hasattr(parsed, "line_items") else [],
            "filename": uploaded_file.name,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "filename": uploaded_file.name,
        }
    finally:
        # Cleanup temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def read_file_content(path: str, suffix: str) -> str:
    """Read file content using OCR if needed."""
    if suffix == ".txt":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    # Try OCR for images
    if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".tiff"):
        try:
            from ocr.reader import read_image

            return read_image(path)
        except ImportError:
            pass
        except Exception:
            pass

    # Try OCR for PDFs
    if suffix == ".pdf":
        try:
            from ocr.reader import read_pdf

            return read_pdf(path)
        except ImportError:
            pass
        except Exception:
            pass

    # Fallback
    with open(path, "rb") as f:
        return f"(binary file, {len(f.read())} bytes)"


def normalize_text(text: str) -> str:
    """Normalize text while preserving line breaks."""
    lines = []
    for raw in (text or "").splitlines():
        s = " ".join(raw.strip().split()).lower()
        if s:
            lines.append(s)
    return "\n".join(lines)


def save_to_database(result: Dict[str, Any], store: SQLiteStore) -> int:
    """Save processed result to database."""
    from categorizer.service import CategorizerService
    from adapters.legacy import LegacyAdapter

    row = result["parsed"]

    # Check for duplicate
    if store.document_exists(result["norm_hash"]):
        return -1  # Duplicate

    # Insert document
    doc_id = store.insert_document(
        vendor=row.get("vendor"),
        date=row.get("date"),
        total=row.get("total"),
        subtotal=row.get("subtotal"),
        tax=row.get("tax"),
        tip=row.get("tip"),
        raw_text=result["raw_text"],
        norm_hash=result["norm_hash"],
        doc_type="receipt",
        source_file=result["filename"],
        reconciled_used=row.get("reconciled_used", 0),
        items_subtotal_diff=row.get("items_subtotal_diff", 0.0),
        items_subtotal_pct=row.get("items_subtotal_pct", 0.0),
    )

    # Insert line items
    if result.get("line_items"):
        store.insert_line_items_batch(doc_id, result["line_items"])

    # Categorize
    try:
        rules_path = PROJECT_ROOT / "config" / "rules.yaml"
        cat_svc = CategorizerService(
            rules_path=str(rules_path) if rules_path.exists() else None
        )

        adapter = LegacyAdapter()
        doc = adapter.build(
            source_path=result["filename"],
            ocr_text=result["raw_text"],
            parsed=None,
        )

        txn, rule_name = cat_svc.categorize_with_rule(doc)
        cat = txn.category

        if cat:
            store.insert_transaction(
                document_id=doc_id,
                amount=row.get("total") or 0,
                date=row.get("date"),
                merchant_norm=(
                    normalize_merchant_key(row.get("vendor"))
                    if row.get("vendor")
                    else None
                ),
                primary_category=cat.primary_category,
                secondary_category=cat.secondary_category,
                confidence=cat.confidence,
                tags=cat.tags,
                rule_name=rule_name,
            )
    except Exception as e:
        st.warning(f"Categorization failed: {e}")

    return doc_id


# =============================================================================
# Page: Upload & Process
# =============================================================================


def page_upload():
    """File upload and processing page."""
    st.markdown(
        """
    <div class="main-header">
        <h1>Upload Documents</h1>
        <p>Drop your receipts, invoices, or paystubs to extract and categorize spending</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # File uploader
    uploaded_files = st.file_uploader(
        "Upload receipts, invoices, or paystubs",
        type=["png", "jpg", "jpeg", "pdf", "txt"],
        accept_multiple_files=True,
        help="Supported formats: PNG, JPG, PDF, TXT",
    )

    if uploaded_files:
        store = get_store()

        # Process each file
        st.subheader(f"Processing {len(uploaded_files)} file(s)...")

        progress_bar = st.progress(0)
        results = []

        for i, file in enumerate(uploaded_files):
            with st.spinner(f"Processing {file.name}..."):
                result = process_uploaded_file(file)
                results.append(result)
            progress_bar.progress((i + 1) / len(uploaded_files))

        # Show results
        st.divider()

        saved_count = 0
        duplicate_count = 0
        error_count = 0

        for result in results:
            if not result["success"]:
                error_count += 1
                st.error(f"**{result['filename']}**: {result['error']}")
                continue

            # Save to database
            doc_id = save_to_database(result, store)

            if doc_id == -1:
                duplicate_count += 1
                st.warning(
                    f"**{result['filename']}**: Duplicate document (already exists)"
                )
                continue

            saved_count += 1

            # Show extraction result
            row = result["parsed"]
            with st.expander(
                f"**{result['filename']}** - {row.get('vendor', 'Unknown')} - {format_currency(row.get('total'))}",
                expanded=True,
            ):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total", format_currency(row.get("total")))
                col2.metric("Subtotal", format_currency(row.get("subtotal")))
                col3.metric("Tax", format_currency(row.get("tax")))
                col4.metric("Date", row.get("date") or "N/A")

                # Line items
                if result.get("line_items"):
                    st.write("**Line Items:**")
                    items_df = pd.DataFrame(result["line_items"])
                    if not items_df.empty:
                        display_cols = ["description", "quantity", "total"]
                        avail = [c for c in display_cols if c in items_df.columns]
                        if avail:
                            st.dataframe(
                                items_df[avail],
                                hide_index=True,
                                use_container_width=True,
                            )

                # Raw text preview
                with st.expander("Raw OCR Text"):
                    st.code(
                        result["raw_text"][:2000]
                        + ("..." if len(result["raw_text"]) > 2000 else "")
                    )

        # Summary
        st.divider()
        col1, col2, col3 = st.columns(3)
        col1.success(f"**{saved_count}** document(s) saved")
        if duplicate_count:
            col2.warning(f"**{duplicate_count}** duplicate(s) skipped")
        if error_count:
            col3.error(f"**{error_count}** error(s)")

        # Clear cache to refresh data
        if "store" in st.session_state:
            del st.session_state["store"]


# =============================================================================
# Page: Dashboard Overview
# =============================================================================


def page_dashboard():
    """Main dashboard with spending overview."""
    st.markdown(
        """
    <div class="main-header">
        <h1>Dashboard</h1>
        <p>Your spending at a glance</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    store = get_store()
    stats = store.get_stats()

    # Quick stats
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="value">{stats.get('documents', 0)}</div>
            <div class="label">Documents</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="value">{stats.get('transactions', 0)}</div>
            <div class="label">Transactions</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col3:
        # Calculate total spending
        spending = store.spending_by_category()
        total_spent = sum(s.get("total", 0) for s in spending) if spending else 0
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="value">{format_currency(total_spent)}</div>
            <div class="label">Total Spent</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col4:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="value">{stats.get('merchants', 0)}</div>
            <div class="label">Merchants</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    if stats.get("transactions", 0) == 0:
        st.info("No transactions yet. Upload some documents to get started!")
        return

    st.divider()

    # Charts
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Spending by Category")
        spending = store.spending_by_category()
        if spending:
            df = pd.DataFrame(spending)
            # Use a nicer chart
            st.bar_chart(
                df.set_index("category")["total"],
                use_container_width=True,
            )

            # Category breakdown table
            st.write("")
            for item in spending[:5]:
                cat = item["category"]
                item_total = item["total"]
                pct = (item_total / total_spent * 100) if total_spent else 0

                col_a, col_b, col_c = st.columns([3, 2, 1])
                col_a.write(f"**{cat}**")
                col_b.write(format_currency(item_total))
                col_c.write(f"{pct:.1f}%")

    with col2:
        st.subheader("Top Merchants")
        merchants = store.spending_by_merchant(limit=10)
        if merchants:
            df = pd.DataFrame(merchants)
            st.bar_chart(
                df.set_index("merchant_display")["total"],
                use_container_width=True,
            )

    st.divider()

    # Spending over time
    st.subheader("Spending Over Time")
    time_options = {"Daily": "day", "Weekly": "week", "Monthly": "month"}
    time_choice = st.radio("Group by", list(time_options.keys()), horizontal=True)

    time_data = store.spending_over_time(group_by=time_options[time_choice])
    if time_data:
        df = pd.DataFrame(time_data)
        st.line_chart(df.set_index("period")["total"], use_container_width=True)
    else:
        st.info("No time series data available yet.")

    # Recent transactions
    st.divider()
    st.subheader("Recent Transactions")

    txns = store.list_transactions(limit=10)
    if txns:
        for txn in txns:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            merchant = txn.get("merchant_norm") or "Unknown"
            date = txn.get("date") or "N/A"
            amount = txn.get("amount", 0)
            category = txn.get("primary_category") or "Uncategorized"

            col1.write(f"**{merchant}**")
            col2.write(date)
            col3.write(format_currency(amount))

            cat_class = get_category_class(category)
            col4.markdown(
                f'<span class="category-chip {cat_class}">{category}</span>',
                unsafe_allow_html=True,
            )


# =============================================================================
# Page: Documents
# =============================================================================


def page_documents():
    """Document browser page."""
    st.markdown(
        """
    <div class="main-header">
        <h1>Documents</h1>
        <p>Browse and manage your receipts, invoices, and paystubs</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    store = get_store()

    # Filters in sidebar
    with st.sidebar:
        st.subheader("Filters")

        limit = st.slider("Show", 10, 200, 50, 10)

        doc_types = ["All", "receipt", "invoice", "paystub"]
        doc_type = st.selectbox("Document Type", doc_types)
        doc_type_filter = None if doc_type == "All" else doc_type

        date_from = st.date_input("From Date", value=None)
        date_to = st.date_input("To Date", value=None)

    # Fetch documents
    docs = store.list_documents(
        limit=limit,
        doc_type=doc_type_filter,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )

    if not docs:
        st.info("No documents found. Upload some documents to get started!")
        return

    st.write(f"**{len(docs)}** documents found")

    # Document cards
    for doc in docs:
        with st.container(border=True):
            col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 2, 1])

            vendor = doc.get("vendor") or "Unknown Vendor"
            date = doc.get("date") or "N/A"
            total = doc.get("total") or 0
            doc_type = doc.get("doc_type") or "receipt"

            col1.write(f"**{vendor}**")
            col2.write(f"{date}")
            col3.write(format_currency(total))
            col4.write(doc_type.title())

            # Expand button
            with col5:
                show_details = st.checkbox("Details", key=f"doc_{doc.get('id')}")

            if show_details:
                st.divider()

                # Metrics row
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total", format_currency(doc.get("total")))
                m2.metric("Subtotal", format_currency(doc.get("subtotal")))
                m3.metric("Tax", format_currency(doc.get("tax")))
                m4.metric("Tip", format_currency(doc.get("tip")))

                # Line items
                items = store.get_line_items(doc.get("id"))
                if items:
                    st.write("**Line Items:**")
                    items_df = pd.DataFrame(items)
                    display_cols = ["description", "quantity", "amount"]
                    avail = [c for c in display_cols if c in items_df.columns]
                    if avail:
                        st.dataframe(
                            items_df[avail], hide_index=True, use_container_width=True
                        )

                # Raw text
                with st.expander("Raw OCR Text"):
                    raw = doc.get("raw_text") or ""
                    if raw:
                        st.code(raw[:2000] + ("..." if len(raw) > 2000 else ""))
                    else:
                        st.write("(No raw text stored)")

                # Transaction info
                txns = store.get_transactions_for_document(doc.get("id"))
                if txns:
                    st.write("**Category:**")
                    for txn in txns:
                        cat = txn.get("primary_category") or "Uncategorized"
                        conf = txn.get("confidence", 0)
                        rule = txn.get("rule_name") or "default"
                        cat_class = get_category_class(cat)
                        st.markdown(
                            f'<span class="category-chip {cat_class}">{cat}</span> '
                            f"<small>({conf:.0%} confidence, rule: {rule})</small>",
                            unsafe_allow_html=True,
                        )


# =============================================================================
# Page: Transactions
# =============================================================================


def page_transactions():
    """Transactions list page."""
    st.markdown(
        """
    <div class="main-header">
        <h1>Transactions</h1>
        <p>View and filter your categorized spending</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    store = get_store()

    # Filters in sidebar
    with st.sidebar:
        st.subheader("Filters")

        limit = st.slider("Show", 10, 500, 100, 10, key="txn_limit")

        spending = store.spending_by_category()
        categories = ["All"] + [s["category"] for s in spending]
        category = st.selectbox("Category", categories)
        category_filter = None if category == "All" else category

        uncategorized = st.checkbox("Uncategorized only")

        date_from = st.date_input("From Date", value=None, key="txn_date_from")
        date_to = st.date_input("To Date", value=None, key="txn_date_to")

    # Fetch transactions
    txns = store.list_transactions(
        limit=limit,
        category=category_filter,
        uncategorized_only=uncategorized,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )

    if not txns:
        st.info(
            "No transactions found. Upload and process documents to create transactions."
        )
        return

    # Summary
    total = sum(t.get("amount", 0) for t in txns)
    col1, col2 = st.columns(2)
    col1.metric("Total Transactions", len(txns))
    col2.metric("Total Amount", format_currency(total))

    st.divider()

    # Transactions table
    df = pd.DataFrame(txns)

    display_cols = [
        "date",
        "merchant_norm",
        "amount",
        "primary_category",
        "confidence",
        "rule_name",
    ]
    available = [c for c in display_cols if c in df.columns]

    # Format columns
    if "amount" in df.columns:
        df["amount"] = df["amount"].apply(
            lambda x: format_currency(x) if x else "$0.00"
        )
    if "confidence" in df.columns:
        df["confidence"] = df["confidence"].apply(lambda x: f"{x:.0%}" if x else "0%")

    st.dataframe(
        df[available].rename(
            columns={
                "date": "Date",
                "merchant_norm": "Merchant",
                "amount": "Amount",
                "primary_category": "Category",
                "confidence": "Confidence",
                "rule_name": "Rule",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


# =============================================================================
# Page: Categories
# =============================================================================


def page_categories():
    """Category breakdown page."""
    st.markdown(
        """
    <div class="main-header">
        <h1>Categories</h1>
        <p>Understand where your money goes</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    store = get_store()

    spending = store.spending_by_category()

    if not spending:
        st.info("No spending data yet. Upload documents to see category breakdown.")
        return

    total = sum(s.get("total", 0) for s in spending)

    # Category cards
    cols = st.columns(3)
    for i, item in enumerate(spending[:6]):
        with cols[i % 3]:
            cat = item["category"]
            cat_total = item["total"]
            count = item["count"]
            pct = (cat_total / total * 100) if total else 0
            avg = cat_total / count if count else 0

            st.markdown(
                f"""
            <div style="background: white; padding: 1.5rem; border-radius: 12px;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 1rem;
                        border-left: 4px solid {'#f59e0b' if 'food' in cat.lower() else '#3b82f6'};">
                <h3 style="margin: 0 0 0.5rem 0;">{cat}</h3>
                <div style="font-size: 1.5rem; font-weight: 700; color: #1f2937;">{format_currency(cat_total)}</div>
                <div style="color: #6b7280; font-size: 0.9rem;">
                    {count} transaction(s) &bull; {pct:.1f}% of total &bull; Avg: {format_currency(avg)}
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

    st.divider()

    # Full breakdown chart
    st.subheader("Spending Distribution")
    df = pd.DataFrame(spending)
    st.bar_chart(df.set_index("category")["total"], use_container_width=True)

    # Detailed table
    st.subheader("Detailed Breakdown")
    df["percentage"] = df["total"].apply(
        lambda x: f"{(x/total*100):.1f}%" if total else "0%"
    )
    df["average"] = df.apply(
        lambda r: format_currency(r["total"] / r["count"]) if r["count"] else "$0.00",
        axis=1,
    )
    df["total_fmt"] = df["total"].apply(format_currency)

    st.dataframe(
        df[["category", "count", "total_fmt", "percentage", "average"]].rename(
            columns={
                "category": "Category",
                "count": "Transactions",
                "total_fmt": "Total",
                "percentage": "% of Total",
                "average": "Average",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


# =============================================================================
# Page: Settings
# =============================================================================


def page_settings():
    """Settings and database management page."""
    st.markdown(
        """
    <div class="main-header">
        <h1>Settings</h1>
        <p>Database management and configuration</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    store = get_store()

    # Database stats
    st.subheader("Database Statistics")
    stats = store.get_stats()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Documents", stats.get("documents", 0))
    col2.metric("Line Items", stats.get("line_items", 0))
    col3.metric("Transactions", stats.get("transactions", 0))
    col4.metric("Merchants", stats.get("merchants", 0))
    col5.metric("Categories", stats.get("categories", 0))

    st.divider()

    # Actions
    st.subheader("Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Run Integrity Check", use_container_width=True):
            result = store.check_integrity()
            status = result.get("status", "unknown")

            if status == "ok":
                st.success(f"Database is healthy (version {result.get('version')})")
            elif status == "warning":
                st.warning("Database has warnings")
                for issue in result.get("issues", []):
                    st.write(f"- {issue}")
            else:
                st.error("Database has errors")
                for issue in result.get("issues", []):
                    st.write(f"- {issue}")

    with col2:
        if st.button("Normalize Merchants", use_container_width=True):
            result = store.normalize_all_merchants()
            st.success(
                f"Updated {result['updated']} documents, added {result['merchants_added']} merchants"
            )

    with col3:
        if st.button("Refresh Views", use_container_width=True):
            store.refresh_views()
            st.success("Compatibility views refreshed")

    st.divider()

    # Database path
    st.subheader("Configuration")
    st.write(f"**Database Path:** `{DB_PATH}`")
    st.write(f"**Project Root:** `{PROJECT_ROOT}`")

    # Clear cache
    st.divider()
    st.subheader("Cache Management")
    if st.button("Clear Application Cache", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.success("Cache cleared!")
        st.rerun()


# =============================================================================
# Main Application
# =============================================================================


def main():
    """Main application entry point."""

    # Sidebar navigation
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/money-bag.png", width=60)
        st.title("Smart Finance")
        st.write("---")

        # Navigation
        pages = {
            "Upload": ("cloud_upload", page_upload),
            "Dashboard": ("dashboard", page_dashboard),
            "Documents": ("description", page_documents),
            "Transactions": ("receipt_long", page_transactions),
            "Categories": ("category", page_categories),
            "Settings": ("settings", page_settings),
        }

        selected = st.radio(
            "Navigation",
            list(pages.keys()),
            label_visibility="collapsed",
        )

        st.write("---")

        # Quick stats
        store = get_store()
        stats = store.get_stats()
        st.caption(f"Documents: {stats.get('documents', 0)}")
        st.caption(f"Transactions: {stats.get('transactions', 0)}")

        st.write("---")
        st.caption("Smart Finance Advisor v1.0")

    # Render selected page
    _, page_func = pages[selected]
    page_func()


if __name__ == "__main__":
    main()
