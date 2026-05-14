from __future__ import annotations

import re
from typing import Any

from app.models import LeadMatchResult

_SPACES_RE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Normalize text for stable phrase matching."""
    if not text:
        return ""

    normalized = text.replace("ё", "е").replace("Ё", "е").lower().strip()
    return _SPACES_RE.sub(" ", normalized)


def _matched_phrases(text: str, phrases: list[str]) -> list[str]:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return []
    matches: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        normalized = normalize_text(phrase)
        if normalized and normalized in normalized_text and normalized not in seen:
            matches.append(str(phrase).strip())
            seen.add(normalized)
    return matches


def contains_any(text: str, phrases: list[str]) -> bool:
    """Return True when normalized text contains at least one normalized phrase."""
    return bool(_matched_phrases(text, phrases))


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


def evaluate_lead_match(text: str | None, source_title: str | None, rules: Any) -> LeadMatchResult:
    """Evaluate message against parser rules and return scoring details."""
    if not text or not text.strip():
        return LeadMatchResult(False, 0, reason="empty_text")

    if len(text.strip()) < rules.min_message_length:
        return LeadMatchResult(False, 0, reason="too_short")

    if not source_title_allowed(source_title, rules.include_source_titles, rules.exclude_source_titles):
        return LeadMatchResult(False, 0, reason="source_filtered")

    exclude_matches = _matched_phrases(text, getattr(rules, "exclude_words", []))
    if exclude_matches:
        return LeadMatchResult(False, 0, negative_phrases=exclude_matches, reason="exclude_keyword")

    strong_words = list(getattr(rules, "strong_trigger_words", []) or [])
    trigger_words = list(getattr(rules, "trigger_words", []) or [])
    weak_words = list(getattr(rules, "weak_trigger_words", []) or [])
    negative_words = list(getattr(rules, "negative_words", []) or [])
    min_score = int(getattr(rules, "min_score", 1))

    strong_matches = _matched_phrases(text, strong_words)
    trigger_matches = _matched_phrases(text, trigger_words)
    weak_matches = _matched_phrases(text, weak_words)
    negative_matches = _matched_phrases(text, negative_words)

    score = len(strong_matches) * 2 + len(trigger_matches) + len(weak_matches) - len(negative_matches) * 3
    matched: list[str] = []
    seen: set[str] = set()
    for phrase in [*strong_matches, *trigger_matches, *weak_matches]:
        key = normalize_text(phrase)
        if key and key not in seen:
            matched.append(phrase)
            seen.add(key)

    if score >= min_score:
        return LeadMatchResult(True, score, matched_phrases=matched, negative_phrases=negative_matches)

    return LeadMatchResult(False, score, matched_phrases=matched, negative_phrases=negative_matches, reason="low_score")


def should_process_message(
    text: str | None,
    source_title: str | None,
    rules: Any,
) -> tuple[bool, str | None]:
    """Return whether a message should be processed by current parser rules."""
    result = evaluate_lead_match(text, source_title, rules)
    return result.matched, result.reason
