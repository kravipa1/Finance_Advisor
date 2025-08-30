# config/loader.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict

# Python 3.11 has tomllib; fall back to "tomli" on older versions if needed
try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def load_config(config_path: Path | None = None) -> Dict[str, Any]:
    """
    Load config.toml from repo root by default.
    """
    if config_path is None:
        # repo root is parent of this file's parent
        repo = Path(__file__).resolve().parents[1]
        config_path = repo / "config.toml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with config_path.open("rb") as f:
        return tomllib.load(f)
