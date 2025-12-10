# categorizer/service.py
"""
Categorizer service for applying rules to documents.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Optional, Tuple

from sfa_core.models import Document, Transaction, Categorization
from categorizer.rules import apply_rules, apply_rules_with_name, get_all_matching_tags


class CategorizerService:
    """Service for categorizing documents using rule-based matching."""

    def __init__(self, rules_path: Optional[str] = None):
        self.cfg = {
            "rules": [],
            "defaults": {"primary_category": "Uncategorized", "confidence": 0.1},
        }
        if rules_path:
            p = Path(rules_path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    self.cfg = yaml.safe_load(f) or self.cfg

    def categorize(self, doc: Document) -> Transaction:
        """Apply rules and return Transaction with categorization."""
        cat = apply_rules(doc, self.cfg)
        return Transaction(doc=doc, category=cat)

    def categorize_with_rule(self, doc: Document) -> Tuple[Transaction, Optional[str]]:
        """
        Apply rules and return (Transaction, rule_name).
        rule_name is None if no rule matched (defaults used).
        """
        cat, rule_name = apply_rules_with_name(doc, self.cfg)

        # Optionally accumulate tags from all matching rules
        all_tags = get_all_matching_tags(doc, self.cfg)
        if all_tags:
            # Merge tags: rule's tags first, then additional from other rules
            merged_tags = list(cat.tags)
            for tag in all_tags:
                if tag not in merged_tags:
                    merged_tags.append(tag)
            cat = Categorization(
                primary_category=cat.primary_category,
                secondary_category=cat.secondary_category,
                merchant=cat.merchant,
                confidence=cat.confidence,
                tags=merged_tags,
            )

        return Transaction(doc=doc, category=cat), rule_name

    def categorize_ml(self, doc: Document) -> Transaction:
        """Placeholder for future ML-based categorization."""
        # TODO: call model.predict(features(doc))
        return self.categorize(doc)

    def get_rule_count(self) -> int:
        """Return number of rules configured."""
        return len(self.cfg.get("rules", []))
