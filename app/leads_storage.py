from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import LeadEvent

logger = logging.getLogger(__name__)


def _datetime_to_json(value: datetime) -> str:
    return value.isoformat()


def _datetime_from_json(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lead_to_dict(lead: LeadEvent) -> dict[str, Any]:
    data = asdict(lead)
    data["matched_at"] = _datetime_to_json(lead.matched_at)
    return data


def _lead_from_dict(data: dict[str, Any]) -> LeadEvent:
    return LeadEvent(
        source_title=data.get("source_title"),
        source_id=data.get("source_id"),
        message_id=int(data["message_id"]),
        sender_id=data.get("sender_id"),
        sender_username=data.get("sender_username"),
        sender_first_name=data.get("sender_first_name"),
        text=str(data.get("text") or ""),
        message_link=data.get("message_link"),
        matched_at=_datetime_from_json(str(data["matched_at"])),
    )


def append_lead(path: str, lead: LeadEvent) -> None:
    """Append a lead event to a JSONL file, creating parent directories if needed."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("a", encoding="utf-8") as file:
        json.dump(_lead_to_dict(lead), file, ensure_ascii=False)
        file.write("\n")


def get_last_leads(path: str, limit: int = 10) -> list[LeadEvent]:
    """Return the latest leads from a JSONL file in newest-first order."""
    if limit <= 0:
        return []

    file_path = Path(path)
    if not file_path.exists():
        return []

    leads: list[LeadEvent] = []
    with file_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
                if not isinstance(raw, dict):
                    raise ValueError("JSONL line is not an object")
                leads.append(_lead_from_dict(raw))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping invalid lead in %s at line %s: %s", file_path, line_number, exc)

    return leads[-limit:][::-1]


def count_leads(path: str) -> int:
    """Count valid lead events in a JSONL file."""
    file_path = Path(path)
    if not file_path.exists():
        return 0

    count = 0
    with file_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
                if not isinstance(raw, dict):
                    raise ValueError("JSONL line is not an object")
                _lead_from_dict(raw)
                count += 1
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping invalid lead in %s at line %s: %s", file_path, line_number, exc)

    return count
