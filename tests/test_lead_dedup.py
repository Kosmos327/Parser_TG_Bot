from datetime import datetime, timedelta, timezone

from app.lead_dedup import is_duplicate_lead, lead_fingerprint
from app.leads_storage import append_lead
from app.models import LeadEvent


def _lead(text: str, username: str | None, sender_id: int | None, hours_ago: int = 1) -> LeadEvent:
    return LeadEvent(
        source_title="s",
        source_id=1,
        message_id=hours_ago,
        sender_id=sender_id,
        sender_username=username,
        sender_first_name=None,
        text=text,
        message_link=None,
        matched_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )


def test_same_user_similar_text_is_duplicate(tmp_path) -> None:
    path = tmp_path / "leads.jsonl"
    append_lead(str(path), _lead("Нужна консультация по налогам для ИП", "user", 42))
    duplicate, original = is_duplicate_lead(str(path), "нужна консультация по налогам для ип!", "user", 42, 72, 0.9)
    assert duplicate
    assert original == "1:1"


def test_other_user_other_text_is_not_duplicate(tmp_path) -> None:
    path = tmp_path / "leads.jsonl"
    append_lead(str(path), _lead("Нужна консультация по налогам", "user", 42))
    duplicate, _ = is_duplicate_lead(str(path), "Ищу дизайнера сайта", "other", 43, 72, 0.9)
    assert not duplicate


def test_old_lead_outside_window_is_not_duplicate(tmp_path) -> None:
    path = tmp_path / "leads.jsonl"
    append_lead(str(path), _lead("Нужна консультация по налогам", "user", 42, hours_ago=100))
    duplicate, _ = is_duplicate_lead(str(path), "Нужна консультация по налогам", "user", 42, 72, 0.9)
    assert not duplicate


def test_fingerprint_stable() -> None:
    assert lead_fingerprint("Привет!!!", "User", None) == lead_fingerprint(" привет ", "user", None)
