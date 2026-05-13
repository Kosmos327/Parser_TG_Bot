from types import SimpleNamespace

from app.rules_storage import (
    ParserRules,
    add_rule_item,
    load_rules,
    remove_rule_item,
    save_rules,
    set_rule_value,
)


def _settings(**overrides):
    values = {
        "keywords": ["как понизить налоги", "снизить налоги"],
        "exclude_keywords": ["не актуально"],
        "include_source_titles": ["налоги"],
        "exclude_source_titles": ["спам"],
        "min_message_length": 10,
        "ignore_bots": True,
        "ignore_forwards": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_missing_rules_file_creates_default_rules_from_settings(tmp_path) -> None:
    path = tmp_path / "parser_rules.json"

    rules = load_rules(str(path), _settings())

    assert path.exists()
    assert rules.trigger_words == ["как понизить налоги", "снизить налоги"]
    assert rules.exclude_words == ["не актуально"]
    assert rules.include_source_titles == ["налоги"]
    assert rules.exclude_source_titles == ["спам"]
    assert rules.min_message_length == 10
    assert rules.ignore_bots is True
    assert rules.ignore_forwards is False


def test_add_rule_item_adds_value(tmp_path) -> None:
    path = tmp_path / "parser_rules.json"

    rules = add_rule_item(str(path), "trigger_words", "оптимизация налогов", _settings())

    assert "оптимизация налогов" in rules.trigger_words


def test_add_rule_item_does_not_add_case_insensitive_duplicate(tmp_path) -> None:
    path = tmp_path / "parser_rules.json"
    add_rule_item(str(path), "trigger_words", "Оптимизация налогов", _settings())

    rules = add_rule_item(str(path), "trigger_words", "оптимизация налогов", _settings())

    matches = [item for item in rules.trigger_words if item.casefold() == "оптимизация налогов"]
    assert matches == ["Оптимизация налогов"]


def test_remove_rule_item_removes_value_case_insensitive(tmp_path) -> None:
    path = tmp_path / "parser_rules.json"
    add_rule_item(str(path), "exclude_words", "Не актуально", _settings(exclude_keywords=[]))

    rules = remove_rule_item(str(path), "exclude_words", "не АКТУАЛЬНО", _settings())

    assert rules.exclude_words == []


def test_set_rule_value_changes_min_message_length(tmp_path) -> None:
    path = tmp_path / "parser_rules.json"

    rules = set_rule_value(str(path), "min_message_length", 25, _settings())

    assert rules.min_message_length == 25


def test_save_load_persists_rules(tmp_path) -> None:
    path = tmp_path / "nested" / "parser_rules.json"
    expected = ParserRules(
        trigger_words=["Триггер"],
        exclude_words=["Стоп"],
        include_source_titles=["Источник"],
        exclude_source_titles=["Спам"],
        min_message_length=42,
        ignore_bots=False,
        ignore_forwards=True,
    )

    save_rules(str(path), expected)
    loaded = load_rules(str(path), _settings())

    assert loaded == expected
