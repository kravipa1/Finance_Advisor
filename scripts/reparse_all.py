# scripts/reparse_all.py
from __future__ import annotations


from storage.sqlite_store import (
    open_conn,
    ensure_schema,
    fetch_receipts,
    update_receipt_fields,
)
from parser.extractor import extract, parsed_doc_as_row


def normalize_text(text: str) -> str:
    # Same minimal normalizer as CLI; adjust if you add your real normalizer.
    return " ".join((text or "").split()).lower()


if __name__ == "__main__":
    conn = open_conn("data/finance.sqlite")
    ensure_schema(conn)

    rows = fetch_receipts(conn, limit=10_000)
    if not rows:
        print("No receipts to reparse.")
        raise SystemExit(0)

    updated = 0
    for r in rows:
        rid = r["id"]
        raw = r["raw_text"] or ""
        norm_text = normalize_text(raw)
        doc = extract(norm_text, source_path=f"(reparse id={rid})")
        row = parsed_doc_as_row(doc)
        update_receipt_fields(conn, rid, row)
        updated += 1

    print(f"✅ Reparsed and updated {updated} receipt(s).")
