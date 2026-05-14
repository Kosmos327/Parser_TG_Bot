from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, Dispatcher
from telethon import TelegramClient, events

from app.auto_sources import auto_source_discovery_loop
from app.bot_handlers import register_bot_handlers
from app.config import Settings, load_settings, risky_settings_warnings
from app.dialogs import is_source_dialog_allowed
from app.source_search_settings import load_source_search_settings
from app.filters import evaluate_lead_match
from app.lead_dedup import is_duplicate_lead
from app.leads_storage import append_lead
from app.models import LeadEvent
from app.notifier import send_lead_notification
from app.rules_storage import load_rules
from app.state import ParserState
from app.storage import load_processed, save_processed
from app.utils import build_message_link
from app.web_dashboard import start_web_dashboard

logger = logging.getLogger(__name__)


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text

    if max_length == 1:
        return "…"
    return f"{text[: max_length - 1]}…"


def _is_forwarded(message: Any) -> bool:
    return bool(getattr(message, "fwd_from", None) or getattr(message, "forward", None))


def _processed_key(source_id: int | None, message_id: int) -> str:
    return f"{source_id}:{message_id}"


def _source_title(chat: Any, source_id: int | None) -> str | None:
    return getattr(chat, "title", None) or getattr(chat, "username", None) or (
        f"ID {source_id}" if source_id is not None else None
    )


def _normalize_source_chat(value: str) -> str | int:
    cleaned = value.strip()
    if cleaned.lstrip("-").isdigit():
        return int(cleaned)
    return cleaned


def _build_event_builder(settings: Settings) -> events.NewMessage:
    if settings.source_chats:
        source_chats = [_normalize_source_chat(chat) for chat in settings.source_chats]
        logger.info("Listening to configured source chats: %s", ", ".join(settings.source_chats))
        return events.NewMessage(chats=source_chats)

    logger.info("SOURCE_CHATS is empty. Listening to all available incoming messages.")
    return events.NewMessage()


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    if task.done():
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def run() -> None:
    settings = load_settings()
    _configure_logging(settings.log_level)
    rules = load_rules(settings.rules_file, settings)
    state = ParserState(enabled=settings.parser_enabled, rules=rules)
    processed = load_processed(settings.dedup_file)
    logger.info("Loaded %s processed message keys.", len(processed))
    for warning in risky_settings_warnings(settings):
        logger.warning(warning)

    client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher()
    register_bot_handlers(dispatcher, settings, state, telethon_client=client, bot=bot)

    @client.on(_build_event_builder(settings))
    async def handle_new_message(event: events.NewMessage.Event) -> None:
        state.processed_count += 1
        try:
            source_id = event.chat_id
            message_id = event.message.id
            chat = await event.get_chat()
            sender = await event.get_sender()
            source_title = _source_title(chat, source_id)

            source_search_settings = load_source_search_settings(settings.source_search_settings_file, settings)
            if not is_source_dialog_allowed(chat, source_settings=source_search_settings):
                logger.debug("Skipping message %s: source type is disabled in search settings.", message_id)
                return

            if not state.enabled:
                logger.debug("Parser is paused. Skipping message %s.", message_id)
                return

            rules = state.rules

            if rules.ignore_bots and getattr(sender, "bot", False):
                logger.debug("Skipping message %s: bot sender.", message_id)
                return

            if rules.ignore_forwards and _is_forwarded(event.message):
                logger.debug("Skipping message %s: forwarded message.", message_id)
                return

            text = event.message.message or ""
            match = evaluate_lead_match(text, source_title, rules)
            if not match.matched:
                logger.debug("Skipping message %s: %s.", message_id, match.reason)
                return

            key = _processed_key(source_id, message_id)
            if key in processed:
                logger.debug("Message %s has already been processed.", key)
                return

            sender_id = getattr(sender, "id", None)
            sender_username = getattr(sender, "username", None)
            if settings.lead_dedup_enabled:
                duplicate, original_lead_id = is_duplicate_lead(
                    settings.leads_file,
                    text,
                    sender_username,
                    sender_id,
                    settings.lead_dedup_window_hours,
                    settings.lead_dedup_similarity_threshold,
                )
                if duplicate:
                    state.duplicate_count += 1
                    processed.add(key)
                    save_processed(settings.dedup_file, processed)
                    logger.info("duplicate lead skipped, original_lead_id=%s", original_lead_id)
                    return

            lead = LeadEvent(
                source_title=source_title,
                source_id=source_id,
                message_id=message_id,
                sender_id=sender_id,
                sender_username=sender_username,
                sender_first_name=getattr(sender, "first_name", None),
                text=_truncate_text(text.strip(), settings.max_text_length),
                message_link=build_message_link(chat, source_id, message_id),
                matched_at=datetime.now(timezone.utc),
                score=match.score,
                matched_phrases=match.matched_phrases,
                negative_phrases=match.negative_phrases,
            )

            append_lead(settings.leads_file, lead)
            if settings.dry_run:
                logger.info("Lead found in dry-run mode. Notification skipped for message %s.", key)
            else:
                await send_lead_notification(
                    bot,
                    settings.admin_chat_id,
                    lead,
                    max_text_length=settings.max_text_length,
                )

            state.matched_count += 1
            processed.add(key)
            save_processed(settings.dedup_file, processed)
            notification_status = ", notification sent" if not settings.dry_run else ""
            logger.info("Lead saved%s and message %s marked as processed.", notification_status, key)
        except Exception as exc:
            state.last_error = str(exc)
            logger.exception("Failed to process incoming message.")

    telethon_task: asyncio.Task[Any] | None = None
    polling_task: asyncio.Task[Any] | None = None
    auto_sources_task: asyncio.Task[Any] | None = None
    dashboard_runner: Any | None = None

    try:
        await client.start()
        logger.info("Parser started. Press Ctrl+C to stop.")
        telethon_task = asyncio.create_task(client.run_until_disconnected(), name="telethon")
        polling_task = asyncio.create_task(dispatcher.start_polling(bot), name="aiogram-polling")
        if settings.auto_source_discovery_enabled:
            auto_sources_task = asyncio.create_task(auto_source_discovery_loop(settings, state, client, bot), name="auto-source-discovery")
        if settings.web_dashboard_enabled:
            dashboard_runner = await start_web_dashboard(settings, state)

        tasks = {telethon_task, polling_task}
        if auto_sources_task is not None:
            tasks.add(auto_sources_task)
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.result()
        for task in pending:
            await _cancel_task(task)
    finally:
        logger.info("Stopping parser and closing network sessions.")
        if auto_sources_task is not None:
            await _cancel_task(auto_sources_task)
        if dashboard_runner is not None:
            await dashboard_runner.cleanup()
        if polling_task is not None:
            await _cancel_task(polling_task)
        if telethon_task is not None:
            await _cancel_task(telethon_task)
        try:
            await dispatcher.stop_polling()
        except RuntimeError:
            pass
        await bot.session.close()
        await client.disconnect()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Parser stopped by user.")


if __name__ == "__main__":
    main()
