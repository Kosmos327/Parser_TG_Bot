from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, Dispatcher
from telethon import TelegramClient, events

from app.bot_handlers import register_bot_handlers
from app.config import Settings, load_settings
from app.filters import message_matches
from app.leads_storage import append_lead
from app.models import LeadEvent
from app.notifier import send_lead_notification
from app.state import ParserState
from app.storage import load_processed, save_processed
from app.utils import build_message_link

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
    state = ParserState(enabled=settings.parser_enabled)
    processed = load_processed(settings.dedup_file)
    logger.info("Loaded %s processed message keys.", len(processed))

    client = TelegramClient(settings.session_name, settings.api_id, settings.api_hash)
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher()
    register_bot_handlers(dispatcher, settings, state)

    @client.on(_build_event_builder(settings))
    async def handle_new_message(event: events.NewMessage.Event) -> None:
        state.processed_count += 1
        try:
            if not state.enabled:
                logger.debug("Parser is paused. Skipping message %s.", getattr(event.message, "id", None))
                return

            text = (event.message.message or "").strip()
            if not message_matches(text, settings.keywords):
                return

            source_id = event.chat_id
            message_id = event.message.id
            key = _processed_key(source_id, message_id)
            if key in processed:
                logger.debug("Message %s has already been processed.", key)
                return

            chat = await event.get_chat()
            sender = await event.get_sender()

            lead = LeadEvent(
                source_title=_source_title(chat, source_id),
                source_id=source_id,
                message_id=message_id,
                sender_id=getattr(sender, "id", None),
                sender_username=getattr(sender, "username", None),
                sender_first_name=getattr(sender, "first_name", None),
                text=text,
                message_link=build_message_link(chat, source_id, message_id),
                matched_at=datetime.now(timezone.utc),
            )

            append_lead(settings.leads_file, lead)
            await send_lead_notification(bot, settings.admin_chat_id, lead)

            state.matched_count += 1
            processed.add(key)
            save_processed(settings.dedup_file, processed)
            logger.info("Lead saved, notification sent, and message %s marked as processed.", key)
        except Exception as exc:
            state.last_error = str(exc)
            logger.exception("Failed to process incoming message.")

    telethon_task: asyncio.Task[Any] | None = None
    polling_task: asyncio.Task[Any] | None = None

    try:
        await client.start()
        logger.info("Parser started. Press Ctrl+C to stop.")
        telethon_task = asyncio.create_task(client.run_until_disconnected(), name="telethon")
        polling_task = asyncio.create_task(dispatcher.start_polling(bot), name="aiogram-polling")

        done, pending = await asyncio.wait(
            {telethon_task, polling_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.result()
        for task in pending:
            await _cancel_task(task)
    finally:
        logger.info("Stopping parser and closing network sessions.")
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
