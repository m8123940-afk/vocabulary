"""Сквозная проверка обработчиков тренировки с фейковым ботом (без сети и Telegram)."""
import asyncio

import pytest

from bot import handlers
from bot.trainer import start_training


class FakeBot:
    def __init__(self):
        self.messages: list[str] = []
        self.audios: int = 0

    async def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append(text)

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None):
        self.audios += 1
        self.messages.append(caption or "")


@pytest.fixture(autouse=True)
def no_tts(monkeypatch):
    async def none(text, rate=1.0):
        return None  # имитируем недоступный TTS: бот должен показать слово текстом
    monkeypatch.setattr(handlers, "synthesize", none)


def test_answer_flow_and_single_award(db):
    db.bulk_add_words(1, [("1", "A", "cat", "кот"), ("1", "A", "dog", "собака")])
    db.update_settings(1, shuffle=0, retry_errors=0)
    bot = FakeBot()
    start_training(db, 1, "1", "A")

    async def run():
        await handlers.process_answer(bot, 10, 1, db, "кот")      # верно
        await handlers.process_answer(bot, 10, 1, db, "стол")     # неверно → отчёт
        await handlers.send_report(bot, 10, 1, db)                # повторный вызов ничего не начисляет

    asyncio.run(run())
    text = "\n".join(bot.messages)
    assert "Верно" in text and "Неверно" in text
    assert "Тренировка завершена" in text
    assert db.balance(1) == 5
    assert db.get_active_session_id(1) is None
    assert sum(1 for m in bot.messages if "Тренировка завершена" in m) == 1


def test_retry_errors_setting_starts_retry_without_points(db):
    db.bulk_add_words(1, [("1", "A", "cat", "кот"), ("1", "A", "dog", "собака")])
    db.update_settings(1, shuffle=0, retry_errors=1)
    bot = FakeBot()
    start_training(db, 1, "1", "A")

    async def run():
        await handlers.process_answer(bot, 10, 1, db, "стол")
        await handlers.process_answer(bot, 10, 1, db, "кот")

    asyncio.run(run())
    assert any("Повторяем ошибки" in m for m in bot.messages)
    # Основная тренировка: одна ошибка → +5. Открытый повтор баллов не даёт.
    assert db.balance(1) == 5


def test_empty_bank_shows_no_crash_on_session_start(db):
    with pytest.raises(ValueError):
        start_training(db, 1, "1", "A")
