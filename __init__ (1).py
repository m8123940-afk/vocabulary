"""Inline-клавиатуры бота."""
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.scoring import POINTS_MAX, POINTS_MIN, Rule


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(*[_btn(text, data) for text, data in row])
    return builder.as_markup()


def _btn(text: str, data: str):
    from aiogram.types import InlineKeyboardButton
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> InlineKeyboardMarkup:
    return _kb([
        [("📚 Тренировка", "m:train"), ("📖 Мои слова", "m:words")],
        [("📊 Статистика", "m:stats"), ("⭐ Мои баллы", "m:points")],
        [("⚙️ Настройки", "m:settings"), ("🌐 Источник слов", "m:source")],
    ])


def back_to_menu() -> InlineKeyboardMarkup:
    return _kb([[("🏠 Главное меню", "menu")]])


def units(unit_names: list[str]) -> InlineKeyboardMarkup:
    rows = [[(f"Unit {u}", f"unit:{u}")] for u in unit_names]
    rows.append([("🏠 Главное меню", "menu")])
    return _kb(rows)


def parts(unit: str, part_names: list[str]) -> InlineKeyboardMarkup:
    rows = [[("📦 Все Part", f"part:{unit}|*")]]
    rows += [[(f"Part {p}" if p else "Без Part", f"part:{unit}|{p}")] for p in part_names]
    rows.append([("⬅️ К Unit", "m:train"), ("🏠 Главное меню", "menu")])
    return _kb(rows)


def question(stopped: bool = False) -> InlineKeyboardMarkup:
    return _kb([
        [("🔊 Повторить слово", "tr:replay"), ("⏭ Пропустить", "tr:skip")],
        [("⏹ Завершить", "tr:stop")],
    ])


def summary(has_wrong: bool, session_id: int) -> InlineKeyboardMarkup:
    rows = []
    if has_wrong:
        rows.append([("🔁 Повторить ошибки", f"retry:{session_id}")])
    rows.append([("🔄 Пройти заново", "m:train_again"), ("🏠 Главное меню", "menu")])
    return _kb(rows)


def source_options() -> InlineKeyboardMarkup:
    return _kb([
        [("📘 Словарь Navigate B1+ (Unit 1–12)", "src:bundled")],
        [("🔗 Указать ссылку", "src:url")],
        [("✍️ Ввести слова вручную", "src:manual")],
        [("🏠 Главное меню", "menu")],
    ])


def source_error() -> InlineKeyboardMarkup:
    return _kb([
        [("✍️ Ввести вручную", "src:manual"), ("🔗 Другая ссылка", "src:url")],
        [("🏠 Главное меню", "menu")],
    ])


def words_menu() -> InlineKeyboardMarkup:
    return _kb([
        [("➕ Добавить / изменить / удалить", "words:edit")],
        [("🏠 Главное меню", "menu")],
    ])


def words_cancel() -> InlineKeyboardMarkup:
    return _kb([[("❌ Отмена", "words:cancel")]])


def settings(cfg: dict) -> InlineKeyboardMarkup:
    speed = "медленная" if cfg["tts_rate"] < 0.9 else "обычная"
    return _kb([
        [(f"🔢 Слов за тренировку: {cfg['words_per_session']}", "set:words")],
        [(f"🔀 Случайный порядок: {'вкл' if cfg['shuffle'] else 'выкл'}", "set:shuffle")],
        [(f"🐢 Скорость озвучки: {speed}", "set:speed")],
        [(f"🔁 Повторять ошибки: {'вкл' if cfg['retry_errors'] else 'выкл'}", "set:retry")],
        [("📋 Таблица баллов", "rules:list")],
        [("🏠 Главное меню", "menu")],
    ])


def rules(rule_rows: list[tuple[int, Rule]]) -> InlineKeyboardMarkup:
    rows = []
    for rule_id, rule in rule_rows:
        rows.append([(_rule_label(rule), f"rule:{rule_id}")])
    rows.append([("➕ Добавить правило", "rules:add")])
    rows.append([("♻️ Восстановить стандартные", "rules:reset")])
    rows.append([("⬅️ Настройки", "m:settings")])
    return _kb(rows)


def rule_actions(rule_id: int) -> InlineKeyboardMarkup:
    return _kb([
        [("✏️ Изменить диапазон", f"rule:range:{rule_id}")],
        [("🎯 Изменить баллы", f"rule:pts:{rule_id}")],
        [("🗑 Удалить", f"rule:del:{rule_id}")],
        [("⬅️ К таблице", "rules:list")],
    ])


def points_picker(prefix: str) -> InlineKeyboardMarkup:
    """Сетка баллов от -5 до +5. prefix: 'np' для нового правила, 'ep:<id>' для изменения."""
    values = list(range(POINTS_MIN, POINTS_MAX + 1))
    rows = [[(f"{v:+d}" if v else "0", f"{prefix}:{v}") for v in values[i:i + 4]] for i in range(0, len(values), 4)]
    rows.append([("❌ Отмена", "rules:list")])
    return _kb(rows)


def _rule_label(rule: Rule) -> str:
    rng = f"{rule.min_errors}+" if rule.max_errors is None else (
        f"{rule.min_errors}" if rule.min_errors == rule.max_errors else f"{rule.min_errors}–{rule.max_errors}")
    return f"{rng} ошибок → {rule.points:+d} баллов"


def rule_label(rule: Rule) -> str:
    return _rule_label(rule)
