from datetime import datetime, timezone

from app.models import LeadEvent
from app.notifier import TELEGRAM_SAFE_MESSAGE_LENGTH, build_lead_notification_text


def _lead(**overrides) -> LeadEvent:
    values = {
        "source_title": "Налоги & бизнес",
        "source_id": -1001234567890,
        "message_id": 10,
        "sender_id": 123456789,
        "sender_username": "client_user",
        "sender_first_name": "Иван <ИП>",
        "text": "Подскажите, как понизить налоги для ООО?",
        "message_link": "https://t.me/c/1234567890/10?x=<tag>",
        "matched_at": datetime(2026, 5, 13, 17, 30, 45, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return LeadEvent(**values)


def test_build_lead_notification_text_formats_application_for_admin() -> None:
    message = build_lead_notification_text(_lead())

    assert message == (
        "🆕 <b>Найден потенциальный клиент</b>\n\n"
        "<b>Логин:</b> @client_user\n"
        "<b>Имя:</b> Иван &lt;ИП&gt;\n"
        "<b>ID пользователя:</b> 123456789\n\n"
        "<b>Что написал:</b>\n"
        "Подскажите, как понизить налоги для ООО?\n\n"
        "<b>Дата и время:</b> 13.05.2026 17:30\n\n"
        "<b>Источник:</b> Налоги &amp; бизнес\n"
        "<b>Ссылка:</b> https://t.me/c/1234567890/10?x=&lt;tag&gt;\n"
        "<b>Скоринг:</b> нет\n"
        "<b>Совпадения:</b> нет"
    )


def test_build_lead_notification_text_uses_fallbacks() -> None:
    message = build_lead_notification_text(
        _lead(
            source_title=None,
            sender_id=None,
            sender_username=None,
            sender_first_name=None,
            message_link=None,
        )
    )

    assert "<b>Логин:</b> нет" in message
    assert "<b>Имя:</b> нет" in message
    assert "<b>ID пользователя:</b> нет" in message
    assert "<b>Источник:</b> неизвестно" in message
    assert "<b>Ссылка:</b> нет публичной ссылки" in message


def test_build_lead_notification_text_escapes_user_text() -> None:
    message = build_lead_notification_text(_lead(text="<script>alert('&')</script>"))

    assert "&lt;script&gt;alert(&#x27;&amp;&#x27;)&lt;/script&gt;" in message
    assert "<script>" not in message


def test_build_lead_notification_text_respects_max_text_length() -> None:
    message = build_lead_notification_text(_lead(text="1234567890"), max_text_length=5)

    assert "1234…" in message
    assert "<b>Что написал:</b>\n1234…\n\n" in message


def test_build_lead_notification_text_fits_telegram_safe_limit() -> None:
    message = build_lead_notification_text(_lead(text="очень длинный текст " * 1000))

    assert len(message) <= TELEGRAM_SAFE_MESSAGE_LENGTH
    assert "…" in message
