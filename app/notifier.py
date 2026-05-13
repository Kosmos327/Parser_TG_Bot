from __future__ import annotations

from html import escape

from aiogram import Bot

from app.models import LeadEvent


def _format_user(lead: LeadEvent) -> str:
    parts: list[str] = []
    if lead.sender_username:
        parts.append(f"@{escape(lead.sender_username)}")
    if lead.sender_first_name:
        parts.append(escape(lead.sender_first_name))
    if lead.sender_id is not None:
        parts.append(f"ID {lead.sender_id}")
    return " / ".join(parts) if parts else "неизвестно"


async def send_lead_notification(bot: Bot, admin_chat_id: int, lead: LeadEvent) -> None:
    source = lead.source_title or (f"ID {lead.source_id}" if lead.source_id is not None else "неизвестно")
    message_link = escape(lead.message_link) if lead.message_link else "недоступна"

    message = (
        "🚨 <b>Найдена потенциальная заявка</b>\n\n"
        f"<b>Источник:</b> {escape(source)}\n"
        f"<b>Пользователь:</b> {_format_user(lead)}\n"
        "<b>Текст:</b>\n"
        f"{escape(lead.text)}\n"
        f"<b>Ссылка:</b> {message_link}"
    )

    await bot.send_message(admin_chat_id, message, parse_mode="HTML", disable_web_page_preview=True)
