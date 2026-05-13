from app.filters import message_matches


def test_keyword_matches_case_insensitive() -> None:
    assert message_matches("Подскажите, КАК ПОНИЗИТЬ НАЛОГИ в ИП?", ["как понизить налоги"])


def test_empty_text_does_not_match() -> None:
    assert not message_matches("", ["как понизить налоги"])


def test_text_without_keyword_does_not_match() -> None:
    assert not message_matches("Нужна консультация по аренде офиса", ["как понизить налоги"])
