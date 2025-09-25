from abc import ABC, abstractmethod
from sfa_core.models import Document


class BaseAdapter(ABC):
    """Turn raw OCR/parsed output into a normalized Document."""

    @abstractmethod
    def build(
        self,
        *,
        source_path: str,
        ocr_text: str | None = None,
        parsed: dict | None = None,
    ) -> Document: ...
