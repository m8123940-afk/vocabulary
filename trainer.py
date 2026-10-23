"""Озвучивание слов (TTS) и распознавание ответов (STT).

TTS: gTTS (бесплатно, использует онлайн-сервис Google Translate TTS, без ключа).
STT: OpenAI Whisper API (платно, нужен OPENAI_API_KEY, STT_PROVIDER=openai).
Если STT не настроен, бот просит ответить текстом — тренировка не блокируется.
Альтернативы: локальный Vosk (бесплатно, офлайн, нужна модель и ffmpeg),
или Yandex SpeechKit / Google Cloud Speech-to-Text (платно, есть free-квоты).
"""
import asyncio
import io
import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)
WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"


class SpeechUnavailable(Exception):
    """Распознавание речи не настроено или временно недоступно."""


class Recognizer(Protocol):
    async def transcribe(self, audio: bytes, filename: str) -> str | None: ...


class WhisperRecognizer:
    def __init__(self, api_key: str, model: str = "whisper-1", language: str = "ru"):
        self._api_key = api_key
        self._model = model
        self._language = language

    async def transcribe(self, audio: bytes, filename: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    WHISPER_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data={"model": self._model, "language": self._language},
                    files={"file": (filename, audio, "audio/ogg")},
                )
        except httpx.HTTPError as exc:
            log.warning("Whisper недоступен: %s", exc)
            raise SpeechUnavailable("Сервис распознавания речи временно недоступен.") from exc
        if response.status_code != 200:
            log.warning("Whisper ответил %s: %s", response.status_code, response.text[:200])
            raise SpeechUnavailable("Сервис распознавания речи вернул ошибку.")
        text = response.json().get("text", "").strip()
        return text or None


class NoRecognizer:
    async def transcribe(self, audio: bytes, filename: str) -> str | None:
        raise SpeechUnavailable("Распознавание речи не настроено. Ответьте текстом.")


def build_recognizer(provider: str, api_key: str | None) -> Recognizer:
    if provider == "openai" and api_key:
        return WhisperRecognizer(api_key)
    return NoRecognizer()


def _synthesize_sync(text: str, slow: bool) -> bytes:
    from gtts import gTTS  # импорт здесь, чтобы тесты не требовали сеть

    buffer = io.BytesIO()
    gTTS(text=text, lang="en", slow=slow).write_to_fp(buffer)
    return buffer.getvalue()


async def synthesize(text: str, tts_rate: float = 1.0) -> bytes | None:
    """Возвращает MP3 с произношением слова или None, если синтез недоступен."""
    slow = tts_rate < 0.9
    try:
        return await asyncio.to_thread(_synthesize_sync, text, slow)
    except Exception as exc:  # сеть, лимиты сервиса и т.п. — бот продолжит работу без аудио
        log.warning("Синтез речи не удался: %s", exc)
        return None
