from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha1

from app.leads_storage import get_all_leads

_SPACES_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+|t\.me/\S+", re.IGNORECASE)


def normalize_lead_text(text: str) -> str:
    normalized = _URL_RE.sub(" ", text.replace("ё", "е").replace("Ё", "е").lower())
    normalized = re.sub(r"[^0-9a-zа-я_@\s]+", " ", normalized)
    return _SPACES_RE.sub(" ", normalized).strip()


def _sender_key(sender_username: str | None, sender_id: int | None) -> str:
    if sender_id is not None:
        return f"id:{sender_id}"
    if sender_username:
        return f"u:{sender_username.lstrip('@').casefold()}"
    return "unknown"


def lead_fingerprint(text: str, sender_username: str | None, sender_id: int | None) -> str:
    payload = f"{_sender_key(sender_username, sender_id)}|{normalize_lead_text(text)}"
    return sha1(payload.encode("utf-8")).hexdigest()


def _is_recent(matched_at: datetime, cutoff: datetime) -> bool:
    if matched_at.tzinfo is None:
        matched_at = matched_at.replace(tzinfo=timezone.utc)
    return matched_at >= cutoff


def is_duplicate_lead(
    leads_file: str,
    text: str,
    sender_username: str | None,
    sender_id: int | None,
    window_hours: int,
    threshold: float,
) -> tuple[bool, str | None]:
    normalized_text = normalize_lead_text(text)
    if not normalized_text:
        return False, None

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
    sender = _sender_key(sender_username, sender_id)
    sender_known = sender != "unknown"

    for lead in get_all_leads(leads_file):
        if not _is_recent(lead.matched_at, cutoff):
            continue
        existing_text = normalize_lead_text(lead.text)
        if not existing_text:
            continue
        existing_sender = _sender_key(lead.sender_username, lead.sender_id)
        if sender_known and existing_sender != sender:
            continue
        ratio = SequenceMatcher(None, normalized_text, existing_text).ratio()
        if ratio >= threshold:
            return True, lead.lead_id
    return False, None
