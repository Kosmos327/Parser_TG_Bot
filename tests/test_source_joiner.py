from app.source_joiner import is_manual_required_error, public_username_sources


def test_public_username_sources_limits_and_excludes_numeric_ids() -> None:
    sources = ["@channel1", "-100123456", "https://t.me/channel2", "t.me/channel3"]

    assert public_username_sources(sources, max_join=2) == ["@channel1", "@channel2"]


def test_manual_required_error_classifier_detects_private_invite() -> None:
    exc = RuntimeError("CHANNEL_PRIVATE invite required")

    assert is_manual_required_error(exc) is True
