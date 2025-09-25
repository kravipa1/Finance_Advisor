from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict


@dataclass
class LineItem:
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None
    # raw extras for debugging
    meta: Dict[str, str] = field(default_factory=dict)


@dataclass
class Document:
    doc_id: str
    source_path: str
    vendor: Optional[str]
    doc_date: Optional[date]
    subtotal: Optional[float]
    tax: Optional[float]
    total: Optional[float]
    currency: Optional[str] = "USD"
    line_items: List[LineItem] = field(default_factory=list)
    # raw debug payloads
    raw_ocr_text: Optional[str] = None
    raw_blocks: Optional[Dict] = None


@dataclass
class Categorization:
    primary_category: Optional[str]
    secondary_category: Optional[str] = None
    merchant: Optional[str] = None
    confidence: float = 0.0
    tags: List[str] = field(default_factory=list)


@dataclass
class Transaction:
    doc: Document
    category: Optional[Categorization] = None
