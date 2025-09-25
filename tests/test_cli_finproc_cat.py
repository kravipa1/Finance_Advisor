import subprocess
import sys


def test_cli_runs_with_categorize(tmp_path):
    # create a dummy file the OCR/parse path will pick up; CLI handles .txt in tests
    p = tmp_path / "r.txt"
    p.write_text("STARBUCKS 09/01/2025 Total $7.89 Latte", encoding="utf-8")
    cmd = [sys.executable, "-m", "cli.finproc", str(p), "--categorize"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0
