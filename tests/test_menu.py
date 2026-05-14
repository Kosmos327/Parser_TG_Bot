from app.bot_handlers import _rules_button_markup, is_main_menu_text


def test_main_menu_text_recognized() -> None:
    assert is_main_menu_text("🏠 Главное меню")
    assert not is_main_menu_text("Главное меню")


def test_main_menu_callback_data_under_64_bytes() -> None:
    markup = _rules_button_markup()
    values = [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]
    assert values
    assert all(len(value.encode("utf-8")) <= 64 for value in values)
