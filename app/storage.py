from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_processed(path: str) -> set[str]:
    """Load processed message keys from a JSON file."""
    file_path = Path(path)
    if not file_path.exists():
        return set()

    try:
        with file_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        logger.error(
            "Deduplication file %s contains invalid JSON: %s. Starting with an empty set.",
            file_path,
            exc,
        )
        return set()

    if not isinstance(data, list):
        logger.error(
            "Deduplication file %s must contain a JSON array. Starting with an empty set.",
            file_path,
        )
        return set()

    return {str(item) for item in data}


def save_processed(path: str, processed: set[str]) -> None:
    """Persist processed message keys to a JSON file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("w", encoding="utf-8") as file:
        json.dump(sorted(processed), file, ensure_ascii=False, indent=2)
