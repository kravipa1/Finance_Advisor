# tests/test_cli_finproc.py
from click.testing import CliRunner
import sys
import pathlib

# Ensure project root is on sys.path (works even if pytest changes CWD)
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Try top-level 'finproc' first; fall back to the shim 'cli.finproc'
try:
    import finproc as fin
except ModuleNotFoundError:
    from cli import finproc as fin


def test_ingest_cmd_with_txt(tmp_path, sample_invoice_txt):
    db_path = tmp_path / "out.sqlite"
    runner = CliRunner()
    result = runner.invoke(
        fin.ingest_cmd, ["--db", str(db_path), str(sample_invoice_txt)]
    )
    assert result.exit_code == 0, result.output
    out = result.output.lower()
    assert any(tag in out for tag in ("[ok]", "[skip]", "[force]"))
