"""Загрузка настроек из переменных окружения (.env)."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: str
    openai_api_key: str | None  # опционально: распознавание речи через Whisper API (платно)
    stt_provider: str           # "openai" или "none"
    miniapp_url: str | None     # HTTPS-адрес мини-приложения (MINIAPP_URL)


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и укажите токен.")
    return Settings(
        bot_token=token,
        db_path=os.getenv("DB_PATH", "english_bot.sqlite3"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        stt_provider=os.getenv("STT_PROVIDER", "none").lower(),
        miniapp_url=os.getenv("MINIAPP_URL") or None,
    )
