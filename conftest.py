from bot import keyboards as kb
from bot.scoring import Rule


def test_menu_has_all_sections():
    texts = [b.text for row in kb.main_menu().inline_keyboard for b in row]
    for expected in ["📚 Тренировка", "📖 Мои слова", "📊 Статистика", "⭐ Мои баллы", "⚙️ Настройки", "🌐 Источник слов"]:
        assert expected in texts


def test_summary_buttons_present():
    texts = [b.text for row in kb.summary(True, 5).inline_keyboard for b in row]
    assert "🔁 Повторить ошибки" in texts and "🔄 Пройти заново" in texts and "🏠 Главное меню" in texts


def test_points_picker_covers_minus5_to_plus5():
    values = [b.callback_data for row in kb.points_picker("np").inline_keyboard for b in row]
    for v in range(-5, 6):
        assert f"np:{v}" in values


def test_callback_data_within_telegram_limit():
    markups = [kb.main_menu(), kb.points_picker("ep:999"), kb.rules([(1, Rule(0, None, 0))])]
    for markup in markups:
        for row in markup.inline_keyboard:
            for btn in row:
                assert len(btn.callback_data.encode()) <= 64
