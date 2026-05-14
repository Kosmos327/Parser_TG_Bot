from types import SimpleNamespace

from app.dialogs import (
    dialog_info_from_entity,
    format_dialog_bot_item,
    format_dialog_cli_item,
    normalize_username,
    source_chats_value,
)


def test_username_becomes_source_chats_at_username() -> None:
    entity = SimpleNamespace(title="Business Chat", username="business_chat", id=123456789)

    info = dialog_info_from_entity(entity)

    assert info.username == "@business_chat"
    assert info.source_chats_value == "@business_chat"


def test_username_with_at_is_not_duplicated() -> None:
    assert normalize_username("@business_chat") == "@business_chat"


def test_missing_username_uses_id_fallback() -> None:
    entity = SimpleNamespace(title="Private Group", username=None, id=-1001234567890)

    info = dialog_info_from_entity(entity)

    assert info.username is None
    assert info.source_chats_value == "-1001234567890"


def test_source_chats_value_prefers_username_over_id() -> None:
    assert source_chats_value("channel1", -1001234567890) == "@channel1"


def test_cli_format_contains_source_chats_and_access_hash_note() -> None:
    entity = SimpleNamespace(title="Business Chat", username="business_chat", id=123456789, access_hash=987654321)
    info = dialog_info_from_entity(entity)

    formatted = format_dialog_cli_item(info, 1)

    assert "Значение для списка источников: @business_chat" in formatted
    assert "Access hash: 987654321 (не вставляйте в .env)" in formatted


def test_bot_format_escapes_html_and_hides_access_hash() -> None:
    entity = SimpleNamespace(title="<Business>", username=None, id=-1001234567890, access_hash=987654321)
    info = dialog_info_from_entity(entity)

    formatted = format_dialog_bot_item(info, 1)

    assert "&lt;Business&gt;" in formatted
    assert "Значение для списка источников: -1001234567890" in formatted
    assert "987654321" not in formatted

from app.dialogs import is_source_dialog_allowed


def test_private_user_excluded_when_enabled() -> None:
    entity = SimpleNamespace(first_name="Ivan", last_name="User", username="ivan", id=42)

    assert is_source_dialog_allowed(entity, exclude_private_chats=True) is False


def test_private_user_allowed_when_disabled() -> None:
    entity = SimpleNamespace(first_name="Ivan", last_name="User", username="ivan", id=42)

    assert is_source_dialog_allowed(entity, exclude_private_chats=False) is True


def test_channel_allowed_when_private_exclusion_enabled() -> None:
    entity = SimpleNamespace(title="Public Channel", username="channel", id=-1001)

    assert is_source_dialog_allowed(entity, exclude_private_chats=True) is True
