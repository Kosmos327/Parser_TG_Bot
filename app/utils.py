from __future__ import annotations

from typing import Any


def build_message_link(chat: Any, source_id: int | None, message_id: int) -> str | None:
    """Build a public or Telegram internal message link when enough source data is available."""
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"

    if source_id is not None:
        source_id_text = str(source_id)
        if source_id_text.startswith("-100"):
            internal_id = source_id_text.removeprefix("-100")
            if internal_id:
                return f"https://t.me/c/{internal_id}/{message_id}"

    return None
