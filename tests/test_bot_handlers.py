from app.bot_handlers import SOURCE_JOIN_CANCEL, SOURCE_JOIN_START_ALL, SOURCE_JOIN_START_SELECTIVE


def test_source_join_callback_data_under_64_bytes() -> None:
    values = [SOURCE_JOIN_START_ALL, SOURCE_JOIN_START_SELECTIVE, SOURCE_JOIN_CANCEL]

    assert all(len(value.encode("utf-8")) <= 64 for value in values)
    assert SOURCE_JOIN_START_ALL != SOURCE_JOIN_START_SELECTIVE
