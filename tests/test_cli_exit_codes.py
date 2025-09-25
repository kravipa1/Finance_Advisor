import subprocess
import sys


def test_cli_empty_dir_exit_code(tmp_path):
    # tmp_path is empty; should return code 2 (no files)
    cmd = [
        sys.executable,
        "-m",
        "cli.finproc",
        str(tmp_path),
        "--categorize",
        "--quiet",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2, f"stderr was: {proc.stderr}"
