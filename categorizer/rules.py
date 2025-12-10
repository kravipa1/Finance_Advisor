# categorizer/rules.py
"""
Enhanced rules engine for transaction categorization.

Features:
- Priority ordering (higher priority rules evaluated first)
- Vendor pattern matching (case-insensitive)
- Line item keyword matching
- Amount conditions (min, max, between)
- Date conditions (weekday, date range)
- Tag accumulation from multiple rules
- Rule name tracking for audit
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from sfa_core.models import Document, Categorization


@dataclass
class Rule:
    """A single categorization rule with conditions and assignments."""

    name: str
    priority: int = 0  # Higher = evaluated first

    # Conditions
    vendor_patterns: List[re.Pattern] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    weekdays: Optional[List[int]] = None  # 0=Monday, 6=Sunday
    date_from: Optional[str] = None  # ISO date
    date_to: Optional[str] = None  # ISO date

    # Assignments
    primary_category: Optional[str] = None
    secondary_category: Optional[str] = None
    confidence: float = 0.5
    tags: List[str] = field(default_factory=list)

    def check_vendor(self, doc: Document) -> bool:
        """Check if vendor matches any pattern."""
        if not self.vendor_patterns:
            return False
        vendor = (doc.vendor or "").upper()
        return any(p.search(vendor) for p in self.vendor_patterns)

    def check_keywords(self, doc: Document) -> bool:
        """Check if any keyword appears in line items."""
        if not self.keywords:
            return False
        text = " ".join([li.description or "" for li in doc.line_items]).lower()
        # Also check vendor and raw text
        text += " " + (doc.vendor or "").lower()
        if doc.raw_ocr_text:
            text += " " + doc.raw_ocr_text.lower()
        return any(k.lower() in text for k in self.keywords)

    def check_amount(self, doc: Document) -> bool:
        """Check if amount is within specified range."""
        if self.amount_min is None and self.amount_max is None:
            return True  # No amount constraint
        amount = doc.total or 0
        if self.amount_min is not None and amount < self.amount_min:
            return False
        if self.amount_max is not None and amount > self.amount_max:
            return False
        return True

    def check_date(self, doc: Document) -> bool:
        """Check if date matches conditions."""
        if not doc.doc_date:
            return True  # No date to check

        # Check weekday
        if self.weekdays is not None:
            if doc.doc_date.weekday() not in self.weekdays:
                return False

        # Check date range
        if self.date_from:
            try:
                from_date = datetime.fromisoformat(self.date_from).date()
                if doc.doc_date < from_date:
                    return False
            except ValueError:
                pass

        if self.date_to:
            try:
                to_date = datetime.fromisoformat(self.date_to).date()
                if doc.doc_date > to_date:
                    return False
            except ValueError:
                pass

        return True

    def applies(self, doc: Document) -> bool:
        """
        Check if this rule applies to the document.

        Logic:
        - If vendor patterns defined, must match at least one
        - If keywords defined, must match at least one
        - Amount conditions are always checked (if defined)
        - Date conditions are always checked (if defined)

        A rule applies if:
        - (vendor matches OR keywords match) AND amount ok AND date ok
        - OR if no vendor/keyword conditions, just amount AND date
        """
        has_content_condition = bool(self.vendor_patterns) or bool(self.keywords)

        if has_content_condition:
            content_match = self.check_vendor(doc) or self.check_keywords(doc)
            if not content_match:
                return False

        if not self.check_amount(doc):
            return False

        if not self.check_date(doc):
            return False

        return True

    def to_categorization(self, doc: Document) -> Tuple[Categorization, str]:
        """Return categorization result and rule name."""
        return (
            Categorization(
                primary_category=self.primary_category,
                secondary_category=self.secondary_category,
                merchant=doc.vendor,
                confidence=self.confidence,
                tags=list(self.tags),
            ),
            self.name,
        )


def parse_rule(r: Dict[str, Any]) -> Rule:
    """Parse a rule from YAML config dict."""
    # Compile vendor patterns
    vendor_patterns = []
    for s in r.get("if_vendor_matches", []):
        # Case-insensitive matching
        pattern = re.compile(re.escape(s.upper()))
        vendor_patterns.append(pattern)

    # Parse amount conditions
    amount_min = None
    amount_max = None
    if "if_amount_gt" in r:
        amount_min = float(r["if_amount_gt"])
    if "if_amount_lt" in r:
        amount_max = float(r["if_amount_lt"])
    if "if_amount_between" in r:
        between = r["if_amount_between"]
        if isinstance(between, (list, tuple)) and len(between) >= 2:
            amount_min = float(between[0])
            amount_max = float(between[1])

    # Parse weekday conditions
    weekdays = None
    if "if_weekday" in r:
        wd = r["if_weekday"]
        if isinstance(wd, list):
            weekdays = [int(d) for d in wd]
        else:
            weekdays = [int(wd)]

    # Get assignments
    assign = r.get("assign", {})

    return Rule(
        name=r.get("name", "unnamed"),
        priority=int(r.get("priority", 0)),
        vendor_patterns=vendor_patterns,
        keywords=r.get("if_lineitem_contains", []),
        amount_min=amount_min,
        amount_max=amount_max,
        weekdays=weekdays,
        date_from=r.get("if_date_from"),
        date_to=r.get("if_date_to"),
        primary_category=assign.get("primary_category"),
        secondary_category=assign.get("secondary_category"),
        confidence=float(assign.get("confidence", 0.5)),
        tags=list(assign.get("tags", [])),
    )


def compile_rules(cfg: Dict[str, Any]) -> List[Rule]:
    """Compile all rules from config, sorted by priority (highest first)."""
    rules = [parse_rule(r) for r in cfg.get("rules", [])]
    # Sort by priority descending
    rules.sort(key=lambda r: r.priority, reverse=True)
    return rules


def apply_rules(doc: Document, cfg: Dict[str, Any]) -> Categorization:
    """
    Apply rules to document and return categorization.
    First matching rule wins (after priority sort).
    """
    result = apply_rules_with_name(doc, cfg)
    return result[0]


def apply_rules_with_name(
    doc: Document, cfg: Dict[str, Any]
) -> Tuple[Categorization, Optional[str]]:
    """
    Apply rules to document and return (categorization, rule_name).
    First matching rule wins (after priority sort).
    """
    rules = compile_rules(cfg)

    for rule in rules:
        if rule.applies(doc):
            cat, name = rule.to_categorization(doc)
            return cat, name

    # Default fallback
    d = cfg.get("defaults", {})
    return (
        Categorization(
            primary_category=d.get("primary_category", "Uncategorized"),
            secondary_category=d.get("secondary_category"),
            merchant=doc.vendor,
            confidence=float(d.get("confidence", 0.1)),
            tags=list(d.get("tags", [])),
        ),
        None,  # No rule matched
    )


def get_all_matching_tags(doc: Document, cfg: Dict[str, Any]) -> List[str]:
    """
    Get tags from ALL matching rules (not just first).
    Useful for accumulating tags like "large-purchase", "review", etc.
    """
    rules = compile_rules(cfg)
    all_tags = []

    for rule in rules:
        if rule.applies(doc):
            all_tags.extend(rule.tags)

    # Deduplicate while preserving order
    seen = set()
    unique_tags = []
    for tag in all_tags:
        if tag not in seen:
            seen.add(tag)
            unique_tags.append(tag)

    return unique_tags
