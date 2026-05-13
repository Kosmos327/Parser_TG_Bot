from types import SimpleNamespace

from app.filters import (
    contains_any,
    message_matches,
    normalize_text,
    should_process_message,
    source_title_allowed,
)


def _settings(**overrides):
    values = {
        "min_message_length": 10,
        "include_source_titles": [],
        "exclude_source_titles": [],
        "exclude_keywords": [],
        "keywords": ["как понизить налоги"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_keyword_matches_case_insensitive() -> None:
    assert message_matches("Подскажите, КАК ПОНИЗИТЬ НАЛОГИ в ИП?", ["как понизить налоги"])


def test_empty_text_does_not_match() -> None:
    assert not message_matches("", ["как понизить налоги"])


def test_text_without_keyword_does_not_match() -> None:
    assert not message_matches("Нужна консультация по аренде офиса", ["как понизить налоги"])


def test_contains_any_case_insensitive() -> None:
    assert contains_any("Нужна ОПТИМИЗАЦИЯ НАЛОГОВ для ООО", ["оптимизация налогов"])


def test_normalize_spaces_and_yo() -> None:
    assert normalize_text(" Как   понизить   налогЁв ") == "как понизить налогев"
    assert contains_any("Как   понизить   налогЁв", ["понизить налогев"])


def test_source_title_allowed_include() -> None:
    assert source_title_allowed("Бухгалтерия и налоги", ["налоги"], [])
    assert not source_title_allowed("Маркетинг", ["налоги"], [])


def test_source_title_allowed_exclude() -> None:
    assert not source_title_allowed("Спам чат", [], ["спам"])
    assert source_title_allowed("Полезный чат", [], ["спам"])


def test_should_process_message_empty_text() -> None:
    assert should_process_message("   ", "Налоги", _settings()) == (False, "empty_text")


def test_should_process_message_too_short() -> None:
    assert should_process_message("налоги", "Налоги", _settings(min_message_length=10)) == (
        False,
        "too_short",
    )


def test_should_process_message_exclude_keyword() -> None:
    settings = _settings(exclude_keywords=["не актуально"])
    assert should_process_message("как понизить налоги? не актуально", "Налоги", settings) == (
        False,
        "exclude_keyword",
    )


def test_should_process_message_no_keyword() -> None:
    assert should_process_message("Нужна консультация по аренде офиса", "Налоги", _settings()) == (
        False,
        "no_keyword",
    )


def test_should_process_message_ok() -> None:
    assert should_process_message("Подскажите, как понизить налоги для ИП?", "Налоги", _settings()) == (
        True,
        None,
    )
