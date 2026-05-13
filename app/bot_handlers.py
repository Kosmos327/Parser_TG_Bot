from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from html import escape
from typing import Any

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Settings
from app.leads_storage import count_leads, get_last_leads
from app.models import LeadEvent
from app.state import ParserState


def is_admin(message: Message, settings: Settings) -> bool:
    """Return whether a Telegram message is allowed to control the bot."""
    user_id = message.from_user.id if message.from_user else None
    if settings.admin_ids:
        return user_id in settings.admin_ids

    return message.chat.id == settings.admin_chat_id


def _format_help() -> str:
    return (
        "Бот управления Telegram lead parser.\n\n"
        "Команды:\n"
        "/status — статус парсера\n"
        "/pause — выключить обработку новых лидов\n"
        "/resume — включить обработку новых лидов\n"
        "/last — последние 5 заявок\n"
        "/last 10 — последние 10 заявок, максимум 20\n"
        "/stats — статистика сохранённых заявок\n"
        "/keywords — текущие ключевые фразы\n"
        "/sources — текущие источники\n"
        "/config — безопасная конфигурация\n"
        "/health — состояние polling, Telethon и парсера\n"
        "/help — список команд"
    )


def _parse_last_limit(message: Message) -> int:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        return 5

    try:
        return min(max(int(parts[1].strip()), 1), 20)
    except ValueError:
        return 5


def _format_lead(lead: LeadEvent, index: int) -> str:
    source = lead.source_title or (f"ID {lead.source_id}" if lead.source_id is not None else "неизвестно")
    if lead.sender_username:
        user = f"@{lead.sender_username}"
    elif lead.sender_first_name:
        user = f"{lead.sender_first_name} / ID {lead.sender_id}" if lead.sender_id is not None else lead.sender_first_name
    elif lead.sender_id is not None:
        user = f"ID {lead.sender_id}"
    else:
        user = "неизвестно"

    text = lead.text.strip()
    if len(text) > 700:
        text = f"{text[:697]}..."

    date_text = lead.matched_at.strftime("%Y-%m-%d %H:%M:%S %Z")
    link = lead.message_link or "нет публичной ссылки"
    return (
        f"<b>{index}.</b> {escape(source)}\n"
        f"<b>Пользователь:</b> {escape(user)}\n"
        f"<b>Дата:</b> {escape(date_text)}\n"
        f"<b>Текст:</b> {escape(text)}\n"
        f"<b>Ссылка:</b> {escape(link)}"
    )


def _admin_only(settings: Settings):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(message: Message) -> None:
            if not is_admin(message, settings):
                await message.answer("Нет доступа.")
                return
            await handler(message)

        return wrapper

    return decorator


def _format_bool(value: bool) -> str:
    return "on" if value else "off"


def _format_list(title: str, values: list[str]) -> str:
    if not values:
        return f"{title} (0): нет"

    formatted = "\n".join(f"  - {escape(value)}" for value in values)
    return f"{title} ({len(values)}):\n{formatted}"


def _format_uptime(started_at: datetime) -> str:
    total_seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _format_safe_config(settings: Settings, state: ParserState) -> str:
    parts = [
        "<b>Безопасная конфигурация</b>",
        f"parser_enabled: {_format_bool(state.enabled)}",
        f"dry_run: {_format_bool(settings.dry_run)}",
        f"min_message_length: {settings.min_message_length}",
        f"ignore_bots: {_format_bool(settings.ignore_bots)}",
        f"ignore_forwards: {_format_bool(settings.ignore_forwards)}",
        f"session_name: {escape(settings.session_name)}",
        _format_list("keywords", settings.keywords),
        _format_list("exclude_keywords", settings.exclude_keywords),
        _format_list("source_chats", settings.source_chats),
        _format_list("include_source_titles", settings.include_source_titles),
        _format_list("exclude_source_titles", settings.exclude_source_titles),
        f"leads_file: {escape(settings.leads_file)}",
        f"dedup_file: {escape(settings.dedup_file)}",
        f"log_level: {escape(settings.log_level)}",
    ]
    return "\n".join(parts)


def _telethon_status(client: Any | None) -> str:
    if client is None:
        return "unknown"

    try:
        return "connected" if client.is_connected() else "disconnected"
    except Exception:
        return "unknown"


def _format_health(settings: Settings, state: ParserState, client: Any | None) -> str:
    return (
        "<b>Health</b>\n"
        "Bot polling: OK\n"
        f"Telethon client: {_telethon_status(client)}\n"
        f"Parser: {'enabled' if state.enabled else 'disabled'}\n"
        f"Dry-run: {'on' if settings.dry_run else 'off'}\n"
        f"Last error: {escape(state.last_error or 'нет')}\n"
        f"Uptime: {_format_uptime(state.started_at)}\n"
        f"Processed count: {state.processed_count}\n"
        f"Matched count: {state.matched_count}"
    )


def register_bot_handlers(
    dispatcher: Dispatcher,
    settings: Settings,
    state: ParserState,
    telethon_client: Any | None = None,
) -> None:
    router = Router()

    @router.message(Command("start"))
    @_admin_only(settings)
    async def start(message: Message) -> None:
        await message.answer(_format_help())

    @router.message(Command("help"))
    @_admin_only(settings)
    async def help_command(message: Message) -> None:
        await message.answer(_format_help())

    @router.message(Command("status"))
    @_admin_only(settings)
    async def status(message: Message) -> None:
        await message.answer(state.status_text())

    @router.message(Command("pause"))
    @_admin_only(settings)
    async def pause(message: Message) -> None:
        state.disable()
        await message.answer("Парсер поставлен на паузу. Процесс работает, но новые лиды не обрабатываются.")

    @router.message(Command("resume"))
    @_admin_only(settings)
    async def resume(message: Message) -> None:
        state.enable()
        await message.answer("Парсер возобновил обработку новых лидов.")

    @router.message(Command("last"))
    @_admin_only(settings)
    async def last(message: Message) -> None:
        limit = _parse_last_limit(message)
        leads = get_last_leads(settings.leads_file, limit=limit)
        if not leads:
            await message.answer("Сохранённых заявок пока нет.")
            return

        formatted = "\n\n".join(_format_lead(lead, index) for index, lead in enumerate(leads, start=1))
        await message.answer(formatted, parse_mode="HTML", disable_web_page_preview=True)

    @router.message(Command("stats"))
    @_admin_only(settings)
    async def stats(message: Message) -> None:
        total = count_leads(settings.leads_file)
        await message.answer(
            "Статистика:\n"
            f"Всего сохранённых заявок: {total}\n"
            f"Обработано сообщений за текущий запуск: {state.processed_count}\n"
            f"Найдено заявок за текущий запуск: {state.matched_count}"
        )

    @router.message(Command("keywords"))
    @_admin_only(settings)
    async def keywords(message: Message) -> None:
        text = "\n".join(f"- {keyword}" for keyword in settings.keywords)
        await message.answer(f"Текущие ключевые фразы:\n{text}")

    @router.message(Command("sources"))
    @_admin_only(settings)
    async def sources(message: Message) -> None:
        if not settings.source_chats:
            await message.answer("Источники: все доступные события")
            return

        text = "\n".join(f"- {source}" for source in settings.source_chats)
        await message.answer(f"Текущие источники:\n{text}")

    @router.message(Command("config"))
    @_admin_only(settings)
    async def config(message: Message) -> None:
        await message.answer(_format_safe_config(settings, state), parse_mode="HTML")

    @router.message(Command("health"))
    @_admin_only(settings)
    async def health(message: Message) -> None:
        await message.answer(_format_health(settings, state, telethon_client), parse_mode="HTML")

    dispatcher.include_router(router)
