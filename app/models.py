from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1


def _lead_id_for(source_id: int | None, message_id: int) -> str:
    source_part = str(source_id) if source_id is not None else "unknown"
    return f"{source_part}:{message_id}"


def _lead_key_for(lead_id: str) -> str:
    return sha1(lead_id.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class LeadEvent:
    source_title: str | None
    source_id: int | None
    message_id: int
    sender_id: int | None
    sender_username: str | None
    sender_first_name: str | None
    text: str
    message_link: str | None
    matched_at: datetime
    lead_id: str = ""
    lead_key: str = ""

    def __post_init__(self) -> None:
        lead_id = self.lead_id or _lead_id_for(self.source_id, self.message_id)
        lead_key = self.lead_key or _lead_key_for(lead_id)
        object.__setattr__(self, "lead_id", lead_id)
        object.__setattr__(self, "lead_key", lead_key)


@dataclass(frozen=True)
class LeadCRMStatus:
    lead_id: str
    lead_key: str
    status: str
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None
    processed_date: str | None = None
    comment: str | None = None
    assigned_to_user_id: int | None = None
    assigned_to_username: str | None = None
