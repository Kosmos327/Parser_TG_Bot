from __future__ import annotations

from html import escape

from aiogram import Bot

from app.models import LeadEvent

TELEGRAM_SAFE_MESSAGE_LENGTH = 3900


def _format_user(lead: LeadEvent) -> str:
    if lead.sender_username:
        return f"@{escape(lead.sender_username)}"

    if lead.sender_first_name:
        first_name = escape(lead.sender_first_name)
        if lead.sender_id is not None:
            return f"{first_name} / ID {lead.sender_id}"
        return first_name

    if lead.sender_id is not None:
        return f"ID {lead.sender_id}"

    return "неизвестно"


def _truncate_text(text: str, max_length: int | None) -> str:
    if max_length is None or max_length < 1 or len(text) <= max_length:
        return text

    if max_length == 1:
        return "…"
    return f"{text[: max_length - 1]}…"


def _build_message(lead: LeadEvent, text: str) -> str:
    source = lead.source_title or (f"ID {lead.source_id}" if lead.source_id is not None else "неизвестно")
    message_link = escape(lead.message_link) if lead.message_link else "нет публичной ссылки"
    date_text = lead.matched_at.strftime("%Y-%m-%d %H:%M:%S %Z")

    return (
        "🚨 <b>Найдена потенциальная заявка</b>\n\n"
        f"<b>Источник:</b> {escape(source)}\n"
        f"<b>Пользователь:</b> {_format_user(lead)}\n"
        f"<b>Дата:</b> {escape(date_text)}\n\n"
        "<b>Текст:</b>\n"
        f"{escape(text)}\n\n"
        f"<b>Ссылка:</b> {message_link}"
    )


def _fit_message_to_telegram_limit(lead: LeadEvent, text: str) -> str:
    message = _build_message(lead, text)
    if len(message) <= TELEGRAM_SAFE_MESSAGE_LENGTH:
        return message

    shortened_text = text
    while shortened_text and len(message) > TELEGRAM_SAFE_MESSAGE_LENGTH:
        overflow = len(message) - TELEGRAM_SAFE_MESSAGE_LENGTH
        new_length = max(1, len(shortened_text) - overflow - 1)
        shortened_text = _truncate_text(shortened_text, new_length)
        message = _build_message(lead, shortened_text)
        if new_length == 1:
            break

    return message


async def send_lead_notification(
    bot: Bot,
    admin_chat_id: int,
    lead: LeadEvent,
    max_text_length: int | None = None,
) -> None:
    text = _truncate_text(lead.text, max_text_length)
    message = _fit_message_to_telegram_limit(lead, text)
    await bot.send_message(admin_chat_id, message, parse_mode="HTML", disable_web_page_preview=True)
