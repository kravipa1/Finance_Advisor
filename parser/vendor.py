# parser/vendor.py
from __future__ import annotations
import re
from typing import List, Optional, Tuple

DOMAIN_RX = re.compile(
    r"\b(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9\-]{1,63})\.(?:[a-z]{2,})(?:/[^\s]*)?",
    re.I,
)
EMAIL_RX = re.compile(r"[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})", re.I)

ORG_HINTS = re.compile(
    r"\b(inc|ltd|llc|gmbh|s\.a\.|sa|sarl|s\.r\.l\.|srl|s\.r\.o\.|oy|aps|kft|bv|ag|plc|pvt|pte|pty|sas|sasu|spa|ab)\b",
    re.I,
)
ADDRESS_HINT = re.compile(
    r"\b(st(?:\.|reet)?|ave(?:\.|nue)?|road|rd\.|blvd|suite|floor|zip|postal|city|state|phone|tel|fax)\b",
    re.I,
)

IGNORE_PHRASES = [
    "thanks for shopping with",
    "thank you for your purchase",
    "invoice",
    "receipt",
    "order details",
    "transaction details",
]


def _uppercase_ratio(s: str) -> float:
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(ch.isupper() for ch in letters) / len(letters)


def _brand_from_domain(dom: str) -> Optional[str]:
    host = dom.split(".")[0]
    if host and host.lower() != "www":
        return host.replace("-", " ").strip().title()
    return None


def _clean_vendor_name(s: str) -> str:
    s_low = s.lower()
    if "thanks for shopping with" in s_low:
        s = re.sub(r".*?\bwith\b", "", s, flags=re.I)

    # remove noisy trailing glyphs and non vendor-ish chars
    s = re.sub(r"[|!•·•]+$", "", s)
    s = re.sub(r"[^A-Za-z0-9&.\s\-]", "", s).strip()
    s = re.sub(r"\s{2,}", " ", s)

    # common OCR tail: "Safeway!" -> "Safewayl" / "|" / "I" → trim if looks bogus
    if re.search(r"[A-Za-z]{3,}[lI|]$", s) and not re.search(r"[aeiou]l$", s, re.I):
        s = s[:-1]

    return s.strip()


def guess_vendor(lines: List[str]) -> Optional[str]:
    """
    Vendor detection with no whitelists:
      - domain/email → brand
      - top-of-page lines scored by position, caps, org hints, proximity to address
    """
    if not lines:
        return None

    # 1) domain/email clues in first 50 lines
    domain_hits: List[str] = []
    for ln in lines[:50]:
        domain_hits += [m.group(1).lower() for m in DOMAIN_RX.finditer(ln)]
        domain_hits += [m.group(1).lower() for m in EMAIL_RX.finditer(ln)]
    dom_brands = []
    for d in domain_hits:
        b = _brand_from_domain(d)
        if b:
            dom_brands.append(b)

    # 2) top candidates by layout/appearance
    candidates: List[Tuple[float, str]] = []
    top = lines[:30]
    for i, raw in enumerate(top):
        s = raw.strip()
        if not s or len(s) > 80:
            continue
        if any(ph in s.lower() for ph in IGNORE_PHRASES):
            continue

        caps = _uppercase_ratio(s)
        org = 1.0 if ORG_HINTS.search(s) else 0.0
        near_addr = (
            1.0 if (i + 1 < len(top) and ADDRESS_HINT.search(top[i + 1])) else 0.0
        )
        pos = max(0.0, 1.0 - (i / 30.0))  # earlier lines weigh more
        score = 2.5 * pos + 2.0 * caps + 1.5 * org + 1.0 * near_addr
        candidates.append((score, s))

    for b in dom_brands:
        candidates.append((4.0, b))  # domains get strong prior

    if not candidates:
        return None

    best = max(candidates, key=lambda t: t[0])[1]
    return _clean_vendor_name(best) or None
