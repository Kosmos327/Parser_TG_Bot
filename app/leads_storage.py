from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.crm_storage import load_crm
from app.filters import normalize_text
from app.lead_index import ensure_lead_identity
from app.models import LeadEvent

logger = logging.getLogger(__name__)


def _datetime_to_json(value: datetime) -> str:
    return value.isoformat()


def _datetime_from_json(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lead_to_dict(lead: LeadEvent) -> dict[str, Any]:
    lead = ensure_lead_identity(lead)
    data = asdict(lead)
    data["matched_at"] = _datetime_to_json(lead.matched_at)
    return data


def _lead_from_dict(data: dict[str, Any]) -> LeadEvent:
    return ensure_lead_identity(
        LeadEvent(
            source_title=data.get("source_title"),
            source_id=data.get("source_id"),
            message_id=int(data["message_id"]),
            sender_id=data.get("sender_id"),
            sender_username=data.get("sender_username"),
            sender_first_name=data.get("sender_first_name"),
            text=str(data.get("text") or ""),
            message_link=data.get("message_link"),
            matched_at=_datetime_from_json(str(data["matched_at"])),
            lead_id=str(data.get("lead_id") or ""),
            lead_key=str(data.get("lead_key") or ""),
            score=data.get("score"),
            matched_phrases=list(data.get("matched_phrases") or []),
            negative_phrases=list(data.get("negative_phrases") or []),
        )
    )


def _iter_leads(path: str) -> list[LeadEvent]:
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
    return leads


def append_lead(path: str, lead: LeadEvent) -> None:
    """Append a lead event to a JSONL file, creating parent directories if needed."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("a", encoding="utf-8") as file:
        json.dump(_lead_to_dict(lead), file, ensure_ascii=False)
        file.write("\n")


def get_all_leads(path: str) -> list[LeadEvent]:
    """Return all valid leads in newest-first order."""
    return _iter_leads(path)[::-1]


def get_last_leads(path: str, limit: int = 10) -> list[LeadEvent]:
    """Return the latest leads from a JSONL file in newest-first order."""
    if limit <= 0:
        return []
    return _iter_leads(path)[-limit:][::-1]


def count_leads(path: str) -> int:
    """Count valid lead events in a JSONL file."""
    return len(_iter_leads(path))


def get_lead_by_id(path: str, lead_id: str) -> LeadEvent | None:
    for lead in _iter_leads(path):
        if lead.lead_id == lead_id:
            return lead
    return None


def get_lead_by_key(path: str, lead_key: str) -> LeadEvent | None:
    for lead in _iter_leads(path):
        if lead.lead_key == lead_key:
            return lead
    return None


def _page_items(items: list[LeadEvent], page: int, page_size: int) -> tuple[list[LeadEvent], int]:
    page_size = max(1, page_size)
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    return items[start : start + page_size], total_pages


def get_leads_page(path: str, page: int, page_size: int = 10) -> tuple[list[LeadEvent], int]:
    return _page_items(get_all_leads(path), page, page_size)


def _lead_search_haystack(lead: LeadEvent, comment: str | None) -> str:
    values = [
        lead.text,
        lead.sender_username,
        lead.sender_first_name,
        str(lead.sender_id) if lead.sender_id is not None else None,
        lead.source_title,
        lead.message_link,
        lead.lead_id,
        lead.lead_key,
        comment,
    ]
    return normalize_text(" ".join(str(value) for value in values if value not in (None, "")))


def search_leads(
    path: str,
    crm_path: str,
    query: str,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[LeadEvent], int]:
    normalized_query = normalize_text(query)
    if not normalized_query:
        return [], 1
    crm = load_crm(crm_path)
    matches = [
        lead
        for lead in get_all_leads(path)
        if normalized_query in _lead_search_haystack(lead, crm.get(lead.lead_id).comment if crm.get(lead.lead_id) else None)
    ]
    return _page_items(matches, page, page_size)
