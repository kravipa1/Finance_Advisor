# ui/app.py
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st

from config.loader import load_config
from pipeline.process_file import process_file
from storage.sqlite_store import init_db, save_document

DB_DEFAULT = Path("data/app.db")


@st.cache_resource
def get_conn(db_path: Path):
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row
    return con


def df_query(con, sql, params=()):
    cur = con.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def main():
    st.set_page_config(page_title="Smart Finance Advisor DB", layout="wide")
    cfg = load_config()
    db_path = Path(st.sidebar.text_input("SQLite path", str(DB_DEFAULT)))
    init_db(db_path)
    con = get_conn(db_path)

    # --- Upload & process ---
    st.sidebar.markdown("### Upload & Process")
    uploaded = st.sidebar.file_uploader(
        "Invoice/Paystub (image/pdf/txt)", type=["jpg", "jpeg", "png", "pdf", "txt"]
    )
    if uploaded is not None:
        # Save to uploads/
        uploads = Path("data/uploads")
        uploads.mkdir(parents=True, exist_ok=True)
        fpath = uploads / uploaded.name
        fpath.write_bytes(uploaded.getbuffer())

        # Run pipeline and save
        ocrdir = Path(cfg["paths"]["ocrdir"])
        ocrdir.mkdir(parents=True, exist_ok=True)
        normdir = Path(cfg["paths"]["normdir"])
        normdir.mkdir(parents=True, exist_ok=True)
        parsedir = Path(cfg["paths"]["parsedir"])
        parsedir.mkdir(parents=True, exist_ok=True)

        _, _, _, data = process_file(
            fpath,
            ocrdir,
            normdir,
            parsedir,
            languages=cfg["ocr"]["languages"],
            gpu=cfg["ocr"]["gpu"],
            min_confidence=cfg["ocr"]["min_confidence"],
            paragraph=cfg["ocr"]["paragraph"],
            dpi=cfg["ocr"]["dpi"],
        )
        doc_id = save_document(db_path, data)
        st.sidebar.success(f"Processed & saved (id {doc_id})")

    # --- Filters ---
    st.sidebar.markdown("### Filters")
    vendor = st.sidebar.text_input("Vendor/Employer (contains)", "")
    category = st.sidebar.text_input("Category (exact)", "")
    kind = st.sidebar.selectbox("Kind", ["", "invoice", "paystub"], index=0)
    hide_low = st.sidebar.checkbox("Hide low-confidence", value=False)

    where = []
    args = []
    if vendor:
        where.append("vendor_or_employer LIKE ?")
        args.append(f"%{vendor}%")
    if category:
        where.append("category = ?")
        args.append(category)
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if hide_low:
        # raw_json LIKE is crude but effective; relies on the 'sanity.low_confidence' flag
        where.append("raw_json NOT LIKE '%\"low_confidence\": true%'")
    W = ("WHERE " + " AND ".join(where)) if where else ""

    # --- Documents table ---
    docs = df_query(
        con,
        f"""
        SELECT id, kind, vendor_or_employer, invoice_number, total, net_pay, category,
               invoice_date_iso, due_date_iso
        FROM documents {W}
        ORDER BY id DESC
        LIMIT 200
    """,
        tuple(args),
    )
    st.subheader("Documents")
    st.dataframe(docs, use_container_width=True, hide_index=True)

    doc_id = st.selectbox(
        "Open document id",
        docs["id"].tolist() if not docs.empty else [],
        index=0 if not docs.empty else None,
    )

    # --- Aggregates ---
    st.markdown("### Spend by Category (from line items)")
    cat_df = df_query(
        con,
        """
        SELECT COALESCE(li.category, d.category, 'Uncategorized') AS category,
               SUM(li.line_total_value) AS spend
        FROM line_items li
        JOIN documents d ON d.id = li.document_id
        GROUP BY 1
        ORDER BY spend DESC
    """,
    )
    if not cat_df.empty:
        st.bar_chart(cat_df.set_index("category")["spend"])

    # --- Detail view ---
    if doc_id:
        doc = df_query(con, "SELECT * FROM documents WHERE id = ?", (int(doc_id),))
        items = df_query(
            con,
            """
            SELECT idx, qty, description, unit_price_value, line_total_value, category
            FROM line_items WHERE document_id = ? ORDER BY idx
        """,
            (int(doc_id),),
        )

        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown("### Line Items")
            st.dataframe(items, use_container_width=True, hide_index=True)

            # CSV export for this doc's line items
            if not items.empty:
                csv_bytes = items.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download items CSV",
                    data=csv_bytes,
                    file_name=f"doc_{doc_id}_items.csv",
                    mime="text/csv",
                )

        with c2:
            st.markdown("### Raw JSON")
            raw = doc.iloc[0]["raw_json"] if not doc.empty else "{}"
            st.code(
                json.dumps(json.loads(raw), indent=2, ensure_ascii=False),
                language="json",
            )
            st.download_button(
                "Download JSON",
                data=raw.encode("utf-8"),
                file_name=f"doc_{doc_id}.json",
                mime="application/json",
            )


if __name__ == "__main__":
    main()
