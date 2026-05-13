from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError, field_validator


class Settings(BaseModel):
    api_id: int
    api_hash: str
    session_name: str
    bot_token: str
    admin_chat_id: int
    source_chats: list[str]
    keywords: list[str]
    dedup_file: str
    leads_file: str
    parser_enabled: bool
    admin_ids: list[int]

    @field_validator("api_hash", "session_name", "bot_token", "dedup_file", "leads_file")
    @classmethod
    def _not_empty(cls, value: str, info: Any) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("keywords")
    @classmethod
    def _keywords_not_empty(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("keywords must contain at least one phrase")
        return cleaned

    @field_validator("source_chats")
    @classmethod
    def _source_chats_clean(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int_csv(value: str | None) -> list[int]:
    ids: list[int] = []
    for item in _parse_csv(value):
        try:
            ids.append(int(item))
        except ValueError as exc:
            raise ValueError(f"ADMIN_IDS contains non-integer value: {item}") from exc
    return ids


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default

    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False

    raise ValueError(f"Invalid boolean value: {value}")


def _optional_env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable {name} is not set or empty")
    return value


def load_settings() -> Settings:
    """Load application settings from .env and validate them."""
    load_dotenv()

    raw_settings = {
        "api_id": _require_env("API_ID"),
        "api_hash": _require_env("API_HASH"),
        "session_name": _require_env("SESSION_NAME"),
        "bot_token": _require_env("BOT_TOKEN"),
        "admin_chat_id": _require_env("ADMIN_CHAT_ID"),
        "source_chats": _parse_csv(os.getenv("SOURCE_CHATS")),
        "keywords": _parse_csv(os.getenv("KEYWORDS")),
        "dedup_file": _require_env("DEDUP_FILE"),
        "leads_file": _optional_env("LEADS_FILE", "data/leads.jsonl"),
        "parser_enabled": _parse_bool(os.getenv("PARSER_ENABLED"), True),
        "admin_ids": _parse_int_csv(os.getenv("ADMIN_IDS")),
    }

    try:
        return Settings(**raw_settings)
    except ValidationError as exc:
        raise ValueError(f"Invalid application settings: {exc}") from exc
