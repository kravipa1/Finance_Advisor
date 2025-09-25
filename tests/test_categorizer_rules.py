from sfa_core.models import Document, LineItem
from categorizer.service import CategorizerService

import os
import tempfile
import yaml


def test_rules_match_vendor():
    cfg = {
        "rules": [
            {
                "name": "coffee",
                "if_vendor_matches": ["STARBUCKS"],
                "assign": {"primary_category": "Food & Drink", "confidence": 0.9},
            }
        ],
        "defaults": {"primary_category": "Uncategorized", "confidence": 0.1},
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml") as f:
        yaml.safe_dump(cfg, f)
        path = f.name
    try:
        svc = CategorizerService(rules_path=path)
        doc = Document(
            doc_id="x",
            source_path="x",
            vendor="Starbucks",
            doc_date=None,
            subtotal=None,
            tax=None,
            total=7.89,
            line_items=[LineItem(description="Latte")],
        )
        txn = svc.categorize(doc)
        assert txn.category.primary_category == "Food & Drink"
        assert txn.category.confidence > 0.5
    finally:
        os.remove(path)
