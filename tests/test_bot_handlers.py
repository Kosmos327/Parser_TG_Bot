from app.bot_handlers import (
    PENDING_LEAD_COMMENT,
    PENDING_LEAD_DATE,
    PENDING_LEAD_SEARCH,
    PENDING_RULE_ADD,
    PENDING_RULE_MIN_LENGTH,
    PENDING_RULE_REMOVE,
    PENDING_SOURCE_JOIN_CONFIRM,
    PENDING_SOURCE_JOIN_SELECTIVE_WAIT_LIST,
    PENDING_SOURCE_SEARCH_WAIT_QUERIES,
    SOURCE_JOIN_CANCEL,
    SOURCE_JOIN_START_ALL,
    SOURCE_JOIN_START_SELECTIVE,
    _candidate_source_values_for_join,
    _format_pending_debug,
    _normalize_source_values_for_join,
    _parse_source_queries,
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


def test_parse_source_queries_single_word() -> None:
    assert _parse_source_queries("бухгалтерия") == ["бухгалтерия"]


def test_parse_source_queries_limits_multiple_lines_to_ten() -> None:
    text = "\n".join(f"запрос {index}" for index in range(12))

    assert _parse_source_queries(text) == [f"запрос {index}" for index in range(10)]


def test_pending_action_constants_are_not_empty() -> None:
    constants = [
        PENDING_SOURCE_SEARCH_WAIT_QUERIES,
        PENDING_SOURCE_JOIN_CONFIRM,
        PENDING_SOURCE_JOIN_SELECTIVE_WAIT_LIST,
        PENDING_LEAD_COMMENT,
        PENDING_LEAD_DATE,
        PENDING_LEAD_SEARCH,
        PENDING_RULE_ADD,
        PENDING_RULE_REMOVE,
        PENDING_RULE_MIN_LENGTH,
    ]

    assert all(constants)


def test_format_pending_debug_includes_action_keys_counts_and_search_text() -> None:
    text = _format_pending_debug(123, {
        "action": PENDING_LEAD_SEARCH,
        "source_values": ["@one", "@two"],
        "query": "бухгалтерия",
        "timestamp": "2026-05-14T00:00:00+00:00",
    })

    assert "Ожидающее действие: да" in text
    assert f"Действие: {PENDING_LEAD_SEARCH}" in text
    assert "Источников в ожидании: 2" in text
    assert "Текст поиска: бухгалтерия" in text
    assert "Создано: 2026-05-14T00:00:00+00:00" in text
