from app.bot_handlers import _format_help, _rules_button_markup


TECHNICAL_WORDS = [
    "source_join_in_progress",
    "Telethon client",
    "Bot polling",
    "dry_run",
    "processed_count",
    "matched_count",
    "duplicate_count",
]


def _menu_text() -> str:
    markup = _rules_button_markup()
    return "\n".join(button.text for row in markup.inline_keyboard for button in row)


def test_help_does_not_show_technical_words() -> None:
    help_text = _format_help()

    assert all(word not in help_text for word in TECHNICAL_WORDS)


def test_menu_does_not_show_technical_words() -> None:
    menu_text = _menu_text()

    assert "⚙️ Настройки поиска источников" in menu_text
    assert "🩺 Проверка работы" in menu_text
    assert all(word not in menu_text for word in TECHNICAL_WORDS)
