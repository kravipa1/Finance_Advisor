# utils/logging_setup.py
import logging
from typing import Literal

Level = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def setup_logging(level: Level = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
