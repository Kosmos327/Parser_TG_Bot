from __future__ import annotations

import re
from typing import Any

_SPACES_RE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Normalize text for stable phrase matching."""
    if not text:
        return ""

    normalized = text.replace("ё", "е").replace("Ё", "е").lower().strip()
    return _SPACES_RE.sub(" ", normalized)


def contains_any(text: str, phrases: list[str]) -> bool:
    """Return True when normalized text contains at least one normalized phrase."""
    normalized_text = normalize_text(text)
    if not normalized_text:
        return False

    normalized_phrases = [normalize_text(phrase) for phrase in phrases]
    return any(phrase in normalized_text for phrase in normalized_phrases if phrase)


def source_title_allowed(
    source_title: str | None,
    include_titles: list[str],
    exclude_titles: list[str],
) -> bool:
    """Return whether a source title passes include/exclude title filters."""
    normalized_title = normalize_text(source_title)
    normalized_include = [normalize_text(title) for title in include_titles if normalize_text(title)]
    normalized_exclude = [normalize_text(title) for title in exclude_titles if normalize_text(title)]

    if normalized_exclude and any(title in normalized_title for title in normalized_exclude):
        return False

    if normalized_include:
        return any(title in normalized_title for title in normalized_include)

    return True


def message_matches(text: str, keywords: list[str]) -> bool:
    """Return True when message text contains at least one keyword phrase."""
    return contains_any(text, keywords)


def should_process_message(
    text: str | None,
    source_title: str | None,
    settings: Any,
) -> tuple[bool, str | None]:
    """Return whether a message should be processed and a skip reason if not."""
    if not text or not text.strip():
        return False, "empty_text"

    if len(text.strip()) < settings.min_message_length:
        return False, "too_short"

    if not source_title_allowed(source_title, settings.include_source_titles, settings.exclude_source_titles):
        return False, "source_filtered"

    if contains_any(text, settings.exclude_keywords):
        return False, "exclude_keyword"

    if not contains_any(text, settings.keywords):
        return False, "no_keyword"

    return True, None
