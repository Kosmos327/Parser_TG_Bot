from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from telethon import errors, functions

from app.source_discovery import parse_sources_text

StatusCallback = Callable[[str, str], Awaitable[None] | None]


def public_username_sources(source_values: list[str], max_join: int) -> list[str]:
    """Return at most max_join public @username sources, excluding numeric ids/invites."""
    normalized = parse_sources_text("\n".join(source_values))
    return normalized[: max(0, max_join)]


def is_manual_required_error(exc: Exception) -> bool:
    """Classify errors that require a human Telegram action instead of automation."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    markers = (
        "captcha",
        "approval",
        "approve",
        "private",
        "invite",
        "request_sent",
        "join request",
        "not accessible",
        "channel_private",
        "invite_hash",
        "user_banned_in_channel",
    )
    return any(marker in name or marker in text for marker in markers)


async def _notify(callback: StatusCallback | None, source: str, status: str) -> None:
    if callback is None:
        return
    result = callback(source, status)
    if hasattr(result, "__await__"):
        await result  # type: ignore[misc]


async def join_sources_limited(
    client: Any,
    source_values: list[str],
    delay_seconds: int,
    max_join: int,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    """Safely join a small batch of public username sources without bypassing Telegram limits."""
    result: dict[str, Any] = {
        "joined": [],
        "already_joined": [],
        "manual_required": [],
        "failed": [],
        "stopped_by_floodwait": False,
        "floodwait_seconds": None,
    }
    sources = public_username_sources(source_values, max_join)

    for index, source in enumerate(sources):
        try:
            await client(functions.channels.JoinChannelRequest(source))
            result["joined"].append(source)
            await _notify(status_callback, source, "joined")
        except errors.UserAlreadyParticipantError:
            result["already_joined"].append(source)
            await _notify(status_callback, source, "already_joined")
        except errors.FloodWaitError as exc:
            seconds = getattr(exc, "seconds", None)
            result["failed"].append({"source": source, "error": f"FloodWaitError: {seconds} seconds"})
            result["stopped_by_floodwait"] = True
            result["floodwait_seconds"] = seconds
            await _notify(status_callback, source, "floodwait")
            break
        except Exception as exc:  # noqa: BLE001 - Telethon raises many RPC subclasses.
            payload = {"source": source, "error": f"{type(exc).__name__}: {exc}"}
            if is_manual_required_error(exc):
                result["manual_required"].append(payload)
                await _notify(status_callback, source, "manual_required")
            else:
                result["failed"].append(payload)
                await _notify(status_callback, source, "failed")

        if index < len(sources) - 1:
            await asyncio.sleep(max(0, delay_seconds))

    return result
