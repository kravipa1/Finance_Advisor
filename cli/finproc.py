# cli/finproc.py
# Command-line ingest for Smart Personal Finance & Expense Advisor.
# - Single-file ingest (ingest)
# - Batch ingest over folders/files (ingest-batch)
# - Optional --watch polling (no extra deps) to auto-ingest new/changed files
#
# Examples:
#   python -m cli.finproc ingest data/samples/invoices/coffee_shop_01.txt
#   python -m cli.finproc ingest-batch data/samples/invoices --ext .txt,.pdf --recurse
#   python -m cli.finproc ingest-batch data/inbox --ext .pdf,.png --watch --interval 3
#
# Notes:
# - OCR here is a stub: .txt files read as text; others become a deterministic placeholder.
# - Normalizer preserves line breaks for parser regexes.

from __future__ import annotations

import os
import time
from typing import Iterable, List, Tuple, Dict, Set

import click

from storage.sqlite_store import (
    open_conn,
    ensure_schema,
    insert_receipt,
    exists_by_hash,
    migrate_add_sanity_flags,
    migrate_add_norm_hash,
)
from sfa_utils.fingerprint import normalized_text_fingerprint
from parser.extractor import extract, parsed_doc_as_row


# ---------- OCR + normalization (stubs you can swap later) ----------
def read_ocr_dual_pass(path: str) -> str:
    """
    .txt -> read as UTF-8 text.
    Other files (pdf/png/jpg) -> deterministic placeholder containing byte length.
    """
    _, ext = os.path.splitext(path.lower())
    if ext == ".txt":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
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


def _ingest_one(conn, path: str, *, force: bool = False) -> Tuple[str, str]:
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
                return "skip", f"[skip] duplicate by hash={norm_hash[:8]} • {path}"
            # fall through to re-insert
            status_prefix = "force"
        else:
            status_prefix = "ok"

        doc = extract(norm_text, source_path=path)
        row = parsed_doc_as_row(doc)
        row["norm_hash"] = norm_hash
        row["raw_text"] = raw_text
        rid = insert_receipt(conn, row)
        return (
            status_prefix,
            f"[{status_prefix}] id={rid} hash={norm_hash[:8]} • {path}",
        )
    except Exception as e:
        return "error", f"[error] {path} :: {e!r}"


def _ensure_db(conn) -> None:
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


if __name__ == "__main__":
    cli()
