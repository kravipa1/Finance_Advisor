from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Any
from sfa_core.models import Document, Categorization


@dataclass
class Rule:
    name: str
    vendor_patterns: List[re.Pattern]
    keywords: List[str]
    assign: Dict[str, Any]

    def applies(self, doc: Document) -> bool:
        v = (doc.vendor or "").upper()
        if self.vendor_patterns:
            if any(p.search(v) for p in self.vendor_patterns):
                return True
        if self.keywords:
            text = " ".join([li.description for li in doc.line_items]).lower()
            if any(k.lower() in text for k in self.keywords):
                return True
        return False


def compile_rules(cfg: Dict[str, Any]) -> List[Rule]:
    out = []
    for r in cfg.get("rules", []):
        pats = [
            re.compile(re.escape(s.upper())) for s in r.get("if_vendor_matches", [])
        ]
        kws = r.get("if_lineitem_contains", [])
        out.append(
            Rule(
                name=r.get("name", "unnamed"),
                vendor_patterns=pats,
                keywords=kws,
                assign=r.get("assign", {}),
            )
        )
    return out


def apply_rules(doc: Document, cfg: Dict[str, Any]) -> Categorization:
    rules = compile_rules(cfg)
    for rule in rules:
        if rule.applies(doc):
            a = rule.assign
            return Categorization(
                primary_category=a.get("primary_category"),
                secondary_category=a.get("secondary_category"),
                merchant=doc.vendor,
                confidence=float(a.get("confidence", 0.5)),
                tags=list(a.get("tags", [])),
            )
    # default
    d = cfg.get("defaults", {})
    return Categorization(
        primary_category=d.get("primary_category"),
        secondary_category=d.get("secondary_category"),
        merchant=doc.vendor,
        confidence=float(d.get("confidence", 0.1)),
        tags=list(d.get("tags", [])),
    )
