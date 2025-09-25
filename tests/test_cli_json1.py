import json
import subprocess
import sys


def test_cli_jsonl_stream(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("STARBUCKS 09/01/2025 Total $7.89 Latte", encoding="utf-8")

    cmd = [sys.executable, "-m", "cli.finproc", str(p), "--categorize", "--jsonl"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1

    rec = json.loads(lines[0])
    assert rec.get("schema_version") == "1.0"
    result = rec.get("result", {})
    # Either a Transaction or a Document depending on flags; check doc fields
    doc = result.get("doc") or result
    assert "source_path" in doc and "vendor" in doc
