# cli/finproc.py  — small adapter so 'from cli import finproc' works
from importlib import import_module as _im

_fin = _im("finproc")  # imports your top-level finproc.py

# re-export everything public so tests can use cli.finproc.ingest_cmd, etc.
for _k in dir(_fin):
    if not _k.startswith("_"):
        globals()[_k] = getattr(_fin, _k)

del _im, _fin, _k
