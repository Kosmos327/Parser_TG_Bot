from __future__ import annotations

from html import escape

from aiogram import Bot

from app.models import LeadEvent


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


async def send_lead_notification(bot: Bot, admin_chat_id: int, lead: LeadEvent) -> None:
    source = lead.source_title or (f"ID {lead.source_id}" if lead.source_id is not None else "неизвестно")
    message_link = escape(lead.message_link) if lead.message_link else "нет публичной ссылки"
    date_text = lead.matched_at.strftime("%Y-%m-%d %H:%M:%S %Z")

    message = (
        "🚨 <b>Найдена потенциальная заявка</b>\n\n"
        f"<b>Источник:</b> {escape(source)}\n"
        f"<b>Пользователь:</b> {_format_user(lead)}\n"
        f"<b>Дата:</b> {escape(date_text)}\n\n"
        "<b>Текст:</b>\n"
        f"{escape(lead.text)}\n\n"
        f"<b>Ссылка:</b> {message_link}"
    )

    await bot.send_message(admin_chat_id, message, parse_mode="HTML", disable_web_page_preview=True)
