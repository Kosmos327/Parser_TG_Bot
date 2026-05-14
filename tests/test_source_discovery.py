from app.source_discovery import export_candidates_txt, filter_joinable_candidates, parse_sources_text


def test_parse_sources_text_normalizes_usernames_and_links() -> None:
    text = """
    @channel1
    https://t.me/channel2
    t.me/channel3
    channel4
    """

    assert parse_sources_text(text) == ["@channel1", "@channel2", "@channel3", "@channel4"]


def test_export_candidates_txt_writes_only_usernames(tmp_path) -> None:
    path = tmp_path / "sources.txt"
    candidates = [
        {"username": "channel1", "source_chats_value": "@channel1"},
        {"username": None, "source_chats_value": "-100123"},
        {"username": "@channel2", "source_chats_value": "@channel2"},
    ]

    result_path = export_candidates_txt(candidates, str(path))

    assert result_path == str(path)
    assert path.read_text(encoding="utf-8") == "@channel1\n@channel2\n"


def test_filter_joinable_candidates_excludes_unsafe_statuses_and_no_username() -> None:
    candidates = [
        {"username": "okchan", "joined": False, "skipped": False, "manual_required": False, "error": None},
        {"username": "joined", "joined": True, "skipped": False, "manual_required": False, "error": None},
        {"username": "skipped", "joined": False, "skipped": True, "manual_required": False, "error": None},
        {"username": "manual", "joined": False, "skipped": False, "manual_required": True, "error": None},
        {"username": "err", "joined": False, "skipped": False, "manual_required": False, "error": "boom"},
        {"username": None, "source_chats_value": "-100123", "joined": False, "skipped": False, "manual_required": False, "error": None},
    ]

    assert filter_joinable_candidates(candidates) == [candidates[0]]


def test_parse_sources_text_deduplicates_case_insensitively() -> None:
    text = """
    channel4
    @channel4
    https://t.me/Channel4
    """

    assert parse_sources_text(text) == ["@channel4"]


def test_parse_sources_text_accepts_line_list() -> None:
    text = "@buhcumIter\n@secrets_1C\n@bs_accounting\n@anna_kvorss\n@hacks_1c\n@bukhgalteriaa\n@bukhgalteria1\n@bukhgalteria1C\n"

    assert parse_sources_text(text) == [
        "@buhcumIter",
        "@secrets_1C",
        "@bs_accounting",
        "@anna_kvorss",
        "@hacks_1c",
        "@bukhgalteriaa",
        "@bukhgalteria1",
        "@bukhgalteria1C",
    ]


def test_filter_joinable_candidates_accepts_public_source_chats_value() -> None:
    candidates = [
        {"username": None, "source_chats_value": "@source_value", "joined": False, "skipped": False, "manual_required": False, "error": None},
        {"username": None, "source_chats_value": "-100123", "joined": False, "skipped": False, "manual_required": False, "error": None},
    ]

    assert filter_joinable_candidates(candidates) == [candidates[0]]
    assert filter_joinable_candidates(candidates)[0]["source_chats_value"] == "@source_value"
