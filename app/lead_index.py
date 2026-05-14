from __future__ import annotations

from hashlib import sha1

from app.models import LeadEvent


def lead_id_for(source_id: int | None, message_id: int) -> str:
    """Return stable lead id based on source and Telegram message ids."""
    source_part = str(source_id) if source_id is not None else "unknown"
    return f"{source_part}:{message_id}"


def lead_key_for(lead_id: str) -> str:
    """Return short callback-safe stable lead key for a lead id."""
    return sha1(lead_id.encode("utf-8")).hexdigest()[:12]


def ensure_lead_identity(lead: LeadEvent) -> LeadEvent:
    """Return lead with populated lead_id and lead_key without changing other fields."""
    lead_id = lead.lead_id or lead_id_for(lead.source_id, lead.message_id)
    lead_key = lead.lead_key or lead_key_for(lead_id)
    if lead.lead_id == lead_id and lead.lead_key == lead_key:
        return lead
    return LeadEvent(
        source_title=lead.source_title,
        source_id=lead.source_id,
        message_id=lead.message_id,
        sender_id=lead.sender_id,
        sender_username=lead.sender_username,
        sender_first_name=lead.sender_first_name,
        text=lead.text,
        message_link=lead.message_link,
        matched_at=lead.matched_at,
        lead_id=lead_id,
        lead_key=lead_key,
        score=lead.score,
        matched_phrases=list(lead.matched_phrases),
        negative_phrases=list(lead.negative_phrases),
    )
