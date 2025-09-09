# tests/test_sanity_flags.py

from __future__ import annotations
from parser.extractor import compute_sanity


def test_items_subtotal_diff_and_pct_basic():
    # 2x $4.50 + 1x $7.00 = $16.00
    items = [
        {"desc": "coffee", "qty": 2, "unit_price": 4.50},
        {"desc": "sandwich", "qty": 1, "unit_price": 7.00},
    ]
    sanity = compute_sanity(items, subtotal=16.00)
    assert "items_subtotal_diff" in sanity and "items_subtotal_pct" in sanity
    assert sanity["items_subtotal_diff"] == 0.00
    assert sanity["items_subtotal_pct"] == 0.0


def test_items_subtotal_diff_and_pct_mismatch():
    # same items, but subtotal off by 0.06
    items = [
        {"desc": "coffee", "qty": 2, "unit_price": 4.50},
        {"desc": "sandwich", "qty": 1, "unit_price": 7.00},
    ]
    sanity = compute_sanity(items, subtotal=16.06)
    assert sanity["items_subtotal_diff"] == 0.06
    assert 0 < sanity["items_subtotal_pct"] <= 0.01
