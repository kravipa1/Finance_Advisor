# sfa_utils/categorizer.py
from __future__ import annotations
import re
from typing import Optional, Dict, Any, List
from .categories import VENDOR_TO_CATEGORY, KEYWORD_TO_CATEGORY
from collections import Counter


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def guess_vendor_category(vendor_or_employer: Optional[str]) -> Optional[str]:
    """Return a category if vendor/employer name hints at one, else None."""
    if not vendor_or_employer:
        return None
    v = _norm(vendor_or_employer)
    for key, cat in VENDOR_TO_CATEGORY.items():
        if key in v:  # substring match to catch "Uber Technologies", etc.
            return cat
    return None


def guess_line_item_category(description: Optional[str]) -> Optional[str]:
    if not description:
        return None
    d = _norm(description)
    for key, cat in KEYWORD_TO_CATEGORY.items():
        if key in d:
            return cat
    return None


def apply_categories(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Doc-level category:
      1) vendor-mapped category if available
      2) else majority of line-item categories (if any)
    Line items: keyword categories on descriptions (do not override doc-level).
    """
    out = dict(doc)

    # 1) doc-level: vendor or employer, depending on kind
    vendor_name = None
    if out.get("kind") == "invoice":
        vendor_name = (
            out.get("vendor")
            if not isinstance(out.get("vendor"), dict)
            else out["vendor"].get("name")
        )
    elif out.get("kind") == "paystub":
        vendor_name = out.get("employer")

    doc_cat = guess_vendor_category(vendor_name)

    # 2) line-item categories (keyword-based)
    items: List[Dict[str, Any]] = out.get("line_items", []) or []
    new_items: List[Dict[str, Any]] = []
    item_cats: List[str] = []
    for it in items:
        it2 = dict(it)
        desc = it2.get("description") or it2.get("desc")
        li_cat = guess_line_item_category(desc)
        if li_cat:
            it2["category"] = li_cat
            item_cats.append(li_cat)
        new_items.append(it2)
    if items:
        out["line_items"] = new_items

    # 3) set doc category with fallback to item-majority if vendor unknown
    if doc_cat:
        out["category"] = doc_cat
    elif item_cats:
        out["category"] = Counter(item_cats).most_common(1)[0][0]

    return out
