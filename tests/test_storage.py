from datetime import datetime, timezone

from app.leads_storage import append_lead, count_leads, get_last_leads
from app.models import LeadEvent


def _lead(message_id: int, text: str) -> LeadEvent:
    return LeadEvent(
        source_title="Test chat",
        source_id=-1001234567890,
        message_id=message_id,
        sender_id=123,
        sender_username=None,
        sender_first_name="Иван",
        text=text,
        message_link=f"https://t.me/c/1234567890/{message_id}",
        matched_at=datetime(2026, 5, 13, 12, 0, message_id, tzinfo=timezone.utc),
    )


def test_append_lead_and_get_last_leads(tmp_path) -> None:
    path = tmp_path / "nested" / "leads.jsonl"

    append_lead(str(path), _lead(1, "первая заявка"))
    append_lead(str(path), _lead(2, "вторая заявка"))

    leads = get_last_leads(str(path), limit=1)

    assert len(leads) == 1
    assert leads[0].message_id == 2
    assert leads[0].text == "вторая заявка"
    assert leads[0].matched_at == datetime(2026, 5, 13, 12, 0, 2, tzinfo=timezone.utc)


def test_count_leads(tmp_path) -> None:
    path = tmp_path / "leads.jsonl"

    append_lead(str(path), _lead(1, "первая заявка"))
    append_lead(str(path), _lead(2, "вторая заявка"))

    assert count_leads(str(path)) == 2


def test_missing_file_returns_empty_results(tmp_path) -> None:
    path = tmp_path / "missing.jsonl"

    assert get_last_leads(str(path)) == []
    assert count_leads(str(path)) == 0
