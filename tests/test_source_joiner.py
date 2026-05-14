import asyncio

from app.source_joiner import join_sources_limited, is_manual_required_error, public_username_sources


def test_public_username_sources_limits_and_excludes_numeric_ids() -> None:
    sources = ["@channel1", "-100123456", "https://t.me/channel2", "t.me/channel3"]

    assert public_username_sources(sources, max_join=2) == ["@channel1", "@channel2"]


def test_manual_required_error_classifier_detects_private_invite() -> None:
    exc = RuntimeError("CHANNEL_PRIVATE invite required")

    assert is_manual_required_error(exc) is True


def test_join_sources_limited_reports_invalid_source() -> None:
    class Client:
        async def get_entity(self, source: str) -> str:
            return source

        async def __call__(self, request):  # pragma: no cover - invalid source must not call client
            raise AssertionError("client should not be called for invalid source")

    result = asyncio.run(join_sources_limited(Client(), ["-100123456", "https://t.me/+invite"], delay_seconds=0, max_join=5))

    assert result["joined"] == []
    assert [item["source"] for item in result["failed"]] == ["-100123456", "https://t.me/+invite"]
    assert all("Invalid public username" in item["error"] for item in result["failed"])
