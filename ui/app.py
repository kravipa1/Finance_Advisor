# ui/app.py
from __future__ import annotations
import streamlit as st
import pandas as pd
from storage.sqlite_store import open_conn, fetch_receipts

st.set_page_config(page_title="Smart Finance Advisor", layout="wide")


def chip(label: str, tone: str = "neutral"):
    colors = {
        "ok": "#10b981",
        "warn": "#f59e0b",
        "bad": "#ef4444",
        "neutral": "#6b7280",
    }
    color = colors.get(tone, colors["neutral"])
    st.markdown(
        f"""
        <span style="
            display:inline-block;
            padding:2px 8px; margin-right:6px; margin-bottom:6px;
            border-radius:999px; font-size:0.85rem;
            background:{color}1A; color:{color}; border:1px solid {color}33;">
            {label}
        </span>
        """,
        unsafe_allow_html=True,
    )


def sanity_chips(row: dict):
    if row.get("reconciled_used"):
        chip("Reconciled", "bad")
    diff = float(row.get("items_subtotal_diff") or 0.0)
    pct = float(row.get("items_subtotal_pct") or 0.0)
    if diff <= 0.02 or pct <= 0.01:
        chip("Items≈Subtotal", "ok")
    elif pct <= 0.05:
        chip("Check Items", "warn")
    else:
        chip("Mismatch", "bad")


def main():
    st.title("Smart Personal Finance & Expense Advisor")

    with st.sidebar:
        st.header("Filters")
        limit = st.number_input(
            "Max rows", min_value=10, max_value=2000, value=200, step=10
        )
        if st.button("Reload data", use_container_width=True):
            st.experimental_rerun()

    conn = open_conn()
    rows = fetch_receipts(conn, limit=limit)
    if not rows:
        st.info("No receipts ingested yet.")
        return

    df = pd.DataFrame([dict(r) for r in rows])

    def _status_label(r):
        if r["reconciled_used"]:
            return "Reconciled"
        p = float(r.get("items_subtotal_pct") or 0.0)
        if p <= 0.01:
            return "OK"
        if p <= 0.05:
            return "Check"
        return "Mismatch"

    df["Sanity"] = df.apply(_status_label, axis=1)
    df["DupHash"] = df["norm_hash"].fillna("").str.slice(0, 8)

    st.subheader("Receipts")
    st.dataframe(
        df[["date", "vendor", "total", "subtotal", "tax", "tip", "Sanity", "DupHash"]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Details")
    for r in rows:
        r = dict(r)
        with st.container(border=True):
            title_vendor = r.get("vendor") or "—"
            title_date = r.get("date") or "—"
            st.markdown(f"**{title_vendor}**  •  {title_date}")
            sanity_chips(r)
            st.write("")
            cols = st.columns(4)
            cols[0].metric("Total", f"${(r.get('total') or 0):.2f}")
            cols[1].metric("Subtotal", f"${(r.get('subtotal') or 0):.2f}")
            cols[2].metric("Tax", f"${(r.get('tax') or 0):.2f}")
            cols[3].metric("Tip", f"${(r.get('tip') or 0):.2f}")
            st.caption(
                f"Hash: `{(r.get('norm_hash') or '')[:20]}`  •  Diff: ${r.get('items_subtotal_diff') or 0:.2f}"
            )
            with st.expander("Debug: stored raw_text"):
                raw = r.get("raw_text") or ""
                if raw:
                    st.code("\n".join(raw.splitlines()[:60]), language="text")
                else:
                    st.text("(no raw_text stored)")


if __name__ == "__main__":
    main()
