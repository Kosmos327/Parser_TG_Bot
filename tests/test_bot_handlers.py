from app.bot_handlers import (
    SOURCE_JOIN_CANCEL,
    SOURCE_JOIN_START_ALL,
    SOURCE_JOIN_START_SELECTIVE,
    _candidate_source_values_for_join,
    _normalize_source_values_for_join,
)


def test_source_join_callback_data_under_64_bytes() -> None:
    values = [SOURCE_JOIN_START_ALL, SOURCE_JOIN_START_SELECTIVE, SOURCE_JOIN_CANCEL]

    assert all(len(value.encode("utf-8")) <= 64 for value in values)
    assert SOURCE_JOIN_START_ALL != SOURCE_JOIN_START_SELECTIVE


def test_normalize_source_values_for_join_deduplicates_and_adds_at() -> None:
    values = ["channel_one", "@Channel_One", "https://t.me/channel_two", "-100123", "bad"]

    assert _normalize_source_values_for_join(values) == ["@channel_one", "@channel_two"]


def test_candidate_source_values_for_join_prefers_public_source_values_and_falls_back_to_username() -> None:
    candidates = [
        {"source_chats_value": "@source_one", "username": "different_one"},
        {"source_chats_value": "-100123", "username": "fallback_two"},
        {"source_chats_value": "source_three", "username": None},
        {"source_chats_value": "@SOURCE_ONE", "username": "source_one"},
    ]

    assert _candidate_source_values_for_join(candidates) == ["@source_one", "@fallback_two", "@source_three"]


def test_candidate_source_values_from_joinable_fixture_returns_eight() -> None:
    candidates = [
        {"source_chats_value": f"@joinable_{index}", "username": f"joinable_{index}"}
        for index in range(8)
    ]

    assert _candidate_source_values_for_join(candidates) == [f"@joinable_{index}" for index in range(8)]
