from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telethon import errors, functions

from app.source_discovery import parse_sources_text

StatusCallback = Callable[[str, str], Awaitable[None] | None]

logger = logging.getLogger(__name__)


def public_username_sources(source_values: list[str], max_join: int) -> list[str]:
    """Return at most max_join public @username sources, excluding numeric ids/invites."""
    normalized = parse_sources_text("\n".join(source_values))
    return normalized[: max(0, max_join)]


def invalid_public_sources(source_values: list[str]) -> list[str]:
    """Return user-provided values that cannot be normalized to public @username sources."""
    invalid: list[str] = []
    for raw in source_values:
        value = str(raw).strip()
        if not value:
            continue
        if not parse_sources_text(value):
            invalid.append(value)
    return invalid


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
        "request sent",
        "join request",
        "request required",
        "not accessible",
        "channel_private",
        "invite_hash",
        "user_banned_in_channel",
        "usernotmutualcontact",
        "user not mutual contact",
        "admin required",
    )
    return any(marker in name or marker in text for marker in markers)


def _manual_error_types() -> tuple[type[BaseException], ...]:
    names = (
        "ChannelPrivateError",
        "InviteRequestSentError",
        "UserNotMutualContactError",
        "ChatAdminRequiredError",
    )
    return tuple(exc_type for name in names if isinstance((exc_type := getattr(errors, name, None)), type))


async def _notify(callback: StatusCallback | None, source: str, status: str) -> None:
    if callback is None:
        return
    result = callback(source, status)
    if hasattr(result, "__await__"):
        await result  # type: ignore[misc]


async def _join_public_source(client: Any, source: str) -> None:
    entity = await client.get_entity(source) if hasattr(client, "get_entity") else source
    await client(functions.channels.JoinChannelRequest(entity))


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

    for invalid in invalid_public_sources(source_values):
        if len(sources) >= max_join and parse_sources_text(invalid):
            continue
        payload = {"source": invalid, "error": "Invalid public username source. Use @channel, t.me/channel, or channel."}
        result["failed"].append(payload)
        logger.info("source join skipped source=%s status=invalid", invalid)
        await _notify(status_callback, invalid, "invalid")

    manual_types = _manual_error_types()
    for index, source in enumerate(sources):
        try:
            logger.info("source join attempting source=%s", source)
            await _join_public_source(client, source)
            result["joined"].append(source)
            logger.info("source join result source=%s status=joined", source)
            await _notify(status_callback, source, "joined")
        except errors.UserAlreadyParticipantError:
            result["already_joined"].append(source)
            logger.info("source join result source=%s status=already_joined", source)
            await _notify(status_callback, source, "already_joined")
        except errors.FloodWaitError as exc:
            seconds = getattr(exc, "seconds", None)
            result["failed"].append({"source": source, "error": f"FloodWaitError: {seconds} seconds"})
            result["stopped_by_floodwait"] = True
            result["floodwait_seconds"] = seconds
            logger.warning("source join stopped by FloodWait source=%s seconds=%s", source, seconds)
            await _notify(status_callback, source, "floodwait")
            break
        except manual_types as exc:
            payload = {"source": source, "error": f"{type(exc).__name__}: {exc}"}
            result["manual_required"].append(payload)
            logger.info("source join result source=%s status=manual_required error=%s", source, exc)
            await _notify(status_callback, source, "manual_required")
        except Exception as exc:  # noqa: BLE001 - Telethon raises many RPC subclasses.
            payload = {"source": source, "error": f"{type(exc).__name__}: {exc}"}
            if is_manual_required_error(exc):
                result["manual_required"].append(payload)
                logger.info("source join result source=%s status=manual_required error=%s", source, exc)
                await _notify(status_callback, source, "manual_required")
            else:
                result["failed"].append(payload)
                logger.info("source join result source=%s status=failed error=%s", source, exc)
                await _notify(status_callback, source, "failed")

        if index < len(sources) - 1:
            await asyncio.sleep(max(0, delay_seconds))

    return result
