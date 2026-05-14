from __future__ import annotations

import asyncio
from hashlib import sha1
from time import time
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from html import escape
import logging
from typing import Any

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telethon import utils

from app.config import Settings, risky_settings_warnings
from app.crm_storage import get_or_create_status, get_stats as get_crm_stats, load_crm, set_comment, set_processed_date, update_status
from app.dialogs import dialog_info_from_entity, format_dialog_bot_item, is_source_dialog_allowed
from app.leads_storage import count_leads, get_all_leads, get_last_leads, get_lead_by_key, search_leads
from app.models import LeadEvent
from app.notifier import STATUS_TITLES, build_lead_actions_markup, build_lead_card_text
from app.rules_storage import LIST_FIELDS, add_rule_item, remove_rule_item, save_rules, set_rule_value
from app.source_discovery import (
    export_candidates_txt,
    filter_joinable_candidates,
    load_candidates,
    mark_candidate_status,
    merge_candidates,
    parse_sources_text,
    save_candidates,
    search_sources,
)
from app.source_joiner import join_sources_limited
from app.state import ParserState

SOURCE_JOIN_START_ALL = "source_join:start_all"
SOURCE_JOIN_START_SELECTIVE = "source_join:start_selective"
SOURCE_JOIN_CANCEL = "source_join:cancel"

logger = logging.getLogger(__name__)

CATEGORY_TITLES = {
    "trigger_words": "Слова-триггеры",
    "exclude_words": "Стоп-слова",
    "include_source_titles": "Разрешённые источники",
    "exclude_source_titles": "Исключённые источники",
}


PendingState = dict[str, Any]


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
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Найти новые источники", callback_data="sources:find")],
            [InlineKeyboardButton(text="⚙️ Правила парсинга", callback_data="rules:menu")],
            [InlineKeyboardButton(text="📋 Лиды / Воронка", callback_data="crm:menu")],
        ]
    )


def _format_help() -> str:
    return (
        "Бот управления Telegram lead parser.\n\n"
        "Команды:\n"
        "/status — статус парсера\n"
        "/pause — выключить обработку новых лидов\n"
        "/resume — включить обработку новых лидов\n"
        "/last — последние 5 заявок\n"
        "/crm — меню лидов и воронки\n"
        "/pipeline — воронка продаж\n"
        "/leads_new, /leads_work, /leads_processed, /leads_no_target, /leads_all — списки лидов\n"
        "/lead_search — поиск по лидам\n"
        "/last 10 — последние 10 заявок, максимум 20\n"
        "/stats — статистика сохранённых заявок\n"
        "/keywords — текущие слова-триггеры\n"
        "/sources — текущие источники\n"
        "/rules — открыть правила парсинга\n"
        "🔎 Найти новые источники\n"
        "/find_sources — поиск новых источников\n"
        "/source_candidates — найденные кандидаты\n"
        "/source_values — строка для SOURCE_CHATS\n"
        "/join_debug — диагностика подписки на источники\n"
        "/config — безопасная конфигурация\n"
        "/health — состояние polling, Telethon и парсера\n"
        "/dialogs — показать чаты/каналы, доступные Telethon-сессии\n"
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
        f"crm_file: {escape(settings.crm_file)}",
        f"leads_page_size: {settings.leads_page_size}",
        f"dedup_file: {escape(settings.dedup_file)}",
        f"log_level: {escape(settings.log_level)}",
        f"source_search_limit: {settings.source_search_limit}",
        f"join_batch_limit: {settings.join_batch_limit}",
        f"join_delay_seconds: {settings.join_delay_seconds}",
        f"exclude_private_chats: {_format_bool(settings.exclude_private_chats)}",
        f"source_candidates_file: {escape(settings.source_candidates_file)}",
        f"source_export_file: {escape(settings.source_export_file)}",
    ]
    warnings = risky_settings_warnings(settings)
    if warnings:
        parts.append("<b>Предупреждения безопасности</b>")
        parts.extend(f"⚠️ {escape(warning)}" for warning in warnings)
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


def _is_telethon_connected(client: Any | None) -> bool:
    if client is None:
        return False

    try:
        return bool(client.is_connected())
    except Exception:
        return False


async def _format_available_dialogs(client: Any, exclude_private_chats: bool = True, limit: int = 20, max_length: int = 3800) -> str:
    parts = ["<b>📡 Доступные источники</b>"]
    count = 0
    has_more = False

    async for dialog in client.iter_dialogs(limit=(limit * 5) + 1):
        if count >= limit:
            has_more = True
            break

        if not is_source_dialog_allowed(dialog, exclude_private_chats):
            continue

        entity = dialog.entity
        info = dialog_info_from_entity(entity, peer_id=utils.get_peer_id(entity))
        item = format_dialog_bot_item(info, count + 1)
        candidate = "\n\n".join([*parts, item])
        if len(candidate) > max_length:
            has_more = True
            break
        parts.append(item)
        count += 1

    if count == 0:
        return "<b>📡 Доступные источники</b>\n\nДиалоги не найдены."

    if has_more:
        footer = (
            f"Показаны первые {count}. Полный список можно получить командой:\n"
            "<code>python list_dialogs.py --limit 500</code>"
        )
        candidate = "\n\n".join([*parts, footer])
        if len(candidate) <= max_length:
            return candidate
    return "\n\n".join(parts)


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
        f"Matched count: {state.matched_count}\n"
        f"Source join: {'in progress' if state.source_join_in_progress else 'idle'}\n"
        f"Source join last report: {escape(state.source_join_last_report or 'нет')}"
        + escape(_crm_status_appendix(settings))
    )


def _user_key(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None



def _find_sources_prompt() -> str:
    return (
        "Напишите слова/фразы, по которым нужно искать каналы. Можно несколько строк, например:\n"
        "налоги\n"
        "бухгалтерия\n"
        "ип"
    )


def _subscription_choice_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подписаться на все найденные", callback_data="sources:join_all")],
            [InlineKeyboardButton(text="✍️ Выборочно", callback_data="sources:join_selective")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="sources:cancel")],
        ]
    )


def _continue_search_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, продолжить поиск", callback_data="sources:continue")],
            [InlineKeyboardButton(text="❌ Нет, перейти к подписке", callback_data="sources:subscribe_step")],
        ]
    )


def _confirm_join_markup(mode: str) -> InlineKeyboardMarkup:
    callback_data = SOURCE_JOIN_START_ALL if mode == "all" else SOURCE_JOIN_START_SELECTIVE
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Начать подписку", callback_data=callback_data)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=SOURCE_JOIN_CANCEL)],
        ]
    )


def _parse_source_queries(text: str) -> list[str]:
    queries: list[str] = []
    for line in text.splitlines():
        query = line.strip()
        if not query:
            continue
        if len(query) > 100:
            query = query[:100].strip()
        queries.append(query)
        if len(queries) >= 10:
            break
    return queries


def _candidate_username(candidate: dict[str, Any]) -> str | None:
    value = candidate.get("username") or candidate.get("source_chats_value")
    if not value:
        return None
    username = str(value).strip()
    if username.startswith("@"):
        return username
    if username and not username.lstrip("-").isdigit():
        return f"@{username}"
    return None


def _format_join_report(result: dict[str, Any]) -> str:
    stopped = "Да" if result.get("stopped_by_floodwait") else "Нет"
    if result.get("stopped_by_floodwait") and result.get("floodwait_seconds") is not None:
        stopped = f"Да ({result['floodwait_seconds']} секунд)"
    return (
        "Подписка завершена.\n\n"
        f"Успешно: {len(result['joined'])}\n"
        f"Уже были подписаны: {len(result['already_joined'])}\n"
        f"Требуют ручного действия: {len(result['manual_required'])}\n"
        f"Ошибки: {len(result['failed'])}\n"
        f"Остановлено FloodWait: {stopped}"
    )


def _write_sources_txt(path: str, values: list[str]) -> str:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(values) + ("\n" if values else ""), encoding="utf-8")
    return str(output_path)


STATUS_FILTERS = {
    "new": "new",
    "work": "in_work",
    "done": "processed",
    "bad": "no_target",
}
FILTER_TITLES = {
    "new": "Необработанные лиды",
    "work": "В работе",
    "done": "Обработанные",
    "bad": "Нецелевые",
    "all": "Все лиды",
}


def _crm_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Необработанные лиды", callback_data="leads:l:new:1")],
            [InlineKeyboardButton(text="🟡 В работе", callback_data="leads:l:work:1")],
            [InlineKeyboardButton(text="✅ Обработанные", callback_data="leads:l:done:1")],
            [InlineKeyboardButton(text="❌ Нецелевые", callback_data="leads:l:bad:1")],
            [InlineKeyboardButton(text="📚 Все лиды", callback_data="leads:l:all:1")],
            [InlineKeyboardButton(text="🔍 Поиск по лидам", callback_data="leads:search")],
            [InlineKeyboardButton(text="📊 Воронка продаж", callback_data="crm:pipeline")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="rules:back")],
        ]
    )


def _crm_menu_text() -> str:
    return "📋 <b>Лиды / Воронка</b>"


def _crm_stats_text(settings: Settings) -> str:
    stats = get_crm_stats(settings.crm_file)
    total_leads = count_leads(settings.leads_file)
    known = stats.get("total", 0)
    implicit_new = max(0, total_leads - known)
    new_count = stats.get("new", 0) + implicit_new
    total = known + implicit_new
    return (
        "📊 <b>Воронка продаж</b>\n\n"
        f"Новые / необработанные: {new_count}\n"
        f"В работе: {stats.get('in_work', 0)}\n"
        f"Обработаны: {stats.get('processed', 0)}\n"
        f"Нецелевые: {stats.get('no_target', 0)}\n"
        f"Всего: {total}"
    )


def _pipeline_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Необработанные", callback_data="leads:l:new:1")],
            [InlineKeyboardButton(text="🟡 В работе", callback_data="leads:l:work:1")],
            [InlineKeyboardButton(text="✅ Обработанные", callback_data="leads:l:done:1")],
            [InlineKeyboardButton(text="❌ Нецелевые", callback_data="leads:l:bad:1")],
            [InlineKeyboardButton(text="📚 Все лиды", callback_data="leads:l:all:1")],
            [InlineKeyboardButton(text="🔙 В меню CRM", callback_data="crm:menu")],
        ]
    )


def _lead_user_short(lead: LeadEvent) -> str:
    if lead.sender_username:
        return f"@{lead.sender_username}"
    if lead.sender_first_name:
        return lead.sender_first_name
    if lead.sender_id is not None:
        return f"ID {lead.sender_id}"
    return "неизвестно"


def _short_text(text: str, limit: int = 50) -> str:
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 1]}…"


def _filter_leads_for_crm(settings: Settings, filter_code: str) -> list[LeadEvent]:
    leads = get_all_leads(settings.leads_file)
    if filter_code == "all":
        return leads
    crm = load_crm(settings.crm_file)
    desired = STATUS_FILTERS[filter_code]
    result: list[LeadEvent] = []
    for lead in leads:
        status = crm.get(lead.lead_id).status if crm.get(lead.lead_id) else "new"
        if status == desired:
            result.append(lead)
    return result


def _paginate(items: list[LeadEvent], page: int, page_size: int) -> tuple[list[LeadEvent], int, int]:
    page_size = max(1, min(page_size, 20))
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    return items[start : start + page_size], page, total_pages


def _build_leads_list_text(settings: Settings, leads: list[LeadEvent], page: int, total_pages: int, title: str) -> str:
    crm = load_crm(settings.crm_file)
    lines = [f"📋 <b>{escape(title)}</b>", f"Страница {page} из {total_pages}"]
    if not leads:
        lines.append("\nЛиды не найдены.")
        return "\n".join(lines)
    lines.append("")
    for index, lead in enumerate(leads, start=1):
        status = crm.get(lead.lead_id).status if crm.get(lead.lead_id) else "new"
        lines.append(
            f"{index}. [{escape(STATUS_TITLES.get(status, status))}] "
            f"{escape(_lead_user_short(lead))} — {escape(_short_text(lead.text))}"
        )
    return "\n".join(lines)


def _build_leads_list_markup(filter_code: str, page: int, total_pages: int, leads: list[LeadEvent]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"leads:l:{filter_code}:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"leads:l:{filter_code}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"leads:l:{filter_code}:{page}")])
    card_buttons = [InlineKeyboardButton(text=f"📄 {index}", callback_data=f"leads:card:{lead.lead_key}") for index, lead in enumerate(leads, start=1)]
    for start in range(0, len(card_buttons), 5):
        rows.append(card_buttons[start : start + 5])
    rows.append([InlineKeyboardButton(text="🔙 В меню CRM", callback_data="crm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_search_markup(search_id: str, page: int, total_pages: int, leads: list[LeadEvent]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"leads:s:{search_id}:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"leads:s:{search_id}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"leads:s:{search_id}:{page}")])
    cards = [InlineKeyboardButton(text=f"📄 {index}", callback_data=f"leads:card:{lead.lead_key}") for index, lead in enumerate(leads, start=1)]
    for start in range(0, len(cards), 5):
        rows.append(cards[start : start + 5])
    rows.append([InlineKeyboardButton(text="🔙 В меню CRM", callback_data="crm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _crm_status_appendix(settings: Settings) -> str:
    stats = get_crm_stats(settings.crm_file)
    total_leads = count_leads(settings.leads_file)
    implicit_new = max(0, total_leads - stats.get("total", 0))
    return (
        f"\nCRM_FILE: {settings.crm_file}\n"
        f"CRM новые: {stats.get('new', 0) + implicit_new}\n"
        f"CRM в работе: {stats.get('in_work', 0)}\n"
        f"CRM обработаны: {stats.get('processed', 0)}\n"
        f"CRM нецелевые: {stats.get('no_target', 0)}"
    )

def register_bot_handlers(
    dispatcher: Dispatcher,
    settings: Settings,
    state: ParserState,
    telethon_client: Any | None = None,
) -> None:
    router = Router()
    pending: dict[int, PendingState] = {}
    search_queries: dict[str, str] = {}

    async def send_rules_menu(message: Message) -> None:
        await message.answer(_format_rules_menu(state), reply_markup=_rules_menu_markup(state), parse_mode="HTML")

    async def edit_rules_menu(callback: CallbackQuery) -> None:
        if callback.message:
            await callback.message.edit_text(
                _format_rules_menu(state), reply_markup=_rules_menu_markup(state), parse_mode="HTML"
            )

    async def answer_category(message: Message, category: str) -> None:
        await message.answer(_format_category(category, state), reply_markup=_category_markup(category), parse_mode="HTML")


    async def show_crm_menu(message: Message) -> None:
        await message.answer(_crm_menu_text(), reply_markup=_crm_menu_markup(), parse_mode="HTML")

    async def show_pipeline_message(message: Message) -> None:
        await message.answer(_crm_stats_text(settings), reply_markup=_pipeline_markup(), parse_mode="HTML")

    async def show_leads_list_message(message: Message, filter_code: str, page: int = 1) -> None:
        leads, actual_page, total_pages = _paginate(
            _filter_leads_for_crm(settings, filter_code), page, settings.leads_page_size
        )
        await message.answer(
            _build_leads_list_text(settings, leads, actual_page, total_pages, FILTER_TITLES[filter_code]),
            reply_markup=_build_leads_list_markup(filter_code, actual_page, total_pages, leads),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def edit_leads_list_callback(callback: CallbackQuery, filter_code: str, page: int = 1) -> None:
        leads, actual_page, total_pages = _paginate(
            _filter_leads_for_crm(settings, filter_code), page, settings.leads_page_size
        )
        if callback.message:
            await callback.message.edit_text(
                _build_leads_list_text(settings, leads, actual_page, total_pages, FILTER_TITLES[filter_code]),
                reply_markup=_build_leads_list_markup(filter_code, actual_page, total_pages, leads),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

    async def show_lead_card(message: Message, lead_key: str) -> None:
        lead = get_lead_by_key(settings.leads_file, lead_key)
        if not lead:
            await message.answer("Лид не найден.")
            return
        crm = get_or_create_status(settings.crm_file, lead.lead_id, lead.lead_key, lead.matched_at)
        await message.answer(
            build_lead_card_text(lead, crm),
            reply_markup=build_lead_actions_markup(lead),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def edit_lead_card(callback: CallbackQuery, lead_key: str) -> None:
        lead = get_lead_by_key(settings.leads_file, lead_key)
        if not lead:
            await callback.answer("Лид не найден.", show_alert=True)
            return
        crm = get_or_create_status(settings.crm_file, lead.lead_id, lead.lead_key, lead.matched_at)
        if callback.message:
            await callback.message.edit_text(
                build_lead_card_text(lead, crm),
                reply_markup=build_lead_actions_markup(lead),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

    async def show_search_results_message(message: Message, search_id: str, query: str, page: int = 1) -> None:
        leads, total_pages = search_leads(settings.leads_file, settings.crm_file, query, page, settings.leads_page_size)
        text = _build_leads_list_text(settings, leads, page, total_pages, f"Поиск: {query}")
        await message.answer(
            text,
            reply_markup=_build_search_markup(search_id, page, total_pages, leads),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    async def start_find_sources(message: Message) -> None:
        if telethon_client is None or not _is_telethon_connected(telethon_client):
            await message.answer("Telethon client недоступен или не подключён. Проверьте /health.")
            return
        user_id = _user_key(message)
        if user_id is not None:
            pending[user_id] = {"action": "find_sources_queries", "category": ""}
        await message.answer(_find_sources_prompt())

    async def run_source_search(message: Message, queries: list[str]) -> None:
        await message.answer(f"Ищу источники по {len(queries)} запросам. Лимит: {settings.source_search_limit} на запрос.")
        try:
            found = await search_sources(telethon_client, queries, settings.source_search_limit)
            existing = load_candidates(settings.source_candidates_file)
            merged = merge_candidates(existing, found)
            save_candidates(merged, settings.source_candidates_file)
            export_path = export_candidates_txt(merged, settings.source_export_file)
        except Exception as exc:
            state.last_error = str(exc)
            await message.answer(f"Не удалось найти источники: {escape(str(exc))}", parse_mode="HTML")
            return

        public_count = len([candidate for candidate in merged if _candidate_username(candidate)])
        if Path(export_path).exists() and Path(export_path).stat().st_size > 0:
            await message.answer_document(FSInputFile(export_path, filename="source_candidates.txt"))
        await message.answer(
            f"Нашёл {public_count} источников с публичным username. Файл приложен.\nПродолжить поиск?",
            reply_markup=_continue_search_markup(),
        )

    async def ask_subscription_choice(message: Message) -> None:
        await message.answer("Подписаться на найденные источники?", reply_markup=_subscription_choice_markup())

    async def prepare_join_all(message: Message) -> None:
        candidates = filter_joinable_candidates(load_candidates(settings.source_candidates_file))
        sources = [username for candidate in candidates if (username := _candidate_username(candidate))]
        if not sources:
            await message.answer("Нет найденных username-источников, доступных для автоматической подписки.")
            return
        user_id = _user_key(message)
        if user_id is not None:
            pending[user_id] = {"action": "confirm_join_all", "category": "", "sources": sources}
        await message.answer(
            f"Принял {len(sources)} источников.\n"
            "Подписаться безопасной партией?\n"
            f"Максимум за запуск: {settings.join_batch_limit}\n"
            f"Задержка между подписками: {settings.join_delay_seconds} секунд",
            reply_markup=_confirm_join_markup("all"),
        )

    async def prepare_selective_join(message: Message) -> None:
        user_id = _user_key(message)
        if user_id is not None:
            pending[user_id] = {"action": "selective_sources", "category": ""}
        await message.answer(
            "Пришлите список каналов, на которые нужно подписаться. Можно столбиком:\n"
            "@channel1\n@channel2\nhttps://t.me/channel3"
        )

    async def run_join_background(bot_obj: Any, chat_id: int, sources: list[str], *, already_marked_started: bool = False) -> None:
        if state.source_join_in_progress and not already_marked_started:
            await bot_obj.send_message(chat_id, "Подписка уже выполняется. Дождитесь завершения.")
            return
        state.source_join_in_progress = True
        state.source_join_started_at = datetime.now(timezone.utc)
        state.source_join_last_report = f"started selective join: {len(sources)} sources"
        attempted = 0

        async def progress(source: str, status: str) -> None:
            nonlocal attempted
            attempted += 1
            mark_candidate_status(
                settings.source_candidates_file,
                source,
                "joined" if status in {"joined", "already_joined"} else ("manual_required" if status == "manual_required" else "failed"),
                None if status in {"joined", "already_joined"} else status,
            )
            state.source_join_last_report = f"обработано {attempted}: {source} — {status}"
            logger.info("source join attempt source=%s status=%s attempted=%s", source, status, attempted)
            if attempted == 1 or attempted % 5 == 0:
                await bot_obj.send_message(chat_id, state.source_join_last_report)

        try:
            result = await join_sources_limited(
                telethon_client,
                sources,
                delay_seconds=settings.join_delay_seconds,
                max_join=settings.join_batch_limit,
                status_callback=progress,
            )
            report = _format_join_report(result)
            state.source_join_last_report = report
            await bot_obj.send_message(chat_id, report)
            manual_sources = [item["source"] for item in result["manual_required"] if isinstance(item, dict) and item.get("source")]
            if manual_sources:
                manual_path = _write_sources_txt("data/manual_required_sources.txt", manual_sources)
                await bot_obj.send_document(
                    chat_id,
                    FSInputFile(manual_path, filename="manual_required_sources.txt"),
                    caption=(
                        "На эти источники не удалось подписаться автоматически. Возможно, там капча, "
                        "заявка на вступление или ограничение. Подпишитесь и пройдите проверку вручную."
                    ),
                )
            failed_lines = [f"{item.get('source')}: {item.get('error')}" for item in result["failed"] if isinstance(item, dict)]
            if failed_lines:
                failed_path = _write_sources_txt("data/failed_join_sources.txt", failed_lines)
                await bot_obj.send_document(chat_id, FSInputFile(failed_path, filename="failed_join_sources.txt"), caption="Источники, на которые не удалось подписаться автоматически, и ошибки.")
        except Exception as exc:
            state.last_error = str(exc)
            state.source_join_last_report = f"ошибка: {exc}"
            await bot_obj.send_message(chat_id, f"Ошибка подписки: {escape(str(exc))}", parse_mode="HTML")
        finally:
            state.source_join_in_progress = False

    async def confirm_join(message: Message, sources: list[str]) -> None:
        if state.source_join_in_progress:
            await message.answer("Подписка уже выполняется. Дождитесь завершения.")
            return
        state.source_join_in_progress = True
        state.source_join_started_at = datetime.now(timezone.utc)
        state.source_join_last_report = f"started selective join: {len(sources)} sources"
        await message.answer(
            "Подписка запущена. Это может занять время. Статус можно смотреть через /status или /health."
        )
        asyncio.create_task(
            run_join_background(message.bot, message.chat.id, sources, already_marked_started=True),
            name="source-join",
        )

    @router.message(Command("start"))
    @_admin_only(settings)
    async def start(message: Message) -> None:
        await message.answer(_format_help(), reply_markup=_rules_button_markup())

    @router.message(Command("help"))
    @_admin_only(settings)
    async def help_command(message: Message) -> None:
        await message.answer(_format_help(), reply_markup=_rules_button_markup())

    @router.message(Command("find_sources"))
    @_admin_only(settings)
    async def find_sources_command(message: Message) -> None:
        await start_find_sources(message)

    @router.message(Command("source_candidates"))
    @_admin_only(settings)
    async def source_candidates_command(message: Message) -> None:
        candidates = load_candidates(settings.source_candidates_file)
        public_count = len([candidate for candidate in candidates if _candidate_username(candidate)])
        if not candidates:
            await message.answer("Кандидаты ещё не найдены. Запустите /find_sources.")
            return
        export_path = export_candidates_txt(candidates, settings.source_export_file)
        if Path(export_path).exists() and Path(export_path).stat().st_size > 0:
            await message.answer_document(FSInputFile(export_path, filename="source_candidates.txt"))
        await message.answer(f"Всего кандидатов: {len(candidates)}. С публичным username: {public_count}.")

    @router.message(Command("source_values"))
    @_admin_only(settings)
    async def source_values_command(message: Message) -> None:
        candidates = load_candidates(settings.source_candidates_file)
        values = [username for candidate in candidates if (username := _candidate_username(candidate))]
        if not values:
            await message.answer("Нет найденных публичных username для SOURCE_CHATS.")
            return
        await message.answer("SOURCE_CHATS=" + ",".join(values[:100]))

    @router.message(Command("join_debug"))
    @_admin_only(settings)
    async def join_debug_command(message: Message) -> None:
        candidates = load_candidates(settings.source_candidates_file)
        joinable = filter_joinable_candidates(candidates)
        started_at = (
            state.source_join_started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if state.source_join_started_at
            else "нет"
        )
        await message.answer(
            "<b>Source join debug</b>\n"
            f"source_join_in_progress: {state.source_join_in_progress}\n"
            f"source_join_started_at: {escape(started_at)}\n"
            f"source_join_last_report: {escape(state.source_join_last_report or 'нет')}\n"
            f"SOURCE_CANDIDATES_FILE candidates: {len(candidates)}\n"
            f"joinable: {len(joinable)}\n"
            f"JOIN_BATCH_LIMIT: {settings.join_batch_limit}\n"
            f"JOIN_DELAY_SECONDS: {settings.join_delay_seconds}",
            parse_mode="HTML",
        )

    @router.message(Command("rules"))
    @_admin_only(settings)
    async def rules_command(message: Message) -> None:
        await send_rules_menu(message)


    @router.message(Command("crm"))
    @_admin_only(settings)
    async def crm_command(message: Message) -> None:
        await show_crm_menu(message)

    @router.message(Command("pipeline"))
    @_admin_only(settings)
    async def pipeline_command(message: Message) -> None:
        await show_pipeline_message(message)

    @router.message(Command("leads_new"))
    @_admin_only(settings)
    async def leads_new_command(message: Message) -> None:
        await show_leads_list_message(message, "new", 1)

    @router.message(Command("leads_work"))
    @_admin_only(settings)
    async def leads_work_command(message: Message) -> None:
        await show_leads_list_message(message, "work", 1)

    @router.message(Command("leads_processed"))
    @_admin_only(settings)
    async def leads_processed_command(message: Message) -> None:
        await show_leads_list_message(message, "done", 1)

    @router.message(Command("leads_no_target"))
    @_admin_only(settings)
    async def leads_no_target_command(message: Message) -> None:
        await show_leads_list_message(message, "bad", 1)

    @router.message(Command("leads_all"))
    @_admin_only(settings)
    async def leads_all_command(message: Message) -> None:
        await show_leads_list_message(message, "all", 1)

    @router.message(Command("lead_search"))
    @_admin_only(settings)
    async def lead_search_command(message: Message) -> None:
        if message.from_user:
            pending[message.from_user.id] = {"action": "lead_search", "category": ""}
        await message.answer(
            "Введите текст для поиска по лидам. Можно искать по логину, имени, ID, источнику, тексту сообщения или комментарию."
        )

    @router.message(Command("status"))
    @_admin_only(settings)
    async def status(message: Message) -> None:
        await message.answer(state.status_text() + _crm_status_appendix(settings))

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

    @router.message(Command("dialogs"))
    @_admin_only(settings)
    async def dialogs(message: Message) -> None:
        if telethon_client is None:
            await message.answer("Telethon client недоступен. Запустите приложение через python -m app.main.")
            return
        if not _is_telethon_connected(telethon_client):
            await message.answer("Telethon client не подключён. Проверьте /health и перезапустите приложение при необходимости.")
            return

        try:
            text = await _format_available_dialogs(telethon_client, settings.exclude_private_chats)
        except Exception as exc:
            await message.answer(f"Не удалось получить список диалогов Telethon: {escape(str(exc))}", parse_mode="HTML")
            return

        await message.answer(text, parse_mode="HTML")


    @router.callback_query(lambda callback: callback.data == "crm:menu")
    async def crm_menu_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await callback.message.edit_text(_crm_menu_text(), reply_markup=_crm_menu_markup(), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(lambda callback: callback.data == "crm:pipeline")
    async def crm_pipeline_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await callback.message.edit_text(_crm_stats_text(settings), reply_markup=_pipeline_markup(), parse_mode="HTML")
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("leads:l:")))
    async def leads_list_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 4 or parts[2] not in FILTER_TITLES:
            await callback.answer("Неизвестный список.", show_alert=True)
            return
        await edit_leads_list_callback(callback, parts[2], int(parts[3]))
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("leads:card:")))
    async def leads_card_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        lead_key = (callback.data or "").split(":", 2)[2]
        await edit_lead_card(callback, lead_key)
        await callback.answer()

    @router.callback_query(lambda callback: callback.data == "leads:search")
    async def leads_search_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        pending[callback.from_user.id] = {"action": "lead_search", "category": ""}
        if callback.message:
            await callback.message.answer(
                "Введите текст для поиска по лидам. Можно искать по логину, имени, ID, источнику, тексту сообщения или комментарию."
            )
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("leads:s:")))
    async def leads_search_page_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 4 or parts[2] not in search_queries:
            await callback.answer("Поиск устарел.", show_alert=True)
            return
        search_id = parts[2]
        page = int(parts[3])
        query = search_queries[search_id]
        leads, total_pages = search_leads(settings.leads_file, settings.crm_file, query, page, settings.leads_page_size)
        if callback.message:
            await callback.message.edit_text(
                _build_leads_list_text(settings, leads, page, total_pages, f"Поиск: {query}"),
                reply_markup=_build_search_markup(search_id, page, total_pages, leads),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        await callback.answer()

    @router.callback_query(lambda callback: bool(callback.data and callback.data.startswith("lead:")))
    async def lead_action_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            await callback.answer("Некорректная кнопка.", show_alert=True)
            return
        action, lead_key = parts[1], parts[2]
        lead = get_lead_by_key(settings.leads_file, lead_key)
        if not lead:
            await callback.answer("Лид не найден.", show_alert=True)
            return
        username = callback.from_user.username if callback.from_user else None
        user_id = callback.from_user.id if callback.from_user else None
        if action == "in_work":
            update_status(settings.crm_file, lead.lead_id, lead.lead_key, "in_work", user_id, username)
            await edit_lead_card(callback, lead_key)
            await callback.answer("Лид взят в работу")
            return
        if action == "processed":
            update_status(settings.crm_file, lead.lead_id, lead.lead_key, "processed", user_id, username)
            await edit_lead_card(callback, lead_key)
            await callback.answer("Лид отмечен обработанным")
            return
        if action == "no_target":
            update_status(settings.crm_file, lead.lead_id, lead.lead_key, "no_target", user_id, username)
            await edit_lead_card(callback, lead_key)
            await callback.answer("Лид отмечен нецелевым")
            return
        if action == "comment":
            pending[callback.from_user.id] = {"action": "lead_comment", "category": "", "lead_key": lead_key}
            if callback.message:
                await callback.message.answer("Напишите комментарий к заявке")
            await callback.answer()
            return
        if action == "date":
            pending[callback.from_user.id] = {"action": "lead_date", "category": "", "lead_key": lead_key}
            if callback.message:
                await callback.message.answer("Отправьте дату обработки в формате ДД.ММ.ГГГГ")
            await callback.answer()
            return
        if action == "card":
            await edit_lead_card(callback, lead_key)
            await callback.answer()
            return
        await callback.answer("Неизвестное действие.", show_alert=True)

    @router.callback_query(lambda callback: callback.data == "sources:find")
    async def find_sources_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await start_find_sources(callback.message)
        await callback.answer()

    @router.callback_query(lambda callback: callback.data == "sources:continue")
    async def continue_sources_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await start_find_sources(callback.message)
        await callback.answer()

    @router.callback_query(lambda callback: callback.data == "sources:subscribe_step")
    async def subscribe_step_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await ask_subscription_choice(callback.message)
        await callback.answer()

    @router.callback_query(lambda callback: callback.data == "sources:join_all")
    async def join_all_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await prepare_join_all(callback.message)
        await callback.answer()

    @router.callback_query(lambda callback: callback.data == "sources:join_selective")
    async def join_selective_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        if callback.message:
            await prepare_selective_join(callback.message)
        await callback.answer()

    @router.callback_query(lambda callback: callback.data in {"sources:cancel", SOURCE_JOIN_CANCEL})
    async def sources_cancel_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        pending.pop(callback.from_user.id, None)
        if callback.message:
            await callback.message.answer("Сценарий источников отменён.")
        await callback.answer()

    @router.callback_query(lambda callback: callback.data in {SOURCE_JOIN_START_ALL, SOURCE_JOIN_START_SELECTIVE})
    async def confirm_join_callback(callback: CallbackQuery) -> None:
        if not is_admin_callback(callback, settings):
            await callback.answer("Нет доступа.", show_alert=True)
            return
        current = pending.pop(callback.from_user.id, {})
        sources = current.get("sources", [])
        if not sources or not callback.message:
            await callback.answer("Нет списка источников для подписки.", show_alert=True)
            return
        await callback.answer()
        await confirm_join(callback.message, list(sources))

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

        if action == "lead_comment":
            lead_key = current.get("lead_key", "")
            lead = get_lead_by_key(settings.leads_file, lead_key)
            if not lead:
                await message.answer("Лид не найден.")
                return
            set_comment(settings.crm_file, lead.lead_id, lead.lead_key, value)
            await message.answer("Комментарий сохранён.")
            await show_lead_card(message, lead_key)
            return

        if action == "lead_date":
            lead_key = current.get("lead_key", "")
            lead = get_lead_by_key(settings.leads_file, lead_key)
            if not lead:
                await message.answer("Лид не найден.")
                return
            try:
                set_processed_date(settings.crm_file, lead.lead_id, lead.lead_key, value)
            except ValueError:
                await message.answer("Ошибка: отправьте дату в формате ДД.ММ.ГГГГ.")
                pending[user_id] = current
                return
            await message.answer("Дата обработки сохранена.")
            await show_lead_card(message, lead_key)
            return

        if action == "lead_search":
            if not value:
                await message.answer("Пустой поисковый запрос не выполнен.")
                return
            search_id = sha1(f"{value}:{user_id}:{time()}".encode("utf-8")).hexdigest()[:8]
            search_queries[search_id] = value
            await show_search_results_message(message, search_id, value, 1)
            return

        if action == "find_sources_queries":
            queries = _parse_source_queries(value)
            if not queries:
                await message.answer("Не получил ни одного запроса. Отправьте слова/фразы строками.")
                await start_find_sources(message)
                return
            await run_source_search(message, queries)
            return

        if action == "selective_sources":
            sources = parse_sources_text(value)
            if not sources:
                await message.answer("Не получил ни одного публичного @username или t.me-ссылки. Пришлите список каналов ещё раз.")
                return
            warning = ""
            if len(sources) > 100:
                sources = sources[:100]
                warning = "\nСписок был больше 100 источников, взял первые 100."
            pending[user_id] = {"action": "confirm_join_selective", "category": "", "sources": sources}
            await message.answer(
                f"Принял {len(sources)} источников.{warning}\n"
                "Подписаться безопасной партией?\n"
                f"Максимум за запуск: {settings.join_batch_limit}\n"
                f"Задержка между подписками: {settings.join_delay_seconds} секунд",
                reply_markup=_confirm_join_markup("selective"),
            )
            return

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
