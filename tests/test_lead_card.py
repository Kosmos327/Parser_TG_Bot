from datetime import datetime, timezone

from app.models import LeadCRMStatus, LeadEvent
from app.notifier import build_lead_card_text


def test_build_lead_card_text_contains_status_login_comment() -> None:
    lead = LeadEvent(
        source_title="Источник",
        source_id=1,
        message_id=2,
        sender_id=3,
        sender_username="client",
        sender_first_name="Иван",
        text="Сообщение",
        message_link="https://t.me/c/1/2",
        matched_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    crm = LeadCRMStatus(
        lead_id=lead.lead_id,
        lead_key=lead.lead_key,
        status="in_work",
        created_at=lead.matched_at,
        updated_at=lead.matched_at,
        comment="созвониться",
    )
    text = build_lead_card_text(lead, crm)
    assert "В работе" in text
    assert "@client" in text
    assert "созвониться" in text


def test_build_lead_card_text_escapes_html() -> None:
    lead = LeadEvent(
        source_title="<src>",
        source_id=1,
        message_id=2,
        sender_id=3,
        sender_username="client",
        sender_first_name="<Иван>",
        text="<script>",
        message_link="https://x/?a=<b>",
        matched_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    crm = LeadCRMStatus(
        lead_id=lead.lead_id,
        lead_key=lead.lead_key,
        status="new",
        created_at=lead.matched_at,
        updated_at=lead.matched_at,
        comment="<comment>",
    )
    text = build_lead_card_text(lead, crm)
    assert "&lt;script&gt;" in text
    assert "&lt;comment&gt;" in text
    assert "<script>" not in text
