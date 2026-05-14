from types import SimpleNamespace

from app.source_search_settings import (
    SourceSearchSettings,
    load_source_search_settings,
    reset_source_search_settings,
    toggle_source_search_setting,
)


def _settings(exclude_private_chats: bool = True):
    return SimpleNamespace(exclude_private_chats=exclude_private_chats)


def test_default_settings_are_created(tmp_path) -> None:
    path = tmp_path / "nested" / "source_search_settings.json"

    settings = load_source_search_settings(str(path), _settings(exclude_private_chats=False))

    assert settings == SourceSearchSettings(exclude_private_chats=False)
    assert path.exists()


def test_toggle_changes_boolean(tmp_path) -> None:
    path = tmp_path / "settings.json"

    settings = toggle_source_search_setting(str(path), "include_public_channels", _settings())

    assert settings.include_public_channels is False
    assert load_source_search_settings(str(path), _settings()).include_public_channels is False


def test_reset_returns_default(tmp_path) -> None:
    path = tmp_path / "settings.json"
    toggle_source_search_setting(str(path), "include_public_groups", _settings())

    settings = reset_source_search_settings(str(path), _settings(exclude_private_chats=False))

    assert settings.include_public_groups is True
    assert settings.exclude_private_chats is False


def test_corrupted_json_falls_back_to_default(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{bad json", encoding="utf-8")

    settings = load_source_search_settings(str(path), _settings())

    assert settings == SourceSearchSettings()
    assert "include_public_channels" in path.read_text(encoding="utf-8")
