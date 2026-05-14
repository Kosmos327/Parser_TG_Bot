from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceSearchSettings:
    include_public_channels: bool = True
    include_public_groups: bool = True
    include_group_chats: bool = True
    include_supergroups: bool = True
    exclude_private_chats: bool = True


_FIELD_NAMES = {field.name for field in fields(SourceSearchSettings)}


def get_default_source_search_settings(settings: Any) -> SourceSearchSettings:
    return SourceSearchSettings(exclude_private_chats=bool(getattr(settings, "exclude_private_chats", True)))


def _write(path: str, source_settings: SourceSearchSettings) -> None:
    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(asdict(source_settings), ensure_ascii=False, indent=2), encoding="utf-8")


def load_source_search_settings(path: str, settings: Any) -> SourceSearchSettings:
    settings_path = Path(path)
    defaults = get_default_source_search_settings(settings)
    if not settings_path.exists():
        _write(path, defaults)
        return defaults

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings JSON must be an object")
        values = asdict(defaults)
        for key in _FIELD_NAMES:
            if key in data:
                values[key] = bool(data[key])
        return SourceSearchSettings(**values)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Source search settings file is invalid, defaults will be recreated: %s", exc)
        _write(path, defaults)
        return defaults


def save_source_search_settings(path: str, source_settings: SourceSearchSettings) -> None:
    _write(path, source_settings)


def toggle_source_search_setting(path: str, field: str, settings: Any) -> SourceSearchSettings:
    if field not in _FIELD_NAMES:
        raise ValueError(f"Unknown source search setting: {field}")
    current = load_source_search_settings(path, settings)
    values = asdict(current)
    values[field] = not bool(values[field])
    updated = SourceSearchSettings(**values)
    save_source_search_settings(path, updated)
    return updated


def reset_source_search_settings(path: str, settings: Any) -> SourceSearchSettings:
    defaults = get_default_source_search_settings(settings)
    save_source_search_settings(path, defaults)
    return defaults
