from __future__ import annotations
import yaml
from pathlib import Path
from typing import Optional
from sfa_core.models import Document, Transaction
from categorizer.rules import apply_rules


class CategorizerService:
    def __init__(self, rules_path: Optional[str] = None):
        self.cfg = {
            "rules": [],
            "defaults": {"primary_category": "Uncategorized", "confidence": 0.1},
        }
        if rules_path:
            with open(Path(rules_path), "r", encoding="utf-8") as f:
                self.cfg = yaml.safe_load(f) or self.cfg

    def categorize(self, doc: Document) -> Transaction:
        cat = apply_rules(doc, self.cfg)
        return Transaction(doc=doc, category=cat)

    # placeholder for future ML mode
    def categorize_ml(self, doc: Document) -> Transaction:
        # TODO: call model.predict(features(doc))
        return self.categorize(doc)
