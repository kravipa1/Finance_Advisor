# finproc.py
# Command-line ingest for Smart Personal Finance & Expense Advisor.
# - Single-file ingest (ingest)
# - Batch ingest over folders/files (ingest-batch)
# - Optional --watch polling (no extra deps) to auto-ingest new/changed files
# - Database management (--sqlite-init, --sqlite-check, etc.)
# - Categorization (categorize)
#
# Examples:
#   python finproc.py ingest data/samples/invoices/coffee_shop_01.txt
#   python finproc.py ingest-batch data/samples/invoices --ext .txt,.pdf --recurse
#   python finproc.py ingest-batch data/inbox --ext .pdf,.png --watch --interval 3
#   python finproc.py categorize --db data/finance.sqlite
#   python finproc.py db --init --db data/finance.sqlite
#   python finproc.py db --check --db data/finance.sqlite
#
# Notes:
# - OCR: .txt files read as text; images/PDFs use EasyOCR when available.
# - Normalizer preserves line breaks for parser regexes.

from __future__ import annotations

import json
import os
import time
from typing import Iterable, List, Tuple, Dict, Set, Optional

import click

from storage.sqlite_store import (
    SQLiteStore,
    open_conn,
    ensure_schema,
    insert_receipt,
    exists_by_hash,
    migrate_add_sanity_flags,
    migrate_add_norm_hash,
)
from storage.migrations import (
    ensure_current_schema,
    check_integrity,
    get_table_stats,
    refresh_views,
    SCHEMA_VERSION,
)
from sfa_utils.fingerprint import normalized_text_fingerprint
from parser.extractor import extract, parsed_doc_as_row


# ---------- OCR + normalization ----------
def read_ocr_dual_pass(path: str) -> str:
    """
    .txt -> read as UTF-8 text.
    Images (png/jpg) -> use EasyOCR if available.
    PDFs -> use PyMuPDF + EasyOCR if available.
    Falls back to placeholder if OCR not available.
    """
    _, ext = os.path.splitext(path.lower())

    if ext == ".txt":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    # Try real OCR for images
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff"):
        try:
            from ocr.reader import read_image

            return read_image(path)
        except ImportError:
            pass  # OCR not available
        except Exception as e:
            click.echo(f"[warn] OCR failed for {path}: {e}", err=True)

    # Try real OCR for PDFs
    if ext == ".pdf":
        try:
            from ocr.reader import read_pdf

            return read_pdf(path)
        except ImportError:
            pass  # OCR not available
        except Exception as e:
            click.echo(f"[warn] PDF OCR failed for {path}: {e}", err=True)

    # Fallback: placeholder
    with open(path, "rb") as f:
        blob = f.read()
    return f"(bytes={len(blob)})"


def normalize_text(text: str) -> str:
    """
    Normalize while preserving line breaks so the parser can see one line per item.
    - Lowercase
    - Strip extra spaces inside each line
    """
    lines: List[str] = []
    for raw in (text or "").splitlines():
        s = " ".join(raw.strip().split()).lower()
        if s:
            lines.append(s)
    return "\n".join(lines)


# ----------------------------- Helpers -----------------------------
DEFAULT_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".txt")


def _exts_from_csv(csv: str | None) -> Tuple[str, ...]:
    if not csv:
        return DEFAULT_EXTS
    parts = [p.strip().lower() for p in csv.split(",") if p.strip()]
    parts = [p if p.startswith(".") else f".{p}" for p in parts]
    return tuple(parts) if parts else DEFAULT_EXTS


def discover_files(
    paths: Iterable[str], *, exts: Tuple[str, ...], recurse: bool
) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for root in paths:
        root = os.path.abspath(root)
        if os.path.isfile(root):
            if root.lower().endswith(exts):
                if root not in seen:
                    seen.add(root)
                    out.append(root)
            continue
        if os.path.isdir(root):
            if recurse:
                for dirpath, _dirs, files in os.walk(root):
                    for fn in files:
                        fp = os.path.join(dirpath, fn)
                        if fp.lower().endswith(exts) and fp not in seen:
                            seen.add(fp)
                            out.append(fp)
            else:
                for fn in os.listdir(root):
                    fp = os.path.join(root, fn)
                    if (
                        os.path.isfile(fp)
                        and fp.lower().endswith(exts)
                        and fp not in seen
                    ):
                        seen.add(fp)
                        out.append(fp)
    out.sort()
    return out


def _ingest_one(
    conn, path: str, *, force: bool = False, use_new_schema: bool = True
) -> Tuple[str, str]:
    """
    Returns (status, message)
      status in {"ok","skip","force","error"}
    """
    try:
        raw_text = read_ocr_dual_pass(path)
        norm_text = normalize_text(raw_text)
        norm_hash = normalized_text_fingerprint(norm_text)

        if exists_by_hash(conn, norm_hash):
            if not force:
                return "skip", f"[skip] duplicate by hash={norm_hash[:8]} | {path}"
            # Delete existing and re-insert
            from storage.sqlite_store import delete_by_hash

            delete_by_hash(conn, norm_hash)
            status_prefix = "force"
        else:
            status_prefix = "ok"

        parsed = extract(norm_text, source_path=path)
        row = parsed_doc_as_row(parsed)
        row["norm_hash"] = norm_hash
        row["raw_text"] = raw_text

        # Use new schema if available (documents table)
        from storage.migrations import table_exists

        if use_new_schema and table_exists(conn, "documents"):
            store = SQLiteStore.__new__(SQLiteStore)
            store._conn = conn
            store.db_path = ""

            # Insert document
            doc_id = store.insert_document(
                vendor=row.get("vendor"),
                date=row.get("date"),
                total=row.get("total"),
                subtotal=row.get("subtotal"),
                tax=row.get("tax"),
                tip=row.get("tip"),
                raw_text=raw_text,
                norm_hash=norm_hash,
                doc_type="receipt",
                source_file=path,
                reconciled_used=row.get("reconciled_used", 0),
                items_subtotal_diff=row.get("items_subtotal_diff", 0.0),
                items_subtotal_pct=row.get("items_subtotal_pct", 0.0),
            )

            # Insert line items if available
            if parsed.line_items:
                store.insert_line_items_batch(doc_id, parsed.line_items)

            return (
                status_prefix,
                f"[{status_prefix}] id={doc_id} hash={norm_hash[:8]} | {path}",
            )
        else:
            # Legacy: use receipts table
            rid = insert_receipt(conn, row)
            return (
                status_prefix,
                f"[{status_prefix}] id={rid} hash={norm_hash[:8]} | {path}",
            )
    except Exception as e:
        return "error", f"[error] {path} :: {e!r}"


def _ensure_db(conn) -> None:
    """Ensure database has current schema (new or legacy)."""
    # Use new schema by default
    result = ensure_current_schema(conn)
    if result["status"] == "current":
        return
    # Also ensure legacy schema for backwards compat
    ensure_schema(conn)
    migrate_add_sanity_flags(conn)
    migrate_add_norm_hash(conn)


# ----------------------------- CLI -----------------------------
@click.group()
def cli() -> None:
    """Finance processor CLI."""


@cli.command("ingest")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option(
    "--db",
    "db_path",
    default="data/finance.sqlite",
    show_default=True,
    help="Path to SQLite database file.",
)
@click.option("--csv-out", is_flag=True, help="Also write CSV row (stub only).")
@click.option(
    "--force", is_flag=True, help="Replace existing row with same normalized-text hash."
)
def ingest_cmd(path: str, db_path: str, csv_out: bool, force: bool) -> None:
    """Ingest a single file into SQLite with de-dup by normalized-text hash."""
    conn = open_conn(db_path)
    _ensure_db(conn)

    status, msg = _ingest_one(conn, os.path.abspath(path), force=force)
    click.echo(msg)

    if csv_out:
        click.echo("[note] CSV export not implemented in this stub.")


@cli.command("ingest-batch")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, readable=True))
@click.option(
    "--db",
    "db_path",
    default="data/finance.sqlite",
    show_default=True,
    help="Path to SQLite database file.",
)
@click.option(
    "--ext",
    "ext_csv",
    default=".pdf,.png,.jpg,.jpeg,.txt",
    show_default=True,
    help="Comma-separated list of file extensions to include.",
)
@click.option(
    "--recurse/--no-recurse",
    default=True,
    show_default=True,
    help="Recurse into subdirectories when PATH is a folder.",
)
@click.option(
    "--force", is_flag=True, help="Replace existing row with same normalized-text hash."
)
@click.option(
    "--watch",
    is_flag=True,
    help="Watch folders and ingest new/changed files (polling).",
)
@click.option(
    "--interval",
    default=2.0,
    show_default=True,
    help="Polling interval seconds for --watch.",
)
def ingest_batch_cmd(
    paths: Tuple[str, ...],
    db_path: str,
    ext_csv: str,
    recurse: bool,
    force: bool,
    watch: bool,
    interval: float,
) -> None:
    """
    Ingest many files and/or folders.
    - De-dup by normalized-text hash (same as single ingest).
    - With --watch, keeps polling and ingests new/changed files.
    """
    if not paths:
        raise click.UsageError("Provide one or more PATHS (files or directories).")

    exts = _exts_from_csv(ext_csv)
    conn = open_conn(db_path)
    _ensure_db(conn)

    def run_once() -> Dict[str, int]:
        stats = {"ok": 0, "skip": 0, "force": 0, "error": 0}
        files = discover_files(paths, exts=exts, recurse=recurse)
        if not files:
            click.echo("[info] no matching files found.")
            return stats

        click.echo(f"[info] found {len(files)} file(s).")
        for fp in files:
            status, msg = _ingest_one(conn, fp, force=force)
            stats[status] = stats.get(status, 0) + 1
            click.echo(msg)
        click.echo(
            f"[sum] ok={stats['ok']} force={stats['force']} skip={stats['skip']} error={stats['error']}"
        )
        return stats

    if not watch:
        run_once()
        return

    # Simple polling watcher: track mod-times; ingest when a file is new or changed.
    click.echo(
        f"[watch] watching {'; '.join(paths)} every {interval:.1f}s; extensions={','.join(exts)}; recurse={recurse}"
    )
    known_mtime: Dict[str, float] = {}
    try:
        while True:
            files = discover_files(paths, exts=exts, recurse=recurse)
            newly_changed: List[str] = []
            for fp in files:
                try:
                    mtime = os.path.getmtime(fp)
                except FileNotFoundError:
                    continue
                last = known_mtime.get(fp)
                if last is None or mtime > last:
                    known_mtime[fp] = mtime
                    newly_changed.append(fp)

            if newly_changed:
                click.echo(
                    f"[watch] detected {len(newly_changed)} new/changed file(s)."
                )
                stats = {"ok": 0, "skip": 0, "force": 0, "error": 0}
                for fp in newly_changed:
                    status, msg = _ingest_one(conn, fp, force=force)
                    stats[status] = stats.get(status, 0) + 1
                    click.echo(msg)
                click.echo(
                    f"[sum] ok={stats['ok']} force={stats['force']} skip={stats['skip']} error={stats['error']}"
                )
            time.sleep(max(0.5, float(interval)))
    except KeyboardInterrupt:
        click.echo("\n[watch] stopped.")
        return


# ----------------------------- Database Management Commands -----------------------------
@cli.command("db")
@click.option(
    "--db",
    "db_path",
    default="data/finance.sqlite",
    show_default=True,
    help="Path to SQLite database file.",
)
@click.option(
    "--init",
    "do_init",
    is_flag=True,
    help="Initialize database with full schema (documents, line_items, transactions, etc.).",
)
@click.option(
    "--check",
    "do_check",
    is_flag=True,
    help="Run integrity checks and report database health.",
)
@click.option(
    "--compat-views",
    "do_views",
    is_flag=True,
    help="Create or refresh compatibility views (documents_v, line_items_v, transactions_v).",
)
@click.option(
    "--merchant-normalize",
    "do_merchant_norm",
    is_flag=True,
    help="Backfill vendor_norm column and populate merchants table.",
)
@click.option(
    "--stats",
    "do_stats",
    is_flag=True,
    help="Show table row counts.",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output results as JSON.",
)
def db_cmd(
    db_path: str,
    do_init: bool,
    do_check: bool,
    do_views: bool,
    do_merchant_norm: bool,
    do_stats: bool,
    output_json: bool,
) -> None:
    """
    Database management commands.

    Examples:

        finproc db --init --db data/finance.sqlite

        finproc db --check --json

        finproc db --merchant-normalize
    """
    if not any([do_init, do_check, do_views, do_merchant_norm, do_stats]):
        click.echo(
            "No action specified. Use --init, --check, --compat-views, --merchant-normalize, or --stats."
        )
        click.echo("Run 'finproc db --help' for usage.")
        raise SystemExit(1)

    conn = open_conn(db_path)

    results: Dict = {"db_path": db_path, "actions": []}

    # --init: Initialize/migrate schema
    if do_init:
        result = ensure_current_schema(conn)
        results["init"] = result
        results["actions"].append("init")
        if not output_json:
            click.echo(
                f"[init] status={result['status']}, schema_version={SCHEMA_VERSION}"
            )
            if result["status"] == "initialized":
                click.echo(f"  - Created {result.get('tables_created', 0)} tables")
                click.echo(f"  - Created {result.get('views_created', 0)} views")
                click.echo(
                    f"  - Seeded {result.get('categories_seeded', 0)} categories"
                )
            elif result["status"] == "migrated":
                if result.get("receipts_migrated", 0) > 0:
                    click.echo(
                        f"  - Migrated {result['receipts_migrated']} receipts to documents"
                    )
                if result.get("tables_created"):
                    click.echo(
                        f"  - Created tables: {', '.join(result['tables_created'])}"
                    )

    # --check: Run integrity checks
    if do_check:
        result = check_integrity(conn)
        results["check"] = result
        results["actions"].append("check")
        if not output_json:
            status_icon = (
                "[OK]"
                if result["status"] == "ok"
                else "[WARN]" if result["status"] == "warning" else "[ERR]"
            )
            click.echo(
                f"[check] {status_icon} status={result['status']}, version={result['version']}"
            )
            click.echo(f"  - integrity_check: {result['integrity_check']}")

            # Table status
            click.echo("  - tables:")
            for table, info in result["tables"].items():
                exists = "[+]" if info.get("exists", True) else "[-]"
                rows = info.get("rows", 0)
                empty = " (empty)" if info.get("empty") else ""
                click.echo(f"      {exists} {table}: {rows} rows{empty}")

            # Views
            click.echo("  - views:")
            for view, exists in result["views"].items():
                icon = "[+]" if exists else "[-]"
                click.echo(f"      {icon} {view}")

            # Issues
            if result["issues"]:
                click.echo("  - issues:")
                for issue in result["issues"]:
                    click.echo(f"      ! {issue}")

        # Set exit code based on status
        if result["status"] == "error":
            results["exit_code"] = 3
        elif result["status"] == "warning":
            results["exit_code"] = 2

    # --compat-views: Refresh views
    if do_views:
        refresh_views(conn)
        results["actions"].append("compat-views")
        results["views_refreshed"] = True
        if not output_json:
            click.echo(
                "[compat-views] Refreshed documents_v, line_items_v, transactions_v, receipts_v"
            )

    # --merchant-normalize: Backfill vendor_norm
    if do_merchant_norm:
        store = SQLiteStore(db_path)
        store._conn = conn  # Reuse connection
        stats = store.normalize_all_merchants()
        results["merchant_normalize"] = stats
        results["actions"].append("merchant-normalize")
        if not output_json:
            click.echo(
                f"[merchant-normalize] Updated {stats['updated']} documents, added {stats['merchants_added']} merchants"
            )

    # --stats: Show row counts
    if do_stats:
        stats = get_table_stats(conn)
        results["stats"] = stats
        results["actions"].append("stats")
        if not output_json:
            click.echo("[stats] Table row counts:")
            for table, count in stats.items():
                if count >= 0:
                    click.echo(f"  - {table}: {count}")
                else:
                    click.echo(f"  - {table}: (not found)")

    # Output JSON if requested
    if output_json:
        click.echo(json.dumps(results, indent=2))

    # Exit with appropriate code
    exit_code = results.get("exit_code", 0)
    if exit_code != 0:
        raise SystemExit(exit_code)


# ----------------------------- Categorize Command -----------------------------
@cli.command("categorize")
@click.option(
    "--db",
    "db_path",
    default="data/finance.sqlite",
    show_default=True,
    help="Path to SQLite database file.",
)
@click.option(
    "--rules",
    "rules_path",
    default=None,
    help="Path to rules YAML file. Uses built-in defaults if not specified.",
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Re-categorize all documents, not just uncategorized ones.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be categorized without saving to database.",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output results as JSON.",
)
def categorize_cmd(
    db_path: str,
    rules_path: Optional[str],
    refresh: bool,
    dry_run: bool,
    output_json: bool,
) -> None:
    """
    Apply rule-based categorization to documents.

    Examples:

        finproc categorize --db data/finance.sqlite

        finproc categorize --refresh --rules config/my_rules.yaml

        finproc categorize --dry-run
    """
    from categorizer.service import CategorizerService
    from adapters.legacy import LegacyAdapter

    # Ensure schema
    conn = open_conn(db_path)
    ensure_current_schema(conn)

    store = SQLiteStore(db_path)
    store._conn = conn

    # Load categorizer
    cat_svc = CategorizerService(rules_path=rules_path)

    # Get documents to process
    if refresh:
        docs = store.list_documents(limit=10000)
    else:
        docs = store.get_uncategorized_documents()

    if not docs:
        if not output_json:
            click.echo("[categorize] No documents to categorize.")
        else:
            click.echo(json.dumps({"status": "ok", "processed": 0, "results": []}))
        return

    if not output_json:
        mode = "refresh all" if refresh else "uncategorized only"
        click.echo(f"[categorize] Processing {len(docs)} documents ({mode})...")

    adapter = LegacyAdapter()
    results = []
    stats = {"categorized": 0, "errors": 0}

    for doc_row in docs:
        try:
            # Build Document from raw_text
            raw_text = doc_row.get("raw_text", "")
            doc = adapter.build(
                source_path=doc_row.get("source_file", ""),
                ocr_text=raw_text,
                parsed=None,
            )
            doc.doc_id = doc_row.get("doc_id", "")

            # Categorize with rule tracking
            txn, rule_name = cat_svc.categorize_with_rule(doc)
            cat = txn.category

            result = {
                "doc_id": doc_row.get("doc_id"),
                "vendor": doc_row.get("vendor"),
                "primary_category": cat.primary_category if cat else None,
                "secondary_category": cat.secondary_category if cat else None,
                "confidence": cat.confidence if cat else 0,
                "tags": cat.tags if cat else [],
                "rule_name": rule_name,
            }
            results.append(result)

            if not dry_run and cat:
                # Delete existing transactions for this document
                store.delete_transactions_for_document(doc_row["id"])

                # Insert new transaction with rule name
                store.insert_transaction(
                    document_id=doc_row["id"],
                    amount=doc_row.get("total") or 0,
                    date=doc_row.get("date"),
                    merchant_norm=doc_row.get("vendor_norm"),
                    primary_category=cat.primary_category,
                    secondary_category=cat.secondary_category,
                    confidence=cat.confidence,
                    tags=cat.tags,
                    rule_name=rule_name,
                )
                stats["categorized"] += 1

            if not output_json and not dry_run:
                cat_display = cat.primary_category if cat else "Uncategorized"
                conf_display = f"{cat.confidence:.0%}" if cat else "0%"
                rule_info = f" [{rule_name}]" if rule_name else ""
                click.echo(
                    f"  [{cat_display}] {doc_row.get('vendor', 'N/A')} ({conf_display}){rule_info}"
                )

        except Exception as e:
            stats["errors"] += 1
            if not output_json:
                click.echo(f"  [error] {doc_row.get('doc_id', '?')}: {e}", err=True)

    # Summary
    if output_json:
        click.echo(
            json.dumps(
                {
                    "status": "ok",
                    "processed": len(docs),
                    "categorized": stats["categorized"],
                    "errors": stats["errors"],
                    "dry_run": dry_run,
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        if dry_run:
            click.echo(
                f"[categorize] Dry run: would categorize {len(results)} documents"
            )
        else:
            click.echo(
                f"[categorize] Done: {stats['categorized']} categorized, {stats['errors']} errors"
            )


if __name__ == "__main__":
    cli()
