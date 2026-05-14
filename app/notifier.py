from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.lead_index import ensure_lead_identity
from app.models import LeadCRMStatus, LeadEvent

TELEGRAM_SAFE_MESSAGE_LENGTH = 3900


def _escape_field(value: object) -> str:
    return escape(str(value))


def _format_login(username: str | None) -> str:
    if not username:
        return "нет"

    username_text = str(username).lstrip("@")
    if not username_text:
        return "нет"

    return f"@{escape(username_text)}"


def _format_optional_field(value: object, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    return _escape_field(value)


def _truncate_text(text: str, max_length: int | None) -> str:
    if max_length is None or max_length < 1 or len(text) <= max_length:
        return text

    if max_length == 1:
        return "…"
    return f"{text[: max_length - 1]}…"


STATUS_TITLES = {
    "new": "Новый",
    "in_work": "В работе",
    "processed": "Обработан",
    "no_target": "Нецелевой",
}


def build_lead_actions_markup(lead: LeadEvent) -> InlineKeyboardMarkup:
    lead = ensure_lead_identity(lead)
    key = lead.lead_key
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟡 В работу", callback_data=f"lead:in_work:{key}"),
                InlineKeyboardButton(text="✅ Обработан", callback_data=f"lead:processed:{key}"),
            ],
            [
                InlineKeyboardButton(text="💬 Комментарий", callback_data=f"lead:comment:{key}"),
                InlineKeyboardButton(text="📅 Дата обработки", callback_data=f"lead:date:{key}"),
            ],
            [
                InlineKeyboardButton(text="❌ Нецелевой", callback_data=f"lead:no_target:{key}"),
                InlineKeyboardButton(text="📄 Карточка", callback_data=f"lead:card:{key}"),
            ],
        ]
    )


def _format_assignee(crm: LeadCRMStatus) -> str:
    if crm.assigned_to_username:
        return _format_login(crm.assigned_to_username)
    if crm.assigned_to_user_id is not None:
        return _escape_field(crm.assigned_to_user_id)
    return "нет"


def build_lead_card_text(lead: LeadEvent, crm: LeadCRMStatus) -> str:
    lead = ensure_lead_identity(lead)
    text = _truncate_text(lead.text.strip(), 1200)
    comment = _truncate_text(crm.comment or "нет", 1000)
    date_found = escape(lead.matched_at.strftime("%d.%m.%Y %H:%M"))
    source = _format_optional_field(lead.source_title, "неизвестно")
    message_link = _format_optional_field(lead.message_link, "нет публичной ссылки")
    return (
        "📄 <b>Карточка лида</b>\n\n"
        f"<b>Статус:</b> {escape(STATUS_TITLES.get(crm.status, crm.status))}\n"
        f"<b>Логин:</b> {_format_login(lead.sender_username)}\n"
        f"<b>Имя:</b> {_format_optional_field(lead.sender_first_name, 'нет')}\n"
        f"<b>ID пользователя:</b> {_format_optional_field(lead.sender_id, 'нет')}\n"
        f"<b>Дата найденного сообщения:</b> {date_found}\n"
        f"<b>Дата обработки:</b> {escape(crm.processed_date or 'нет')}\n"
        f"<b>Ответственный:</b> {_format_assignee(crm)}\n"
        f"<b>Источник:</b> {source}\n"
        f"<b>Ссылка:</b> {message_link}\n\n"
        "<b>Сообщение:</b>\n"
        f"{escape(text) if text else 'нет'}\n\n"
        "<b>Комментарий:</b>\n"
        f"{escape(comment)}"
    )


def _build_message(lead: LeadEvent, text: str) -> str:
    login = _format_login(lead.sender_username)
    first_name = _format_optional_field(lead.sender_first_name, "нет")
    sender_id = _format_optional_field(lead.sender_id, "нет")
    source = _format_optional_field(lead.source_title, "неизвестно")
    message_link = _format_optional_field(lead.message_link, "нет публичной ссылки")
    date_text = escape(lead.matched_at.strftime("%d.%m.%Y %H:%M"))
    message_text = escape(text)

    return (
        "🆕 <b>Найден потенциальный клиент</b>\n\n"
        f"<b>Логин:</b> {login}\n"
        f"<b>Имя:</b> {first_name}\n"
        f"<b>ID пользователя:</b> {sender_id}\n\n"
        "<b>Что написал:</b>\n"
        f"{message_text}\n\n"
        f"<b>Дата и время:</b> {date_text}\n\n"
        f"<b>Источник:</b> {source}\n"
        f"<b>Ссылка:</b> {message_link}"
    )


def _fit_message_to_telegram_limit(lead: LeadEvent, text: str) -> str:
    message = _build_message(lead, text)
    if len(message) <= TELEGRAM_SAFE_MESSAGE_LENGTH:
        return message

    low = 0
    high = len(text)
    best_message = _build_message(lead, "")

    while low <= high:
        middle = (low + high) // 2
        shortened_text = _truncate_text(text, middle)
        candidate = _build_message(lead, shortened_text)
        if len(candidate) <= TELEGRAM_SAFE_MESSAGE_LENGTH:
            best_message = candidate
            low = middle + 1
        else:
            high = middle - 1

    if len(best_message) <= TELEGRAM_SAFE_MESSAGE_LENGTH:
        return best_message

    return best_message[:TELEGRAM_SAFE_MESSAGE_LENGTH]


def build_lead_notification_text(
    lead: LeadEvent,
    max_text_length: int | None = None,
) -> str:
    text = _truncate_text(lead.text, max_text_length)
    return _fit_message_to_telegram_limit(lead, text)


async def send_lead_notification(
    bot: Bot,
    admin_chat_id: int,
    lead: LeadEvent,
    max_text_length: int | None = None,
) -> None:
    lead = ensure_lead_identity(lead)
    message = build_lead_notification_text(lead, max_text_length=max_text_length)
    await bot.send_message(
        admin_chat_id,
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=build_lead_actions_markup(lead),
    )
