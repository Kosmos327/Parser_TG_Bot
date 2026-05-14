from types import SimpleNamespace

from app.filters import evaluate_lead_match


def rules(**overrides):
    data = dict(
        min_message_length=1,
        include_source_titles=[],
        exclude_source_titles=[],
        exclude_words=[],
        trigger_words=[],
        strong_trigger_words=[],
        weak_trigger_words=[],
        negative_words=[],
        min_score=1,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def test_strong_trigger_adds_two_points() -> None:
    result = evaluate_lead_match("Нужна бухгалтерия для ИП", "Источник", rules(strong_trigger_words=["бухгалтерия"]))
    assert result.matched
    assert result.score == 2


def test_negative_words_subtract_score() -> None:
    result = evaluate_lead_match(
        "Нужна бухгалтерия бесплатно", "Источник", rules(strong_trigger_words=["бухгалтерия"], negative_words=["бесплатно"])
    )
    assert not result.matched
    assert result.score == -1
    assert result.negative_phrases == ["бесплатно"]


def test_exclude_words_reject_immediately() -> None:
    result = evaluate_lead_match("Нужна бухгалтерия не актуально", "Источник", rules(trigger_words=["бухгалтерия"], exclude_words=["не актуально"]))
    assert not result.matched
    assert result.reason == "exclude_keyword"


def test_low_score_reject() -> None:
    result = evaluate_lead_match("Нужна консультация", "Источник", rules(weak_trigger_words=["консультация"], min_score=2))
    assert not result.matched
    assert result.reason == "low_score"


def test_matched_phrases_are_saved() -> None:
    result = evaluate_lead_match("Нужна консультация по налогам", "Источник", rules(trigger_words=["налогам"], weak_trigger_words=["консультация"]))
    assert result.matched_phrases == ["налогам", "консультация"]
