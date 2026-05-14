from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


LIST_FIELDS = {
    "trigger_words",
    "strong_trigger_words",
    "weak_trigger_words",
    "negative_words",
    "exclude_words",
    "include_source_titles",
    "exclude_source_titles",
}


@dataclass
class ParserRules:
    trigger_words: list[str] = field(default_factory=list)
    strong_trigger_words: list[str] = field(default_factory=list)
    weak_trigger_words: list[str] = field(default_factory=list)
    negative_words: list[str] = field(default_factory=list)
    exclude_words: list[str] = field(default_factory=list)
    include_source_titles: list[str] = field(default_factory=list)
    exclude_source_titles: list[str] = field(default_factory=list)
    min_message_length: int = 10
    ignore_bots: bool = True
    ignore_forwards: bool = False
    min_score: int = 1


def _dedupe_items(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        key = item.casefold()
        if not item or key in seen:
            continue
        result.append(item)
        seen.add(key)
    return result


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on", "да"}
    return bool(value)


def _coerce_rules(data: dict[str, Any]) -> ParserRules:
    min_message_length = data.get("min_message_length", 10)
    try:
        min_message_length = int(min_message_length)
    except (TypeError, ValueError):
        min_message_length = 10

    trigger_words = _dedupe_items(list(data.get("trigger_words") or []))
    strong_words = _dedupe_items(list(data["strong_trigger_words"] if "strong_trigger_words" in data else trigger_words))
    min_score = data.get("min_score", 1)
    try:
        min_score = int(min_score)
    except (TypeError, ValueError):
        min_score = 1

    return ParserRules(
        trigger_words=trigger_words,
        strong_trigger_words=strong_words,
        weak_trigger_words=_dedupe_items(list(data.get("weak_trigger_words") or [])),
        negative_words=_dedupe_items(list(data.get("negative_words") or [])),
        exclude_words=_dedupe_items(list(data.get("exclude_words") or [])),
        include_source_titles=_dedupe_items(list(data.get("include_source_titles") or [])),
        exclude_source_titles=_dedupe_items(list(data.get("exclude_source_titles") or [])),
        min_message_length=max(0, min_message_length),
        ignore_bots=_coerce_bool(data.get("ignore_bots", True)),
        ignore_forwards=_coerce_bool(data.get("ignore_forwards", False)),
        min_score=max(-10, min(20, min_score)),
    )


def get_default_rules(settings: Any) -> ParserRules:
    """Build parser rules from legacy .env settings."""
    return ParserRules(
        trigger_words=_dedupe_items(getattr(settings, "keywords", [])),
        strong_trigger_words=_dedupe_items(getattr(settings, "keywords", [])),
        weak_trigger_words=[],
        negative_words=[],
        exclude_words=_dedupe_items(getattr(settings, "exclude_keywords", [])),
        include_source_titles=_dedupe_items(getattr(settings, "include_source_titles", [])),
        exclude_source_titles=_dedupe_items(getattr(settings, "exclude_source_titles", [])),
        min_message_length=int(getattr(settings, "min_message_length", 10)),
        ignore_bots=bool(getattr(settings, "ignore_bots", True)),
        ignore_forwards=bool(getattr(settings, "ignore_forwards", False)),
        min_score=1,
    )


def load_rules(path: str, settings: Any) -> ParserRules:
    """Load rules from JSON file, creating it from settings when missing."""
    rules_path = Path(path)
    if not rules_path.exists():
        rules = get_default_rules(settings)
        save_rules(path, rules)
        return rules

    with rules_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        rules = get_default_rules(settings)
        save_rules(path, rules)
        return rules

    return _coerce_rules(data)


def save_rules(path: str, rules: ParserRules) -> None:
    """Persist parser rules to JSON, creating parent directories."""
    rules_path = Path(path)
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _coerce_rules(asdict(rules))
    with rules_path.open("w", encoding="utf-8") as file:
        json.dump(asdict(normalized), file, ensure_ascii=False, indent=2)
        file.write("\n")


def add_rule_item(path: str, category: str, value: str, settings: Any) -> ParserRules:
    """Add a unique item to a list rule category and persist rules."""
    if category not in LIST_FIELDS:
        raise ValueError(f"Unsupported list rule category: {category}")

    rules = load_rules(path, settings)
    item = value.strip()
    if not item:
        return rules

    items = getattr(rules, category)
    if item.casefold() not in {existing.casefold() for existing in items}:
        items.append(item)
        setattr(rules, category, _dedupe_items(items))
        save_rules(path, rules)

    return rules


def remove_rule_item(path: str, category: str, value: str, settings: Any) -> ParserRules:
    """Remove an item from a list rule category case-insensitively and persist rules."""
    if category not in LIST_FIELDS:
        raise ValueError(f"Unsupported list rule category: {category}")

    rules = load_rules(path, settings)
    key = value.strip().casefold()
    if not key:
        return rules

    items = getattr(rules, category)
    filtered = [item for item in items if item.casefold() != key]
    if len(filtered) != len(items):
        setattr(rules, category, filtered)
        save_rules(path, rules)

    return rules


def set_rule_value(path: str, field: str, value: Any, settings: Any) -> ParserRules:
    """Set a scalar rule value and persist rules."""
    if field in LIST_FIELDS or not hasattr(ParserRules, field):
        raise ValueError(f"Unsupported scalar rule field: {field}")

    rules = load_rules(path, settings)
    if field == "min_message_length":
        value = max(0, int(value))
    elif field == "min_score":
        value = max(-10, min(20, int(value)))
    elif field in {"ignore_bots", "ignore_forwards"}:
        value = _coerce_bool(value)

    setattr(rules, field, value)
    save_rules(path, rules)
    return rules
