from app.dialogs import detect_source_type, is_allowed_by_source_search_settings
from app.source_search_settings import SourceSearchSettings


class User:
    first_name = "Ivan"
    title = None


class Chat:
    title = "Small group"
    username = None


class Channel:
    def __init__(self, *, broadcast=False, megagroup=False, username=None):
        self.broadcast = broadcast
        self.megagroup = megagroup
        self.username = username
        self.title = "Channel"


def test_user_is_private_chat() -> None:
    assert detect_source_type(User()) == "private_chat"


def test_chat_is_group_chat() -> None:
    assert detect_source_type(Chat()) == "group_chat"


def test_channel_broadcast_is_public_channel() -> None:
    assert detect_source_type(Channel(broadcast=True, username="news")) == "public_channel"


def test_channel_megagroup_is_supergroup() -> None:
    assert detect_source_type(Channel(megagroup=True, username="group")) == "supergroup"


def test_filter_blocks_private_chat_when_excluded() -> None:
    assert is_allowed_by_source_search_settings(User(), SourceSearchSettings(exclude_private_chats=True)) is False


def test_filter_allows_public_channel_when_enabled() -> None:
    assert is_allowed_by_source_search_settings(Channel(broadcast=True), SourceSearchSettings(include_public_channels=True)) is True
