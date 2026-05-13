from __future__ import annotations


def message_matches(text: str, keywords: list[str]) -> bool:
    """Return True when message text contains at least one keyword phrase."""
    normalized_text = (text or "").strip().lower()
    if not normalized_text:
        return False

    return any(keyword.strip().lower() in normalized_text for keyword in keywords if keyword.strip())
