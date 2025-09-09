# sfa_utils/fingerprint.py
# Purpose: stable text fingerprint for de-duplication.

from __future__ import annotations
import hashlib
import re


def canonicalize_text(s: str) -> str:
    """
    Minimal canonicalization so the same receipt text yields the same fingerprint.
    - Lowercase
    - Collapse whitespace
    """
    if not isinstance(s, str):
        s = str(s or "")
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalized_text_fingerprint(text: str) -> str:
    """
    Return a short, stable SHA-1 based fingerprint (first 20 hex chars).
    """
    canon = canonicalize_text(text)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:20]
