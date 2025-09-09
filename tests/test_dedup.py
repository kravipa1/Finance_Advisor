# tests/test_dedup.py

from __future__ import annotations
from sfa_utils.fingerprint import normalized_text_fingerprint


def test_normalized_text_fingerprint_stable():
    a = "  SAFEWAY\nTotal: $17.94 "
    b = "safeway   total: $17.94"
    assert normalized_text_fingerprint(a) == normalized_text_fingerprint(b)
