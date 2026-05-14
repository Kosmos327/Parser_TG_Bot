from datetime import datetime, timezone

import pytest

from app.crm_storage import (
    get_or_create_status,
    get_stats,
    set_comment,
    set_processed_date,
    update_status,
)


def test_get_or_create_status_creates_new(tmp_path) -> None:
    status = get_or_create_status(str(tmp_path / "crm.json"), "1:2", "abc")
    assert status.status == "new"
    assert status.lead_id == "1:2"


def test_update_status_changes_status(tmp_path) -> None:
    status = update_status(str(tmp_path / "crm.json"), "1:2", "abc", "in_work", 10, "admin")
    assert status.status == "in_work"
    assert status.assigned_to_user_id == 10
    assert status.assigned_to_username == "admin"


def test_processed_status_sets_processed_at(tmp_path) -> None:
    status = update_status(str(tmp_path / "crm.json"), "1:2", "abc", "processed")
    assert status.processed_at is not None
    assert status.processed_date == datetime.now(timezone.utc).strftime("%d.%m.%Y")


def test_set_processed_date_validates_dd_mm_yyyy(tmp_path) -> None:
    path = str(tmp_path / "crm.json")
    status = set_processed_date(path, "1:2", "abc", "14.05.2026")
    assert status.processed_date == "14.05.2026"
    with pytest.raises(ValueError):
        set_processed_date(path, "1:2", "abc", "2026-05-14")


def test_set_comment_saves_comment_and_limits_length(tmp_path) -> None:
    status = set_comment(str(tmp_path / "crm.json"), "1:2", "abc", "x" * 1200)
    assert status.comment == "x" * 1000


def test_get_stats_counts_statuses(tmp_path) -> None:
    path = str(tmp_path / "crm.json")
    update_status(path, "1:2", "abc", "in_work")
    update_status(path, "1:3", "def", "processed")
    stats = get_stats(path)
    assert stats["in_work"] == 1
    assert stats["processed"] == 1
    assert stats["total"] == 2
