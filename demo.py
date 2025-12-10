#!/usr/bin/env python3
# demo.py
"""
Demo script for Smart Finance Advisor.

Demonstrates the full pipeline:
1. Initialize database
2. Ingest sample documents
3. Categorize transactions
4. Show statistics
5. Optionally launch dashboard

Usage:
    python demo.py              # Run full demo
    python demo.py --dashboard  # Also launch Streamlit dashboard
    python demo.py --reset      # Reset database before demo
"""
from __future__ import annotations

import argparse
import os
import sys
import subprocess
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_cmd(
    cmd: list, description: str, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a command with nice output."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}")
    print(f"  > {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=False)

    if check and result.returncode != 0:
        print(f"\n[ERROR] Command failed with exit code {result.returncode}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Smart Finance Advisor Demo")
    parser.add_argument(
        "--dashboard", action="store_true", help="Launch Streamlit dashboard after demo"
    )
    parser.add_argument(
        "--reset", action="store_true", help="Reset database before running demo"
    )
    parser.add_argument(
        "--db",
        default="data/demo.sqlite",
        help="Database path (default: data/demo.sqlite)",
    )
    args = parser.parse_args()

    print(
        """
    =============================================
           Smart Finance Advisor Demo
    =============================================

    This demo will:
    1. Initialize a fresh database
    2. Ingest sample receipts, invoices, and paystubs
    3. Apply categorization rules
    4. Display statistics
    """
    )

    db_path = args.db

    # Ensure data directory exists
    data_dir = Path(db_path).parent
    data_dir.mkdir(parents=True, exist_ok=True)

    # Reset database if requested
    if args.reset and Path(db_path).exists():
        print(f"\n[INFO] Removing existing database: {db_path}")
        Path(db_path).unlink()

    # Step 1: Initialize database
    run_cmd(
        ["python", "-m", "finproc", "db", "--init", "--db", db_path],
        "Step 1: Initialize Database Schema",
    )

    # Step 2: Ingest sample files
    samples_dir = PROJECT_ROOT / "data" / "samples"

    if samples_dir.exists():
        # Ingest invoices/receipts
        invoices_dir = samples_dir / "invoices"
        if invoices_dir.exists():
            run_cmd(
                [
                    "python",
                    "-m",
                    "finproc",
                    "ingest-batch",
                    str(invoices_dir),
                    "--db",
                    db_path,
                ],
                "Step 2a: Ingest Invoices/Receipts",
            )

        # Ingest paystubs
        paystubs_dir = samples_dir / "paystubs"
        if paystubs_dir.exists():
            run_cmd(
                [
                    "python",
                    "-m",
                    "finproc",
                    "ingest-batch",
                    str(paystubs_dir),
                    "--db",
                    db_path,
                ],
                "Step 2b: Ingest Paystubs",
            )
    else:
        print(f"\n[WARN] Samples directory not found: {samples_dir}")
        print("       Creating sample receipt for demo...")

        # Create a sample receipt
        sample_file = PROJECT_ROOT / "data" / "demo_receipt.txt"
        sample_file.write_text(
            """Starbucks Coffee
Date: 2025-12-01
Items:
- Grande Latte 1 x 5.45 = 5.45
- Chocolate Croissant 1 x 3.95 = 3.95
Subtotal: 9.40
Tax: 0.85
Total: 10.25
"""
        )
        run_cmd(
            ["python", "-m", "finproc", "ingest", str(sample_file), "--db", db_path],
            "Step 2: Ingest Sample Receipt",
        )

    # Step 3: Categorize transactions
    rules_path = PROJECT_ROOT / "config" / "rules.yaml"
    if rules_path.exists():
        run_cmd(
            [
                "python",
                "-m",
                "finproc",
                "categorize",
                "--db",
                db_path,
                "--rules",
                str(rules_path),
            ],
            "Step 3: Apply Categorization Rules",
        )
    else:
        run_cmd(
            ["python", "-m", "finproc", "categorize", "--db", db_path],
            "Step 3: Apply Default Categorization",
        )

    # Step 4: Show database statistics
    run_cmd(
        ["python", "-m", "finproc", "db", "--stats", "--db", db_path],
        "Step 4: Database Statistics",
    )

    # Step 5: Run integrity check
    run_cmd(
        ["python", "-m", "finproc", "db", "--check", "--db", db_path],
        "Step 5: Integrity Check",
    )

    print(
        f"""
    =============================================
           Demo Complete!
    =============================================

    Database created at: {db_path}

    Next steps:
    - View data in the dashboard: streamlit run ui/app.py
    - Check the database: python -m finproc db --stats --db {db_path}
    - Add more documents: python -m finproc ingest <file> --db {db_path}
    """
    )

    # Launch dashboard if requested
    if args.dashboard:
        print("\n[INFO] Launching Streamlit dashboard...")
        print("       Press Ctrl+C to stop\n")

        # Set database path for Streamlit
        os.environ["SFA_DB_PATH"] = db_path

        subprocess.run(
            ["streamlit", "run", str(PROJECT_ROOT / "ui" / "app.py")], cwd=PROJECT_ROOT
        )


if __name__ == "__main__":
    main()
