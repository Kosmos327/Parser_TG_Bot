from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from telethon import functions, utils

from app.dialogs import is_private_user_entity, normalize_username, source_chats_value

_TME_RE = re.compile(r"^(?:https?://)?(?:www\.)?t\.me/", re.IGNORECASE)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def _public_username(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("@"):
        text = text[1:]
    if not _USERNAME_RE.fullmatch(text):
        return None
    return f"@{text}"


def _candidate_from_entity(entity: Any, query: str) -> dict[str, Any] | None:
    if is_private_user_entity(entity):
        return None

    username = normalize_username(getattr(entity, "username", None))
    entity_id = getattr(entity, "id", None)
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or "без названия"
    participants_count = getattr(entity, "participants_count", None)

    return {
        "title": str(title),
        "username": username[1:] if username else None,
        "id": entity_id,
        "type": type(entity).__name__,
        "participants_count": participants_count,
        "source_chats_value": source_chats_value(username, utils.get_peer_id(entity) if entity_id is not None else None),
        "query": query,
        "joined": False,
        "skipped": False,
        "manual_required": False,
        "error": None,
    }


async def search_sources(client: Any, queries: list[str], limit: int) -> list[dict[str, Any]]:
    """Search public Telegram sources with Telethon and return serializable candidates."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_query_limit = max(1, limit)

    for raw_query in queries:
        query = raw_query.strip()
        if not query:
            continue
        result = await client(functions.contacts.SearchRequest(q=query, limit=per_query_limit))
        for entity in list(getattr(result, "chats", [])) + list(getattr(result, "users", [])):
            candidate = _candidate_from_entity(entity, query)
            if candidate is None:
                continue
            key = candidate.get("source_chats_value") or str(candidate.get("id"))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

    return candidates


def export_candidates_txt(candidates: list[dict[str, Any]], path: str) -> str:
    """Write public @username candidates to a plain-text file, one source per line."""
    usernames: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        username = _public_username(candidate.get("username"))
        if not username or username in seen:
            continue
        seen.add(username)
        usernames.append(username)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(usernames) + ("\n" if usernames else ""), encoding="utf-8")
    return str(output_path)


def parse_sources_text(text: str) -> list[str]:
    """Normalize user-provided Telegram usernames/links to @username values."""
    values: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        value = line.strip().strip(",;")
        if not value:
            continue
        value = _TME_RE.sub("", value).split("?", 1)[0].strip("/")
        if value.startswith("+") or value.startswith("joinchat/") or value.startswith("c/"):
            continue
        if value.startswith("@"):
            value = value[1:]
        if not _USERNAME_RE.fullmatch(value):
            continue
        normalized = f"@{value}"
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(normalized)
    return values


def filter_joinable_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return candidates safe to feed into the limited public-username join flow."""
    joinable: list[dict[str, Any]] = []
    for candidate in candidates:
        username = _public_username(candidate.get("source_chats_value")) or _public_username(candidate.get("username"))
        if not username:
            continue
        if candidate.get("joined") or candidate.get("skipped") or candidate.get("manual_required") or candidate.get("error"):
            continue
        joinable.append(candidate)
    return joinable


def load_candidates(path: str) -> list[dict[str, Any]]:
    candidate_path = Path(path)
    if not candidate_path.exists():
        return []
    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def save_candidates(candidates: list[dict[str, Any]], path: str) -> str:
    candidate_path = Path(path)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(candidate_path)


def merge_candidates(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(existing)
    seen = {str(item.get("source_chats_value") or item.get("id")) for item in existing}
    for candidate in new:
        key = str(candidate.get("source_chats_value") or candidate.get("id"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(candidate)
    return merged


def mark_candidate_status(path: str, source_value: str, status: str, error: str | None = None) -> None:
    """Update a candidate status flag in the JSON candidates file."""
    candidates = load_candidates(path)
    normalized = normalize_username(source_value) or source_value
    for candidate in candidates:
        values = {
            str(candidate.get("source_chats_value")),
            normalize_username(candidate.get("username")) or "",
            str(candidate.get("id")),
        }
        if normalized not in values and source_value not in values:
            continue
        if status in {"joined", "skipped", "manual_required"}:
            candidate[status] = True
        if status == "failed":
            candidate["error"] = error or "failed"
        elif error is not None:
            candidate["error"] = error
        break
    save_candidates(candidates, path)
