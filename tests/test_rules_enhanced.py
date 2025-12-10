# tests/test_rules_enhanced.py
"""
Tests for enhanced rules engine with priority, amount/date conditions.
"""
from datetime import date

from categorizer.rules import (
    apply_rules,
    apply_rules_with_name,
    get_all_matching_tags,
)
from categorizer.service import CategorizerService
from sfa_core.models import Document, LineItem


def make_doc(
    vendor: str = "Test Vendor",
    total: float = 10.0,
    doc_date: date = None,
    line_items: list = None,
    raw_text: str = None,
) -> Document:
    """Helper to create test documents."""
    return Document(
        doc_id="test123",
        source_path="/test/path.txt",
        vendor=vendor,
        doc_date=doc_date,
        subtotal=total * 0.9,
        tax=total * 0.1,
        total=total,
        line_items=line_items or [],
        raw_ocr_text=raw_text,
    )


class TestPriorityOrdering:
    """Tests for rule priority ordering."""

    def test_higher_priority_wins(self):
        """Higher priority rule should match first."""
        cfg = {
            "rules": [
                {
                    "name": "low_priority",
                    "priority": 10,
                    "if_vendor_matches": ["COFFEE"],
                    "assign": {"primary_category": "Generic", "confidence": 0.5},
                },
                {
                    "name": "high_priority",
                    "priority": 100,
                    "if_vendor_matches": ["COFFEE"],
                    "assign": {"primary_category": "Specific", "confidence": 0.9},
                },
            ],
            "defaults": {"primary_category": "Uncategorized"},
        }

        doc = make_doc(vendor="Coffee Shop")
        cat, rule_name = apply_rules_with_name(doc, cfg)

        assert cat.primary_category == "Specific"
        assert rule_name == "high_priority"
        assert cat.confidence == 0.9

    def test_same_priority_uses_order(self):
        """Same priority should use config order."""
        cfg = {
            "rules": [
                {
                    "name": "first",
                    "priority": 50,
                    "if_vendor_matches": ["COFFEE"],
                    "assign": {"primary_category": "First"},
                },
                {
                    "name": "second",
                    "priority": 50,
                    "if_vendor_matches": ["COFFEE"],
                    "assign": {"primary_category": "Second"},
                },
            ],
            "defaults": {"primary_category": "Uncategorized"},
        }

        doc = make_doc(vendor="Coffee Shop")
        cat, rule_name = apply_rules_with_name(doc, cfg)

        # First rule in config wins when priority is equal
        assert rule_name == "first"


class TestAmountConditions:
    """Tests for amount-based conditions."""

    def test_amount_gt(self):
        """Test if_amount_gt condition."""
        cfg = {
            "rules": [
                {
                    "name": "large_purchase",
                    "if_amount_gt": 100,
                    "if_vendor_matches": ["STORE"],
                    "assign": {"primary_category": "Large", "tags": ["large"]},
                },
            ],
            "defaults": {"primary_category": "Normal"},
        }

        # Under threshold - should not match
        doc = make_doc(vendor="Store", total=50)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Normal"

        # Over threshold - should match
        doc = make_doc(vendor="Store", total=150)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Large"
        assert "large" in cat.tags

    def test_amount_lt(self):
        """Test if_amount_lt condition."""
        cfg = {
            "rules": [
                {
                    "name": "small_purchase",
                    "if_amount_lt": 10,
                    "if_vendor_matches": ["STORE"],
                    "assign": {"primary_category": "Small"},
                },
            ],
            "defaults": {"primary_category": "Normal"},
        }

        # Over threshold - should not match
        doc = make_doc(vendor="Store", total=15)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Normal"

        # Under threshold - should match
        doc = make_doc(vendor="Store", total=5)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Small"

    def test_amount_between(self):
        """Test if_amount_between condition."""
        cfg = {
            "rules": [
                {
                    "name": "gas_purchase",
                    "if_amount_between": [20, 100],
                    "if_vendor_matches": ["SHELL"],
                    "assign": {"primary_category": "Gas"},
                },
            ],
            "defaults": {"primary_category": "Other"},
        }

        # Under range
        doc = make_doc(vendor="Shell", total=10)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Other"

        # In range
        doc = make_doc(vendor="Shell", total=50)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Gas"

        # Over range
        doc = make_doc(vendor="Shell", total=150)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Other"


class TestDateConditions:
    """Tests for date-based conditions."""

    def test_weekday_condition(self):
        """Test if_weekday condition (0=Monday, 6=Sunday)."""
        cfg = {
            "rules": [
                {
                    "name": "weekend_purchase",
                    "if_weekday": [5, 6],  # Saturday, Sunday
                    "if_vendor_matches": ["STORE"],
                    "assign": {"primary_category": "Weekend", "tags": ["weekend"]},
                },
            ],
            "defaults": {"primary_category": "Weekday"},
        }

        # Monday (0)
        doc = make_doc(vendor="Store", doc_date=date(2024, 1, 15))  # Monday
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Weekday"

        # Saturday (5)
        doc = make_doc(vendor="Store", doc_date=date(2024, 1, 20))  # Saturday
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Weekend"
        assert "weekend" in cat.tags

    def test_date_range(self):
        """Test if_date_from and if_date_to conditions."""
        cfg = {
            "rules": [
                {
                    "name": "holiday_purchase",
                    "if_date_from": "2024-12-20",
                    "if_date_to": "2024-12-31",
                    "if_vendor_matches": ["STORE"],
                    "assign": {"primary_category": "Holiday", "tags": ["holiday"]},
                },
            ],
            "defaults": {"primary_category": "Regular"},
        }

        # Before range
        doc = make_doc(vendor="Store", doc_date=date(2024, 12, 15))
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Regular"

        # In range
        doc = make_doc(vendor="Store", doc_date=date(2024, 12, 25))
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Holiday"

        # After range
        doc = make_doc(vendor="Store", doc_date=date(2025, 1, 5))
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Regular"


class TestKeywordMatching:
    """Tests for keyword matching in line items and raw text."""

    def test_keyword_in_line_items(self):
        """Test matching keywords in line item descriptions."""
        cfg = {
            "rules": [
                {
                    "name": "coffee_keywords",
                    "if_lineitem_contains": ["latte", "espresso"],
                    "assign": {"primary_category": "Coffee"},
                },
            ],
            "defaults": {"primary_category": "Other"},
        }

        items = [LineItem(description="Caramel Latte", total=5.0)]
        doc = make_doc(line_items=items)
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Coffee"

    def test_keyword_in_raw_text(self):
        """Test matching keywords in raw OCR text."""
        cfg = {
            "rules": [
                {
                    "name": "grocery_keywords",
                    "if_lineitem_contains": ["milk", "bread"],
                    "assign": {"primary_category": "Groceries"},
                },
            ],
            "defaults": {"primary_category": "Other"},
        }

        doc = make_doc(raw_text="SAFEWAY\nMilk 2% $3.99\nBread $2.49")
        cat = apply_rules(doc, cfg)
        assert cat.primary_category == "Groceries"


class TestTagAccumulation:
    """Tests for collecting tags from multiple matching rules."""

    def test_get_all_matching_tags(self):
        """Test accumulating tags from multiple rules."""
        cfg = {
            "rules": [
                {
                    "name": "coffee",
                    "priority": 100,
                    "if_vendor_matches": ["STARBUCKS"],
                    "assign": {
                        "primary_category": "Coffee",
                        "tags": ["coffee", "beverage"],
                    },
                },
                {
                    "name": "large",
                    "priority": 50,
                    "if_amount_gt": 20,
                    "if_vendor_matches": ["STARBUCKS"],
                    "assign": {"primary_category": "Large", "tags": ["large-order"]},
                },
            ],
            "defaults": {},
        }

        doc = make_doc(vendor="Starbucks", total=25)
        all_tags = get_all_matching_tags(doc, cfg)

        assert "coffee" in all_tags
        assert "beverage" in all_tags
        assert "large-order" in all_tags


class TestRuleNameTracking:
    """Tests for rule name tracking."""

    def test_rule_name_returned(self):
        """Test that rule name is returned with categorization."""
        cfg = {
            "rules": [
                {
                    "name": "my_custom_rule",
                    "if_vendor_matches": ["TEST"],
                    "assign": {"primary_category": "Test"},
                },
            ],
            "defaults": {"primary_category": "Default"},
        }

        doc = make_doc(vendor="Test Vendor")
        cat, rule_name = apply_rules_with_name(doc, cfg)

        assert rule_name == "my_custom_rule"

    def test_no_rule_name_for_defaults(self):
        """Test that rule_name is None when defaults are used."""
        cfg = {
            "rules": [
                {
                    "name": "no_match",
                    "if_vendor_matches": ["NOMATCH"],
                    "assign": {"primary_category": "NoMatch"},
                },
            ],
            "defaults": {"primary_category": "Default"},
        }

        doc = make_doc(vendor="Other")
        cat, rule_name = apply_rules_with_name(doc, cfg)

        assert cat.primary_category == "Default"
        assert rule_name is None


class TestCategorizerService:
    """Tests for CategorizerService with enhanced rules."""

    def test_categorize_with_rule(self):
        """Test categorize_with_rule returns transaction and rule name."""
        import tempfile
        import os

        # Create temp rules file
        rules_content = """
rules:
  - name: "test_rule"
    if_vendor_matches: ["TESTCO"]
    assign:
      primary_category: "TestCategory"
      confidence: 0.85
defaults:
  primary_category: "Uncategorized"
"""
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, rules_content.encode())
            os.close(fd)

            svc = CategorizerService(rules_path=path)
            doc = make_doc(vendor="TestCo Store")

            txn, rule_name = svc.categorize_with_rule(doc)

            assert txn.category.primary_category == "TestCategory"
            assert txn.category.confidence == 0.85
            assert rule_name == "test_rule"
        finally:
            os.unlink(path)

    def test_get_rule_count(self):
        """Test get_rule_count method."""
        import tempfile
        import os

        rules_content = """
rules:
  - name: "rule1"
    if_vendor_matches: ["A"]
    assign:
      primary_category: "Cat1"
  - name: "rule2"
    if_vendor_matches: ["B"]
    assign:
      primary_category: "Cat2"
defaults:
  primary_category: "Uncategorized"
"""
        fd, path = tempfile.mkstemp(suffix=".yaml")
        try:
            os.write(fd, rules_content.encode())
            os.close(fd)

            svc = CategorizerService(rules_path=path)
            assert svc.get_rule_count() == 2
        finally:
            os.unlink(path)
