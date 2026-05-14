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
    crm_file: str
    rules_file: str
    parser_enabled: bool
    admin_ids: list[int]
    dry_run: bool
    min_message_length: int
    ignore_bots: bool
    ignore_forwards: bool
    exclude_keywords: list[str]
    include_source_titles: list[str]
    exclude_source_titles: list[str]
    max_text_length: int
    log_level: str
    source_search_limit: int
    join_batch_limit: int
    join_delay_seconds: int
    exclude_private_chats: bool
    source_candidates_file: str
    source_export_file: str
    leads_page_size: int

    @field_validator(
        "api_hash",
        "session_name",
        "bot_token",
        "dedup_file",
        "leads_file",
        "rules_file",
        "crm_file",
        "source_candidates_file",
        "source_export_file",
    )
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

    @field_validator("source_chats", "exclude_keywords", "include_source_titles", "exclude_source_titles")
    @classmethod
    def _string_lists_clean(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("min_message_length")
    @classmethod
    def _min_message_length_valid(cls, value: int) -> int:
        if value < 0:
            raise ValueError("min_message_length must be greater than or equal to 0")
        return value

    @field_validator("max_text_length")
    @classmethod
    def _max_text_length_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_text_length must be greater than 0")
        return value

    @field_validator("source_search_limit", "join_batch_limit", "join_delay_seconds")
    @classmethod
    def _positive_int_valid(cls, value: int, info: Any) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return value


    @field_validator("leads_page_size")
    @classmethod
    def _leads_page_size_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("leads_page_size must be greater than 0")
        return min(value, 20)

    @field_validator("log_level")
    @classmethod
    def _log_level_valid(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            raise ValueError("log_level must be one of CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET")
        return normalized


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int(value: str | None, default: int, env_name: str) -> int:
    if value is None or not value.strip():
        return default

    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{env_name} contains non-integer value: {value}") from exc


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


def risky_settings_warnings(settings: Settings) -> list[str]:
    """Return non-fatal safety warnings for source join settings."""
    warnings: list[str] = []
    if settings.join_batch_limit > 20:
        warnings.append("JOIN_BATCH_LIMIT больше 20: массовая подписка рискованна и может привести к ограничениям Telegram.")
    if settings.join_delay_seconds < 60:
        warnings.append("JOIN_DELAY_SECONDS меньше 60: слишком частые подписки рискованны и могут вызвать FloodWait.")
    return warnings


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
        "crm_file": _optional_env("CRM_FILE", "data/lead_crm.json"),
        "rules_file": _optional_env("RULES_FILE", "data/parser_rules.json"),
        "parser_enabled": _parse_bool(os.getenv("PARSER_ENABLED"), True),
        "admin_ids": _parse_int_csv(os.getenv("ADMIN_IDS")),
        "dry_run": _parse_bool(os.getenv("DRY_RUN"), False),
        "min_message_length": _parse_int(os.getenv("MIN_MESSAGE_LENGTH"), 10, "MIN_MESSAGE_LENGTH"),
        "ignore_bots": _parse_bool(os.getenv("IGNORE_BOTS"), True),
        "ignore_forwards": _parse_bool(os.getenv("IGNORE_FORWARDS"), False),
        "exclude_keywords": _parse_csv(os.getenv("EXCLUDE_KEYWORDS")),
        "include_source_titles": _parse_csv(os.getenv("INCLUDE_SOURCE_TITLES")),
        "exclude_source_titles": _parse_csv(os.getenv("EXCLUDE_SOURCE_TITLES")),
        "max_text_length": _parse_int(os.getenv("MAX_TEXT_LENGTH"), 3500, "MAX_TEXT_LENGTH"),
        "log_level": _optional_env("LOG_LEVEL", "INFO"),
        "source_search_limit": _parse_int(os.getenv("SOURCE_SEARCH_LIMIT"), 100, "SOURCE_SEARCH_LIMIT"),
        "join_batch_limit": _parse_int(os.getenv("JOIN_BATCH_LIMIT"), 10, "JOIN_BATCH_LIMIT"),
        "join_delay_seconds": _parse_int(os.getenv("JOIN_DELAY_SECONDS"), 90, "JOIN_DELAY_SECONDS"),
        "exclude_private_chats": _parse_bool(os.getenv("EXCLUDE_PRIVATE_CHATS"), True),
        "source_candidates_file": _optional_env("SOURCE_CANDIDATES_FILE", "data/source_candidates.json"),
        "source_export_file": _optional_env("SOURCE_EXPORT_FILE", "data/source_candidates.txt"),
        "leads_page_size": _parse_int(os.getenv("LEADS_PAGE_SIZE"), 10, "LEADS_PAGE_SIZE"),
    }

    try:
        return Settings(**raw_settings)
    except ValidationError as exc:
        raise ValueError(f"Invalid application settings: {exc}") from exc
