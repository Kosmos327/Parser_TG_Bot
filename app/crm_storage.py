from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import LeadCRMStatus

logger = logging.getLogger(__name__)

VALID_STATUSES = {"new", "in_work", "processed", "no_target"}
_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
COMMENT_LIMIT = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_json(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dt_from_json(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _validate_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid CRM status: {status}")
    return status


def _validate_processed_date(processed_date: str) -> str:
    value = processed_date.strip()
    if not _DATE_RE.match(value):
        raise ValueError("processed_date must be in dd.mm.yyyy format")
    datetime.strptime(value, "%d.%m.%Y")
    return value


def _normalize_comment(comment: str) -> str:
    return comment.strip()[:COMMENT_LIMIT]


def _status_to_dict(status: LeadCRMStatus) -> dict[str, Any]:
    data = asdict(status)
    data["created_at"] = _dt_to_json(status.created_at)
    data["updated_at"] = _dt_to_json(status.updated_at)
    data["processed_at"] = _dt_to_json(status.processed_at)
    return data


def _status_from_dict(data: dict[str, Any]) -> LeadCRMStatus:
    now = _now()
    return LeadCRMStatus(
        lead_id=str(data["lead_id"]),
        lead_key=str(data["lead_key"]),
        status=_validate_status(str(data.get("status") or "new")),
        created_at=_dt_from_json(data.get("created_at")) or now,
        updated_at=_dt_from_json(data.get("updated_at")) or now,
        processed_at=_dt_from_json(data.get("processed_at")),
        processed_date=data.get("processed_date"),
        comment=data.get("comment"),
        assigned_to_user_id=data.get("assigned_to_user_id"),
        assigned_to_username=data.get("assigned_to_username"),
    )


def load_crm(path: str) -> dict[str, LeadCRMStatus]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("CRM file root is not an object")
        crm: dict[str, LeadCRMStatus] = {}
        for lead_id, value in raw.items():
            if not isinstance(value, dict):
                logger.warning("Skipping invalid CRM row for lead %s in %s", lead_id, file_path)
                continue
            status = _status_from_dict(value)
            crm[status.lead_id] = status
        return crm
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        logger.warning("Failed to load CRM file %s: %s. Starting with empty CRM.", file_path, exc)
        return {}


def save_crm(path: str, crm: dict[str, LeadCRMStatus]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    data = {lead_id: _status_to_dict(status) for lead_id, status in crm.items()}
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_or_create_status(path: str, lead_id: str, lead_key: str, created_at: datetime | None = None) -> LeadCRMStatus:
    crm = load_crm(path)
    if lead_id in crm:
        return crm[lead_id]
    now = _now()
    status = LeadCRMStatus(
        lead_id=lead_id,
        lead_key=lead_key,
        status="new",
        created_at=created_at or now,
        updated_at=now,
    )
    crm[lead_id] = status
    save_crm(path, crm)
    return status


def update_status(
    path: str,
    lead_id: str,
    lead_key: str,
    status: str,
    user_id: int | None = None,
    username: str | None = None,
) -> LeadCRMStatus:
    status = _validate_status(status)
    crm = load_crm(path)
    current = crm.get(lead_id) or get_or_create_status(path, lead_id, lead_key)
    now = _now()
    processed_at = current.processed_at
    processed_date = current.processed_date
    if status == "processed":
        processed_at = now
        if not processed_date:
            processed_date = now.strftime("%d.%m.%Y")
    updated = LeadCRMStatus(
        lead_id=lead_id,
        lead_key=lead_key,
        status=status,
        created_at=current.created_at,
        updated_at=now,
        processed_at=processed_at,
        processed_date=processed_date,
        comment=current.comment,
        assigned_to_user_id=user_id if user_id is not None else current.assigned_to_user_id,
        assigned_to_username=username if username is not None else current.assigned_to_username,
    )
    crm[lead_id] = updated
    save_crm(path, crm)
    return updated


def set_processed_date(path: str, lead_id: str, lead_key: str, processed_date: str) -> LeadCRMStatus:
    value = _validate_processed_date(processed_date)
    crm = load_crm(path)
    current = crm.get(lead_id) or get_or_create_status(path, lead_id, lead_key)
    updated = LeadCRMStatus(**{**asdict(current), "processed_date": value, "updated_at": _now()})
    crm[lead_id] = updated
    save_crm(path, crm)
    return updated


def set_comment(path: str, lead_id: str, lead_key: str, comment: str) -> LeadCRMStatus:
    value = _normalize_comment(comment)
    crm = load_crm(path)
    current = crm.get(lead_id) or get_or_create_status(path, lead_id, lead_key)
    updated = LeadCRMStatus(**{**asdict(current), "comment": value, "updated_at": _now()})
    crm[lead_id] = updated
    save_crm(path, crm)
    return updated


def get_stats(path: str) -> dict[str, int]:
    stats = {status: 0 for status in VALID_STATUSES}
    for status in load_crm(path).values():
        stats[status.status] = stats.get(status.status, 0) + 1
    stats["total"] = sum(stats.values())
    return stats


def get_status_by_lead_key(path: str, lead_key: str) -> LeadCRMStatus | None:
    for status in load_crm(path).values():
        if status.lead_key == lead_key:
            return status
    return None


def find_lead_id_by_key(path: str, lead_key: str) -> str | None:
    status = get_status_by_lead_key(path, lead_key)
    return status.lead_id if status else None
