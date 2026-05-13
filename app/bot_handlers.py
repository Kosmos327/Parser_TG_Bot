from __future__ import annotations

from html import escape

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
        async def wrapper(message: Message) -> None:
            if not is_admin(message, settings):
                await message.answer("Нет доступа.")
                return
            await handler(message)

        return wrapper

    return decorator


def register_bot_handlers(dispatcher: Dispatcher, settings: Settings, state: ParserState) -> None:
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

    dispatcher.include_router(router)
