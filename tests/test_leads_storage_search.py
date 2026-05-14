from datetime import datetime, timezone

from app.crm_storage import set_comment
from app.leads_storage import append_lead, get_leads_page, search_leads
from app.models import LeadEvent


def _lead(message_id: int, text: str, username: str | None = None) -> LeadEvent:
    return LeadEvent(
        source_title="Источник",
        source_id=100,
        message_id=message_id,
        sender_id=message_id,
        sender_username=username,
        sender_first_name="Имя",
        text=text,
        message_link=f"https://t.me/c/100/{message_id}",
        matched_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )


def test_get_leads_page_returns_requested_page(tmp_path) -> None:
    path = str(tmp_path / "leads.jsonl")
    append_lead(path, _lead(1, "one"))
    append_lead(path, _lead(2, "two"))
    page, total_pages = get_leads_page(path, 2, page_size=1)
    assert total_pages == 2
    assert page[0].message_id == 1


def test_search_leads_finds_by_text(tmp_path) -> None:
    path = str(tmp_path / "leads.jsonl")
    crm_path = str(tmp_path / "crm.json")
    append_lead(path, _lead(1, "Нужна оптимизация налогов"))
    leads, _ = search_leads(path, crm_path, "налогов")
    assert [lead.message_id for lead in leads] == [1]


def test_search_leads_finds_by_username(tmp_path) -> None:
    path = str(tmp_path / "leads.jsonl")
    crm_path = str(tmp_path / "crm.json")
    append_lead(path, _lead(1, "text", "client_user"))
    leads, _ = search_leads(path, crm_path, "CLIENT")
    assert [lead.message_id for lead in leads] == [1]


def test_search_leads_finds_by_crm_comment(tmp_path) -> None:
    path = str(tmp_path / "leads.jsonl")
    crm_path = str(tmp_path / "crm.json")
    lead = _lead(1, "text")
    append_lead(path, lead)
    set_comment(crm_path, lead.lead_id, lead.lead_key, "важный vip клиент")
    leads, _ = search_leads(path, crm_path, "VIP")
    assert [item.message_id for item in leads] == [1]
