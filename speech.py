"""Обработчики Telegram: меню, тренировка, слова, статистика, баллы, настройки, источник слов."""
import asyncio
import html
import io
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from bot import keyboards as kb
from bot import trainer
from bot.db import Database
from bot.bundled import load_navigate_rows
from bot.parsing import ParseError, parse_edit_command, parse_range, parse_unit_command, parse_word_lines
from bot.scoring import find_overlaps, validate_rule
from bot.scraper import ScrapeError, list_units, load_words_from_url, parse_words
from bot.speech import Recognizer, SpeechUnavailable, synthesize
from bot.url_safety import validate_url

router = Router()
log = logging.getLogger(__name__)
CUSTOM_UNIT = "Мои"
SESSION_SIZES = [5, 10, 15, 20]


class Form(StatesGroup):
    source_url = State()
    manual_words = State()
    words_input = State()
    rule_range_new = State()
    rule_range_edit = State()


# ---------- общие помощники ----------
async def show(cb: CallbackQuery, text: str, markup=None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


def menu_text() -> str:
    return "🎓 <b>Изучение английских слов</b>\n\nВыберите раздел:"


def _progress_line(done: int, total: int, errors: int) -> str:
    return f"{trainer.progress_bar(done, total)}  •  ❌ ошибок: {errors}"


# ---------- меню ----------
@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    db.ensure_user(message.from_user.id)
    await message.answer(menu_text(), reply_markup=kb.main_menu())


@router.message(Command("app"))
async def cmd_app(message: Message, miniapp_url: str | None = None) -> None:
    """Кнопка, которая открывает Telegram Mini App (нужен HTTPS-адрес в MINIAPP_URL)."""
    if not miniapp_url:
        await message.answer("Мини-приложение пока не подключено (нужен MINIAPP_URL в .env).")
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=miniapp_url))
    ]])
    await message.answer("Откройте мини-приложение — тренировка, слова, баллы и статистика в одном месте.",
                         reply_markup=markup)


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(cb, menu_text(), kb.main_menu())


# ---------- тренировка ----------
@router.callback_query(F.data == "m:train")
async def cb_train(cb: CallbackQuery, db: Database) -> None:
    units = db.list_units(cb.from_user.id)
    if not units:
        await show(cb, "📭 Слов пока нет. Укажите источник или добавьте слова вручную.", kb.back_to_menu())
        return
    await show(cb, "📚 <b>Выберите Unit</b>", kb.units(units))


@router.callback_query(F.data.startswith("unit:"))
async def cb_unit(cb: CallbackQuery, db: Database) -> None:
    unit = cb.data.split(":", 1)[1]
    await show(cb, f"📚 <b>Unit {html.escape(unit)}</b>\nВыберите Part:",
               kb.parts(unit, db.list_parts(cb.from_user.id, unit)))


@router.callback_query(F.data.startswith("part:"))
async def cb_part(cb: CallbackQuery, db: Database, bot: Bot) -> None:
    unit, part = cb.data.split(":", 1)[1].split("|", 1)
    try:
        session_id = trainer.start_training(db, cb.from_user.id, unit, part)
    except ValueError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    await cb.answer("Поехали!")
    await cb.message.answer("🚀 <b>Тренировка началась!</b> Слушайте слово и переводите его на русский.")
    await ask_question(bot, cb.message.chat.id, cb.from_user.id, db)


@router.callback_query(F.data == "m:train_again")
async def cb_train_again(cb: CallbackQuery, db: Database, bot: Bot) -> None:
    last = db.history(cb.from_user.id, 1)
    if not last:
        await cb.answer("Сначала пройдите тренировку.", show_alert=True)
        return
    session_id = trainer.start_training(db, cb.from_user.id, last[0]["unit"], last[0]["part"])
    await cb.answer("Начинаем заново")
    await ask_question(bot, cb.message.chat.id, cb.from_user.id, db)


@router.callback_query(F.data.startswith("retry:"))
async def cb_retry(cb: CallbackQuery, db: Database, bot: Bot) -> None:
    source_id = int(cb.data.split(":", 1)[1])
    session = db.get_session(cb.from_user.id, source_id)
    wrong = db.wrong_word_ids(source_id) if session else []
    if not wrong:
        await cb.answer("Ошибок нет — повторять нечего.", show_alert=True)
        return
    trainer.start_training(db, cb.from_user.id, session.unit, session.part, mode="retry", word_ids=wrong)
    await cb.answer("Повторяем ошибки")
    await cb.message.answer("🔁 <b>Повтор ошибок</b> — баллы за этот проход не начисляются.")
    await ask_question(bot, cb.message.chat.id, cb.from_user.id, db)


async def ask_question(bot: Bot, chat_id: int, user_id: int, db: Database) -> None:
    session_id = db.get_active_session_id(user_id)
    if session_id is None:
        return
    if trainer.is_finished(db, user_id, session_id):
        await send_report(bot, chat_id, user_id, db)
        return
    session = db.get_session(user_id, session_id)
    word = trainer.current_word(db, user_id, session_id)
    settings = db.get_settings(user_id)
    done = session.current_index
    caption = (
        f"🎧 <b>Слово {done + 1} из {len(session.word_ids)}</b>\n"
        f"{trainer.progress_bar(done, len(session.word_ids))}\n\n"
        "🎤 Ответьте голосом или текстом — по-русски."
    )
    audio = await synthesize(word.en, settings["tts_rate"])
    if audio:
        await bot.send_audio(chat_id, BufferedInputFile(audio, "word.mp3"), caption=caption, reply_markup=kb.question())
    else:
        await bot.send_message(
            chat_id,
            caption + f"\n\n🔇 Озвучка недоступна. Слово: <b>{html.escape(word.en)}</b>",
            reply_markup=kb.question(),
        )


@router.callback_query(F.data == "tr:replay")
async def cb_replay(cb: CallbackQuery, db: Database, bot: Bot) -> None:
    session_id = db.get_active_session_id(cb.from_user.id)
    word = trainer.current_word(db, cb.from_user.id, session_id) if session_id else None
    if word is None:
        await cb.answer("Тренировка не активна.", show_alert=True)
        return
    audio = await synthesize(word.en, db.get_settings(cb.from_user.id)["tts_rate"])
    await cb.answer()
    if audio:
        await bot.send_audio(cb.message.chat.id, BufferedInputFile(audio, "word.mp3"))
    else:
        await cb.message.answer(f"🔇 Озвучка недоступна. Слово: <b>{html.escape(word.en)}</b>")


@router.callback_query(F.data == "tr:skip")
async def cb_skip(cb: CallbackQuery, db: Database, bot: Bot) -> None:
    session_id = db.get_active_session_id(cb.from_user.id)
    if session_id is None:
        await cb.answer("Тренировка не активна.", show_alert=True)
        return
    result = trainer.skip_word(db, cb.from_user.id, session_id)
    await cb.answer()
    await cb.message.answer(
        f"⏭ Пропущено. Перевод: <b>{html.escape(result.word.ru)}</b>  ({html.escape(result.word.en)})"
    )
    await ask_question(bot, cb.message.chat.id, cb.from_user.id, db)


@router.callback_query(F.data == "tr:stop")
async def cb_stop(cb: CallbackQuery, db: Database, bot: Bot) -> None:
    session_id = db.get_active_session_id(cb.from_user.id)
    if session_id is None:
        await cb.answer("Тренировка не активна.", show_alert=True)
        return
    await cb.answer()
    await send_report(bot, cb.message.chat.id, cb.from_user.id, db)


async def process_answer(bot: Bot, chat_id: int, user_id: int, db: Database, said: str) -> None:
    session_id = db.get_active_session_id(user_id)
    result = trainer.submit_answer(db, user_id, session_id, said)
    if result.correct:
        head = "✅ <b>Верно!</b>"
    else:
        head = "❌ <b>Неверно.</b>"
    text = (
        f"{head}\n"
        f"Вы сказали: «{html.escape(said)}»\n"
        f"🇬🇧 <b>{html.escape(result.word.en)}</b> — {html.escape(result.word.ru)}"
    )
    session = db.get_session(user_id, session_id)
    errors = sum(1 for a in db.session_attempts(session_id) if a["errors"] > 0 and not a["skipped"])
    text += f"\n\n{_progress_line(result.done, result.total, errors)}"
    await bot.send_message(chat_id, text)
    await ask_question(bot, chat_id, user_id, db)


@router.message(F.voice, StateFilter(None))
async def on_voice(message: Message, db: Database, bot: Bot, recognizer: Recognizer) -> None:
    session_id = db.get_active_session_id(message.from_user.id)
    if session_id is None:
        await message.answer("Сначала начните тренировку в меню.", reply_markup=kb.back_to_menu())
        return
    buffer = io.BytesIO()
    file = await bot.get_file(message.voice.file_id)
    await bot.download_file(file.file_path, buffer)
    try:
        said = await recognizer.transcribe(buffer.getvalue(), "answer.ogg")
    except SpeechUnavailable as exc:
        await message.answer(f"⚠️ {exc}")
        return
    if not said:
        # Нераспознанная речь не считается ошибкой: просто просим повторить.
        await message.answer("🤷 Речь не распознана. Повторите ответ — штрафа нет.")
        return
    await process_answer(bot, message.chat.id, message.from_user.id, db, said)


@router.message(F.text, StateFilter(None))
async def on_text(message: Message, db: Database, bot: Bot) -> None:
    uid = message.from_user.id
    command = parse_unit_command(message.text)
    if command is not None:
        # Команда «Unit 4 Part 2» запускает тренировку по указанной части (но не во время активной тренировки).
        if db.get_active_session_id(uid) is not None:
            await message.answer("Сначала завершите текущую тренировку (кнопка «⏹ Завершить»).")
            return
        unit, part = command
        if part is None:
            parts_list = db.list_parts(uid, unit)
            if not parts_list:
                await message.answer(f"В базе нет Unit {unit}. Проверьте номер или загрузите словарь.",
                                     reply_markup=kb.source_options())
                return
            await message.answer(f"📚 Unit {unit}: выберите Part", reply_markup=kb.parts(unit, parts_list))
            return
        if part not in db.list_parts(uid, unit):
            await message.answer(f"В Unit {unit} нет Part {part}.", reply_markup=kb.parts(unit, db.list_parts(uid, unit)))
            return
        try:
            trainer.start_training(db, uid, unit, part)
        except ValueError as exc:
            await message.answer(f"⚠️ {html.escape(str(exc))}")
            return
        await message.answer(f"🚀 <b>Unit {unit} Part {part}</b> — тренировка началась!")
        await ask_question(bot, message.chat.id, uid, db)
        return
    if db.get_active_session_id(uid) is None:
        await message.answer(menu_text(), reply_markup=kb.main_menu())
        return
    await process_answer(bot, message.chat.id, uid, db, message.text)


async def send_report(bot: Bot, chat_id: int, user_id: int, db: Database) -> None:
    session_id = db.get_active_session_id(user_id)
    if session_id is None:
        return
    report = trainer.finish(db, user_id, session_id)
    if report["mode"] == "retry":
        points_line = "⭐ Баллы: не начисляются за повтор ошибок"
    elif report["points"] == 0 and report["total"] and report["errors"] > 0:
        points_line = "⭐ Баллы за тренировку: 0"
    else:
        points_line = f"⭐ Баллы за тренировку: {report['points']:+d}"
    text = (
        "🏁 <b>Тренировка завершена!</b>\n"
        f"{trainer.progress_bar(report['done'], report['total'])}\n\n"
        f"📚 Всего слов: {report['total']}\n"
        f"✅ Правильных: {report['correct']}\n"
        f"❌ Ошибок: {report['errors']}\n"
        f"⏭ Пропусков: {report['skipped']}\n"
        f"🎯 Точность: {report['percent']}%\n\n"
        f"{points_line}\n"
        f"🏆 Общий баланс: {report['balance']}"
    )
    has_wrong = bool(report["wrong_ids"])
    await bot.send_message(chat_id, text, reply_markup=kb.summary(has_wrong, report["session_id"]))
    settings = db.get_settings(user_id)
    if report["mode"] == "train" and settings["retry_errors"] and has_wrong:
        trainer.start_training(db, user_id, report["unit"], report["part"], mode="retry", word_ids=report["wrong_ids"])
        await bot.send_message(chat_id, "🔁 <b>Повторяем ошибки</b> — без начисления баллов.")
        await ask_question(bot, chat_id, user_id, db)


# ---------- мои слова ----------
@router.callback_query(F.data == "m:words")
async def cb_words(cb: CallbackQuery, db: Database) -> None:
    words = db.list_words(cb.from_user.id)
    if not words:
        await show(cb, "📭 Список пуст. Добавьте слова или загрузите их по ссылке.", kb.words_menu())
        return
    lines = [f"<code>{w.id}</code>. {html.escape(w.en)} — {html.escape(w.ru)}" for w in words[:40]]
    more = f"\n… и ещё {len(words) - 40}" if len(words) > 40 else ""
    text = (
        f"📖 <b>Мои слова</b> — всего {len(words)}\n\n" + "\n".join(lines) + more +
        "\n\n<i>Команды: «+ слово - перевод», «e 12 слово - перевод», «d 12»</i>"
    )
    await show(cb, text, kb.words_menu())


@router.callback_query(F.data == "words:edit")
async def cb_words_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.words_input)
    await show(cb, "✍️ Отправляйте команды (можно несколько сообщений подряд):\n"
                   "<code>+ apple - яблоко</code> — добавить\n"
                   "<code>e 12 apple - яблоко</code> — изменить\n"
                   "<code>d 12</code> — удалить", kb.words_cancel())


@router.callback_query(F.data == "words:cancel")
async def cb_words_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(cb, "Готово.", kb.words_menu())


@router.message(StateFilter(Form.words_input), F.text)
async def on_words_command(message: Message, state: FSMContext, db: Database) -> None:
    uid = message.from_user.id
    try:
        action, word_id, pair = parse_edit_command(message.text)
        if action == "add":
            db.add_word(uid, pair[0], pair[1], unit=CUSTOM_UNIT)
            reply = f"➕ Добавлено: {html.escape(pair[0])} — {html.escape(pair[1])}"
        elif action == "edit":
            if db.get_word(uid, word_id) is None:
                raise ParseError(f"Слово {word_id} не найдено.")
            db.update_word(uid, word_id, en=pair[0], ru=pair[1])
            reply = f"✏️ Слово {word_id} обновлено."
        else:
            if db.get_word(uid, word_id) is None:
                raise ParseError(f"Слово {word_id} не найдено.")
            db.delete_word(uid, word_id)
            reply = f"🗑 Слово {word_id} удалено."
    except (ParseError, ValueError) as exc:
        reply = f"⚠️ {html.escape(str(exc))}"
    await message.answer(reply, reply_markup=kb.words_cancel())


# ---------- статистика и баллы ----------
@router.callback_query(F.data == "m:stats")
async def cb_stats(cb: CallbackQuery, db: Database) -> None:
    uid = cb.from_user.id
    totals = db.totals(uid)
    total = totals["total"]
    percent = round(100 * totals["correct"] / total) if total else 0
    lines = [
        "📊 <b>Статистика</b>",
        f"Всего слов: {total}",
        f"✅ Правильных: {totals['correct']}",
        f"❌ Ошибок: {totals['errors']}",
        f"⏭ Пропусков: {totals['skipped']}",
        f"🎯 Процент правильных: {percent}%",
        f"🏆 Баланс: {db.balance(uid)}",
    ]
    by_unit = db.stats_by_unit_part(uid)
    if by_unit:
        lines.append("\n<b>По Unit и Part</b>")
        for row in by_unit:
            pct = round(100 * row["correct"] / row["total"]) if row["total"] else 0
            lines.append(f"Unit {html.escape(row['unit'] or '—')} / Part {html.escape(row['part'] or '—')}: {pct}% ({row['total']} сл.)")
    history = db.history(uid, 10)
    if history:
        lines.append("\n<b>История тренировок</b>")
        for h in history:
            mode = "повтор" if h["mode"] == "retry" else "тренировка"
            lines.append(f"#{h['id']} • Unit {html.escape(h['unit'] or '—')} / {html.escape(h['part'] or '—')} • {mode} • {h['points']:+d} б.")
    await show(cb, "\n".join(lines), kb.back_to_menu())


@router.callback_query(F.data == "m:points")
async def cb_points(cb: CallbackQuery, db: Database) -> None:
    uid = cb.from_user.id
    history = db.history(uid, 5)
    lines = [f"⭐ <b>Мои баллы</b>\n🏆 Общий баланс: <b>{db.balance(uid)}</b>", ""]
    lines += [f"#{h['id']}: {h['points']:+d} б." for h in history] or ["Пока нет тренировок."]
    await show(cb, "\n".join(lines), kb.back_to_menu())


# ---------- источник слов ----------
@router.callback_query(F.data == "m:source")
async def cb_source(cb: CallbackQuery, db: Database) -> None:
    cfg = db.get_settings(cb.from_user.id)
    current = html.escape(cfg["source_url"]) if cfg["source_url"] else "не указан"
    count = len(db.list_words(cb.from_user.id))
    await show(cb, f"🌐 <b>Источник слов</b>\nСсылка: {current}\nСлов в базе: {count}", kb.source_options())


@router.callback_query(F.data == "src:url")
async def cb_src_url(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.source_url)
    await show(cb, "🔗 Пришлите ссылку (https://...) на страницу с таблицей слов и переводами.", kb.back_to_menu())


@router.message(StateFilter(Form.source_url), F.text)
async def on_source_url(message: Message, state: FSMContext, db: Database) -> None:
    uid = message.from_user.id
    await state.clear()
    try:
        url = await asyncio.to_thread(validate_url, message.text)
        rows = await asyncio.to_thread(load_words_from_url, url)
    except (ScrapeError, ValueError) as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}\nМожно ввести слова вручную.", reply_markup=kb.source_error())
        return
    added = db.bulk_add_words(uid, [(r.unit, r.part, r.en, r.ru) for r in rows])
    db.update_settings(uid, source_url=url)
    units = db.list_units(uid)
    await message.answer(
        f"✅ Загружено слов: {len(rows)} (новых: {added}).\nВыберите Unit для тренировки:",
        reply_markup=kb.units(units),
    )


@router.callback_query(F.data == "src:bundled")
async def cb_src_bundled(cb: CallbackQuery, db: Database) -> None:
    rows = load_navigate_rows()
    added = db.bulk_add_words(cb.from_user.id, rows)
    db.update_settings(cb.from_user.id, source_url="встроенный словарь Navigate B1+")
    units = db.list_units(cb.from_user.id)
    await show(cb, f"✅ Словарь Navigate B1+ загружен: {len(rows)} слов (новых: {added}).\n"
                   "Выберите Unit и Part или напишите, например: <code>Unit 4 Part 2</code>",
               kb.units(units))


@router.callback_query(F.data == "src:manual")
async def cb_src_manual(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.manual_words)
    await show(cb, "✍️ Отправьте слова, по одному на строку:\n<code>apple - яблоко</code>\n"
                   "Они сохранятся в раздел «Мои».", kb.back_to_menu())


@router.message(StateFilter(Form.manual_words), F.text)
async def on_manual_words(message: Message, state: FSMContext, db: Database) -> None:
    pairs, bad = parse_word_lines(message.text)
    await state.clear()
    added = db.bulk_add_words(message.from_user.id, [(CUSTOM_UNIT, "", en, ru) for en, ru in pairs])
    text = f"✅ Добавлено слов: {added}."
    if bad:
        text += "\n⚠️ Не распознаны строки:\n" + "\n".join(html.escape(b) for b in bad[:10])
    await message.answer(text, reply_markup=kb.main_menu())


# ---------- настройки ----------
@router.callback_query(F.data == "m:settings")
async def cb_settings(cb: CallbackQuery, db: Database) -> None:
    await show(cb, "⚙️ <b>Настройки</b>", kb.settings(db.get_settings(cb.from_user.id)))


@router.callback_query(F.data.startswith("set:"))
async def cb_set(cb: CallbackQuery, db: Database) -> None:
    uid = cb.from_user.id
    cfg = db.get_settings(uid)
    key = cb.data.split(":", 1)[1]
    if key == "words":
        current = cfg["words_per_session"]
        nxt = SESSION_SIZES[(SESSION_SIZES.index(current) + 1) % len(SESSION_SIZES)] if current in SESSION_SIZES else 10
        db.update_settings(uid, words_per_session=nxt)
    elif key == "shuffle":
        db.update_settings(uid, shuffle=0 if cfg["shuffle"] else 1)
    elif key == "speed":
        db.update_settings(uid, tts_rate=0.7 if cfg["tts_rate"] >= 0.9 else 1.0)
    elif key == "retry":
        db.update_settings(uid, retry_errors=0 if cfg["retry_errors"] else 1)
    await show(cb, "⚙️ <b>Настройки</b>", kb.settings(db.get_settings(uid)))


# ---------- таблица баллов ----------
def _rules_text(db: Database, uid: int) -> str:
    rules = db.get_rules(uid)
    overlaps = find_overlaps(rules)
    text = "📋 <b>Таблица баллов</b>\nНажмите правило, чтобы изменить или удалить."
    if overlaps:
        text += "\n\n⚠️ Есть пересекающиеся диапазоны — будет применено первое подходящее."
    return text


@router.callback_query(F.data == "rules:list")
async def cb_rules_list(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    uid = cb.from_user.id
    await show(cb, _rules_text(db, uid), kb.rules(db.list_rule_rows(uid)))


@router.callback_query(F.data.startswith("rule:"))
async def cb_rule(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    uid = cb.from_user.id
    parts = cb.data.split(":")
    if len(parts) == 2:  # rule:<id>
        rule = _find_rule(db, uid, int(parts[1]))
        if rule is None:
            await cb.answer("Правило не найдено.", show_alert=True)
            return
        await show(cb, f"📋 Правило: <b>{kb.rule_label(rule[1])}</b>", kb.rule_actions(rule[0]))
        return
    action, rule_id = parts[1], int(parts[2])
    if action == "del":
        db.delete_rule(uid, rule_id)
        await show(cb, _rules_text(db, uid), kb.rules(db.list_rule_rows(uid)))
    elif action == "pts":
        await show(cb, "🎯 Выберите баллы за правило:", kb.points_picker(f"ep:{rule_id}"))
    elif action == "range":
        await state.set_state(Form.rule_range_edit)
        await state.update_data(rule_id=rule_id)
        await show(cb, "✏️ Введите новый диапазон ошибок: 5, 3-4 или 11+", kb.rules([]))


def _find_rule(db: Database, uid: int, rule_id: int):
    for rid, rule in db.list_rule_rows(uid):
        if rid == rule_id:
            return rid, rule
    return None


@router.callback_query(F.data == "rules:add")
async def cb_rules_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.rule_range_new)
    await show(cb, "➕ Введите диапазон ошибок: 5, 3-4 или 11+", kb.rules([]))


@router.message(StateFilter(Form.rule_range_new), F.text)
async def on_rule_range_new(message: Message, state: FSMContext) -> None:
    try:
        low, high = parse_range(message.text)
        validate_rule(low, high, 0)
    except ValueError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}")
        return
    await state.update_data(min_errors=low, max_errors=high)
    await message.answer("🎯 Выберите баллы (от -5 до +5):", reply_markup=kb.points_picker("np"))


@router.callback_query(F.data.startswith("np:"))
async def cb_new_rule_points(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    if "min_errors" not in data:
        await cb.answer("Сначала введите диапазон.", show_alert=True)
        return
    points = int(cb.data.split(":", 1)[1])
    try:
        db.add_rule(cb.from_user.id, data["min_errors"], data["max_errors"], points)
    except ValueError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    await state.clear()
    await show(cb, _rules_text(db, cb.from_user.id), kb.rules(db.list_rule_rows(cb.from_user.id)))


@router.message(StateFilter(Form.rule_range_edit), F.text)
async def on_rule_range_edit(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    uid = message.from_user.id
    try:
        low, high = parse_range(message.text)
        current = _find_rule(db, uid, data["rule_id"])
        if current is None:
            raise ValueError("Правило не найдено.")
        db.update_rule(uid, data["rule_id"], low, high, current[1].points)
    except ValueError as exc:
        await message.answer(f"⚠️ {html.escape(str(exc))}")
        return
    await state.clear()
    await message.answer(_rules_text(db, uid), reply_markup=kb.rules(db.list_rule_rows(uid)))


@router.callback_query(F.data.startswith("ep:"))
async def cb_edit_points(cb: CallbackQuery, db: Database) -> None:
    _, rule_id, points = cb.data.split(":")
    uid = cb.from_user.id
    current = _find_rule(db, uid, int(rule_id))
    if current is None:
        await cb.answer("Правило не найдено.", show_alert=True)
        return
    db.update_rule(uid, int(rule_id), current[1].min_errors, current[1].max_errors, int(points))
    await show(cb, _rules_text(db, uid), kb.rules(db.list_rule_rows(uid)))


@router.callback_query(F.data == "rules:reset")
async def cb_rules_reset(cb: CallbackQuery, db: Database) -> None:
    db.reset_rules(cb.from_user.id)
    await show(cb, "♻️ Стандартная таблица восстановлена.\n\n" + _rules_text(db, cb.from_user.id),
               kb.rules(db.list_rule_rows(cb.from_user.id)))


# ---------- ошибки ----------
@router.error()
async def on_error(event) -> bool:
    log.exception("Ошибка при обработке обновления: %s", event.exception)
    update = event.update
    message = getattr(update, "message", None) or getattr(getattr(update, "callback_query", None), "message", None)
    if message is not None:
        try:
            await message.answer("⚠️ Что-то пошло не так. Попробуйте ещё раз или вернитесь в меню.",
                                 reply_markup=kb.back_to_menu())
        except Exception:  # noqa: BLE001
            pass
    return True
