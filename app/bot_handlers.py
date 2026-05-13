from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from html import escape
from typing import Any

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Settings
from app.leads_storage import count_leads, get_last_leads
from app.models import LeadEvent
from app.rules_storage import LIST_FIELDS, add_rule_item, remove_rule_item, save_rules, set_rule_value
from app.state import ParserState

CATEGORY_TITLES = {
    "trigger_words": "Слова-триггеры",
    "exclude_words": "Стоп-слова",
    "include_source_titles": "Разрешённые источники",
    "exclude_source_titles": "Исключённые источники",
}


PendingState = dict[str, str]


def is_admin(message: Message, settings: Settings) -> bool:
    """Return whether a Telegram message is allowed to control the bot."""
    user_id = message.from_user.id if message.from_user else None
    if settings.admin_ids:
        return user_id in settings.admin_ids

    return message.chat.id == settings.admin_chat_id


def is_admin_callback(callback: CallbackQuery, settings: Settings) -> bool:
    """Return whether a callback query is allowed to control the bot."""
    user_id = callback.from_user.id if callback.from_user else None
    if settings.admin_ids:
        return user_id in settings.admin_ids

    message = callback.message
    return bool(message and message.chat.id == settings.admin_chat_id)


def _rules_button_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⚙️ Правила парсинга", callback_data="rules:menu")]]
    )


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
        "/keywords — текущие слова-триггеры\n"
        "/sources — текущие источники\n"
        "/rules — открыть правила парсинга\n"
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


def _format_yes_no(value: bool) -> str:
    return "Да" if value else "Нет"


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
    rules = state.rules
    parts = [
        "<b>Безопасная конфигурация</b>",
        f"rules_file: {escape(settings.rules_file)}",
        f"parser_enabled: {_format_bool(state.enabled)}",
        f"dry_run: {_format_bool(settings.dry_run)}",
        _format_list("trigger_words", rules.trigger_words),
        _format_list("exclude_words", rules.exclude_words),
        _format_list("include_source_titles", rules.include_source_titles),
        _format_list("exclude_source_titles", rules.exclude_source_titles),
        f"min_message_length: {rules.min_message_length}",
        f"ignore_bots: {_format_bool(rules.ignore_bots)}",
        f"ignore_forwards: {_format_bool(rules.ignore_forwards)}",
        _format_list("source_chats", settings.source_chats),
        f"leads_file: {escape(settings.leads_file)}",
        f"dedup_file: {escape(settings.dedup_file)}",
        f"log_level: {escape(settings.log_level)}",
    ]
    return "\n".join(parts)


def _format_rules_menu(state: ParserState) -> str:
    rules = state.rules
    return (
        "⚙️ <b>Правила парсинга</b>\n\n"
        "Критерии:\n"
        f"1. Слова-триггеры: {len(rules.trigger_words)}\n"
        f"2. Стоп-слова: {len(rules.exclude_words)}\n"
        f"3. Разрешённые источники: {len(rules.include_source_titles)}\n"
        f"4. Исключённые источники: {len(rules.exclude_source_titles)}\n"
        f"5. Мин. длина сообщения: {rules.min_message_length}\n"
        f"6. Игнорировать ботов: {_format_yes_no(rules.ignore_bots)}\n"
        f"7. Игнорировать пересланные: {_format_yes_no(rules.ignore_forwards)}"
    )


def _rules_menu_markup(state: ParserState) -> InlineKeyboardMarkup:
    rules = state.rules
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Слова-триггеры", callback_data="rules:list:trigger_words")],
            [InlineKeyboardButton(text="⛔ Стоп-слова", callback_data="rules:list:exclude_words")],
            [InlineKeyboardButton(text="✅ Разрешённые источники", callback_data="rules:list:include_source_titles")],
            [InlineKeyboardButton(text="🚫 Исключённые источники", callback_data="rules:list:exclude_source_titles")],
            [InlineKeyboardButton(text="📏 Мин. длина", callback_data="rules:min_length")],
            [
                InlineKeyboardButton(
                    text=f"🤖 Игнорировать ботов: {_format_yes_no(rules.ignore_bots)}",
                    callback_data="rules:toggle:ignore_bots",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔁 Игнорировать пересланные: {_format_yes_no(rules.ignore_forwards)}",
                    callback_data="rules:toggle:ignore_forwards",
                )
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="rules:back")],
        ]
    )


def _format_category(category: str, state: ParserState) -> str:
    title = CATEGORY_TITLES[category]
    values = getattr(state.rules, category)
    if values:
        items = "\n".join(f"{index}. {escape(value)}" for index, value in enumerate(values, start=1))
    else:
        items = "Список пуст"
    return f"<b>{escape(title)}</b>\n\n{items}"


def _category_markup(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить", callback_data=f"rules:add:{category}")],
            [InlineKeyboardButton(text="➖ Удалить", callback_data=f"rules:remove:{category}")],
            [InlineKeyboardButton(text="🧹 Очистить список", callback_data=f"rules:clear_confirm:{category}")],
            [InlineKeyboardButton(text="🔙 Назад к правилам", callback_data="rules:menu")],
        ]
    )


def _clear_confirm_text(category: str) -> str:
    title = CATEGORY_TITLES[category]
    warning = ""
    if category == "trigger_words":
        warning = "\n\nПосле очистки слов-триггеров парсер не будет находить заявки, пока вы не добавите новые слова."
    return f"Точно очистить список: {escape(title)}?{warning}"


def _clear_confirm_markup(category: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, очистить", callback_data=f"rules:clear:{category}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"rules:list:{category}")],
        ]
    )


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


def _user_key(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


def register_bot_handlers(
    dispatcher: Dispatcher,
    settings: Settings,
    state: ParserState,
    telethon_client: Any | None = None,
) -> None:
    router = Router()
    pending: dict[int, PendingState] = {}

    async def send_rules_menu(message: Message) -> None:
        await message.answer(_format_rules_menu(state), reply_markup=_rules_menu_markup(state), parse_mode="HTML")

    async def edit_rules_menu(callback: CallbackQuery) -> None:
        if callback.message:
            await callback.message.edit_text(
                _format_rules_menu(state), reply_markup=_rules_menu_markup(state), parse_mode="HTML"
            )

    async def answer_category(message: Message, category: str) -> None:
        await message.answer(_format_category(category, state), reply_markup=_category_markup(category), parse_mode="HTML")

    @router.message(Command("start"))
    @_admin_only(settings)
    async def start(message: Message) -> None:
        await message.answer(_format_help(), reply_markup=_rules_button_markup())

    @router.message(Command("help"))
    @_admin_only(settings)
    async def help_command(message: Message) -> None:
        await message.answer(_format_help(), reply_markup=_rules_button_markup())

    @router.message(Command("rules"))
    @_admin_only(settings)
    async def rules_command(message: Message) -> None:
        await send_rules_menu(message)

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
        if state.rules.trigger_words:
            text = "\n".join(f"- {keyword}" for keyword in state.rules.trigger_words)
        else:
            text = "нет"
        await message.answer(f"Текущие слова-триггеры:\n{text}")

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

    @router.callback_query(lambda callback: callback.data == "rules:menu")
    async def rules_menu_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        await edit_rules_menu(callback)
        await callback.answer()

    @router.callback_query(lambda callback: callback.data == "rules:back")
    async def rules_back_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await callback.message.edit_text(_format_help(), reply_markup=_rules_button_markup())
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("rules:list:")))
    async def rules_list_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        category = (callback.data or "").split(":", 2)[2]
        if category not in LIST_FIELDS or not callback.message:
            await callback.answer("Неизвестная категория.", show_alert=True)
            return
        await callback.message.edit_text(_format_category(category, state), reply_markup=_category_markup(category), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("rules:add:")))
    async def rules_add_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        category = (callback.data or "").split(":", 2)[2]
        if category not in LIST_FIELDS or not callback.message:
            await callback.answer("Неизвестная категория.", show_alert=True)
            return
        pending[callback.from_user.id] = {"action": "add", "category": category}
        await callback.message.answer(f"Отправьте новое значение для категории: {CATEGORY_TITLES[category]}")
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("rules:remove:")))
    async def rules_remove_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        category = (callback.data or "").split(":", 2)[2]
        if category not in LIST_FIELDS or not callback.message:
            await callback.answer("Неизвестная категория.", show_alert=True)
            return
        pending[callback.from_user.id] = {"action": "remove", "category": category}
        await callback.message.answer("Отправьте точное значение, которое нужно удалить")
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("rules:clear_confirm:")))
    async def rules_clear_confirm_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        category = (callback.data or "").split(":", 2)[2]
        if category not in LIST_FIELDS or not callback.message:
            await callback.answer("Неизвестная категория.", show_alert=True)
            return
        await callback.message.edit_text(_clear_confirm_text(category), reply_markup=_clear_confirm_markup(category), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("rules:clear:")))
    async def rules_clear_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        category = (callback.data or "").split(":", 2)[2]
        if category not in LIST_FIELDS or not callback.message:
            await callback.answer("Неизвестная категория.", show_alert=True)
            return
        setattr(state.rules, category, [])
        save_rules(settings.rules_file, state.rules)
        await callback.message.edit_text(_format_category(category, state), reply_markup=_category_markup(category), parse_mode="HTML")
        await callback.answer("Список очищен.")

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("rules:toggle:")))
    async def rules_toggle_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        field = (callback.data or "").split(":", 2)[2]
        if field not in {"ignore_bots", "ignore_forwards"}:
            await callback.answer("Неизвестное поле.", show_alert=True)
            return
        state.rules = set_rule_value(settings.rules_file, field, not getattr(state.rules, field), settings)
        await edit_rules_menu(callback)
        await callback.answer("Сохранено.")

    @router.callback_query(lambda callback: callback.data == "rules:min_length")
    async def rules_min_length_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        pending[callback.from_user.id] = {"action": "min_length", "category": ""}
        if callback.message:
            await callback.message.answer("Отправьте новое число от 1 до 1000")
        await callback.answer()

    @router.message()
    async def pending_text(message: Message) -> None:
        user_id = _user_key(message)
        if user_id is None or user_id not in pending:
            return
        if not is_admin(message, settings):
            pending.pop(user_id, None)
            await message.answer("Нет доступа.")
            return

        current = pending.pop(user_id)
        action = current["action"]
        category = current.get("category", "")
        value = (message.text or "").strip()

        if action in {"add", "remove"}:
            if not value:
                await message.answer("Пустое значение не сохранено.")
                await answer_category(message, category)
                return
            if len(value) > 200:
                await message.answer("Значение длиннее 200 символов отклонено.")
                await answer_category(message, category)
                return

            if action == "add":
                before = {item.casefold() for item in getattr(state.rules, category)}
                state.rules = add_rule_item(settings.rules_file, category, value, settings)
                if value.casefold() in before:
                    await message.answer(f"Дубликат не добавлен: {value}")
                else:
                    await message.answer(f"Добавлено: {value}")
            else:
                before = {item.casefold() for item in getattr(state.rules, category)}
                state.rules = remove_rule_item(settings.rules_file, category, value, settings)
                if value.casefold() in before:
                    await message.answer(f"Удалено: {value}")
                else:
                    await message.answer(f"Не найдено: {value}")
            await answer_category(message, category)
            return

        if action == "min_length":
            try:
                number = int(value)
            except ValueError:
                await message.answer("Ошибка: отправьте число от 1 до 1000.")
                await send_rules_menu(message)
                return
            if not 1 <= number <= 1000:
                await message.answer("Ошибка: число должно быть от 1 до 1000.")
                await send_rules_menu(message)
                return
            state.rules = set_rule_value(settings.rules_file, "min_message_length", number, settings)
            await message.answer(f"Мин. длина сообщения сохранена: {number}")
            await send_rules_menu(message)

    dispatcher.include_router(router)
