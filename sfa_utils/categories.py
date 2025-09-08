# sfa_utils/categories.py
# Minimal taxonomy to start; easy to extend later.
# Optional tiny vendor map (for backward-compat with tests). Pipeline
# works without it; when unknown, we'll fall back to item-majority.

VENDOR_TO_CATEGORY = {
    "uber": "Transport",
    "lyft": "Transport",
    "zomato": "Food",
    "doordash": "Food",
    "instacart": "Groceries",
    "walmart": "Groceries",
    "amazon": "Shopping",
    "target": "Shopping",
    "starbucks": "Coffee",
    # add or remove freely — not required for generalization
}

# Item-description keywords → category.
# Start small; we’ll swap this for a learned model later.
KEYWORD_TO_CATEGORY = {
    "service fee": "Fees",
    "delivery": "Delivery",
    "tip": "Tips",
    "tax": "Taxes",
    # groceries-ish
    "produce": "Groceries",
    "deli": "Groceries",
    "bakery": "Groceries",
    "milk": "Groceries",
    "banana": "Groceries",
    "cucumber": "Groceries",
    "chicken": "Groceries",
    # coffee-ish
    "coffee": "Coffee",
}
