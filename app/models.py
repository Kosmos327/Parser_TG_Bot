from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
