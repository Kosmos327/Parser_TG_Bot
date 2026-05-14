from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

SOURCE_TYPE_LABELS = {
    "public_channel": "публичный канал",
    "public_group": "публичная группа",
    "group_chat": "групповой чат",
    "supergroup": "супергруппа",
    "private_chat": "личный чат",
    "unknown": "неизвестный тип",
}


def source_type_label(source_type: str) -> str:
    return SOURCE_TYPE_LABELS.get(source_type, SOURCE_TYPE_LABELS["unknown"])


@dataclass(frozen=True)
class DialogInfo:
    """Safe display information for a Telethon dialog entity."""

    title: str
    entity_type: str
    source_type: str
    source_type_label: str
    username: str | None
    entity_id: int | None
    source_chats_value: str
    access_hash: int | None = None


def normalize_username(username: str | None) -> str | None:
    """Return a username in @username form, or None when it is missing."""
    if not username:
        return None

    cleaned = username.strip()
    if not cleaned:
        return None
    return cleaned if cleaned.startswith("@") else f"@{cleaned}"


def source_chats_value(username: str | None, entity_id: int | None) -> str:
    """Return the value recommended for SOURCE_CHATS.

    Public usernames are preferred because they are stable and readable. When a
    username is unavailable, the numeric Telegram peer id is used as a fallback.
    """
    normalized_username = normalize_username(username)
    if normalized_username:
        return normalized_username
    if entity_id is None:
        return "нет"
    return str(entity_id)


def is_private_user_entity(entity: Any) -> bool:
    """Return True for Telethon User/private-dialog-like entities."""
    if entity is None:
        return False
    if type(entity).__name__ == "User":
        return True
    return bool(getattr(entity, "first_name", None) and not getattr(entity, "title", None))


def detect_source_type(entity_or_dialog: Any) -> str:
    """Detect the user-facing Telegram source type for a Telethon entity/dialog."""
    if entity_or_dialog is None:
        return "unknown"

    if getattr(entity_or_dialog, "is_user", False):
        return "private_chat"

    entity = getattr(entity_or_dialog, "entity", entity_or_dialog)
    if is_private_user_entity(entity):
        return "private_chat"

    type_name = type(entity).__name__
    if type_name == "User":
        return "private_chat"
    if type_name == "Chat":
        return "group_chat"
    if type_name == "Channel":
        if bool(getattr(entity, "broadcast", False)):
            return "public_channel"
        if bool(getattr(entity, "megagroup", False)):
            return "supergroup"
        if getattr(entity, "username", None):
            return "public_group"
        return "unknown"

    if getattr(entity, "broadcast", False):
        return "public_channel"
    if getattr(entity, "megagroup", False):
        return "supergroup"
    if getattr(entity, "title", None) and getattr(entity, "username", None):
        return "public_group"
    if getattr(entity, "title", None):
        return "group_chat"
    return "unknown"


def is_allowed_by_source_search_settings(entity_or_dialog: Any, source_settings: Any) -> bool:
    source_type = detect_source_type(entity_or_dialog)
    if source_type == "private_chat":
        return not bool(getattr(source_settings, "exclude_private_chats", True))
    if source_type == "public_channel":
        return bool(getattr(source_settings, "include_public_channels", True))
    if source_type == "public_group":
        return bool(getattr(source_settings, "include_public_groups", True))
    if source_type == "group_chat":
        return bool(getattr(source_settings, "include_group_chats", True))
    if source_type == "supergroup":
        return bool(getattr(source_settings, "include_supergroups", True))
    return False


def is_source_dialog_allowed(dialog_or_entity: Any, exclude_private_chats: bool = True, source_settings: Any | None = None) -> bool:
    """Return whether a dialog/entity is allowed as a parser source."""
    if source_settings is not None:
        return is_allowed_by_source_search_settings(dialog_or_entity, source_settings)

    if not exclude_private_chats:
        return True

    if getattr(dialog_or_entity, "is_user", False):
        return False

    entity = getattr(dialog_or_entity, "entity", dialog_or_entity)
    return not is_private_user_entity(entity)


def dialog_info_from_entity(entity: Any, peer_id: int | None = None) -> DialogInfo:
    """Build safe, serializable dialog information from a Telethon entity."""
    title = (
        getattr(entity, "title", None)
        or " ".join(
            part
            for part in [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
            if part
        )
        or getattr(entity, "username", None)
        or "без названия"
    )
    entity_id = peer_id if peer_id is not None else getattr(entity, "id", None)
    username = normalize_username(getattr(entity, "username", None))

    source_type = detect_source_type(entity)

    return DialogInfo(
        title=str(title),
        entity_type=type(entity).__name__,
        source_type=source_type,
        source_type_label=source_type_label(source_type),
        username=username,
        entity_id=entity_id,
        access_hash=getattr(entity, "access_hash", None),
        source_chats_value=source_chats_value(username, entity_id),
    )


def format_dialog_cli_item(dialog: DialogInfo, index: int) -> str:
    """Format a dialog for terminal output without exposing secrets."""
    lines = [
        f"{index}. Название: {dialog.title}",
        f"   Тип: {dialog.source_type_label}",
        f"   Username: {dialog.username or 'нет'}",
        f"   ID: {dialog.entity_id if dialog.entity_id is not None else 'нет'}",
    ]
    if dialog.access_hash is not None:
        lines.append(f"   Access hash: {dialog.access_hash} (не вставляйте в .env)")
    lines.append(f"   Значение для списка источников: {dialog.source_chats_value}")
    return "\n".join(lines)


def format_dialog_bot_item(dialog: DialogInfo, index: int) -> str:
    """Format a dialog for an HTML Telegram message."""
    return (
        f"{index}. {escape(dialog.title)}\n"
        f"Тип: {escape(dialog.source_type_label)}\n"
        f"Значение для списка источников: {escape(dialog.source_chats_value)}"
    )
