"""HTTP API Telegram Mini App. Использует те же модули, что и бот: БД, тренер, баллы, парсер, безопасность URL.

Запуск: uvicorn miniapp.server:get_app --factory --host 0.0.0.0 --port 8000
Бот и приложение читают одну и ту же базу (DB_PATH).
"""
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bot import trainer
from bot.answer_check import is_answer_correct
from bot.bundled import load_navigate_rows
from bot.db import Database
from bot.parsing import parse_word_lines
from bot.scoring import find_overlaps
from bot.scraper import ScrapeError, load_words_from_url
from bot.url_safety import UnsafeUrlError, validate_url
from miniapp.auth import AuthError, verify_init_data

STATIC_DIR = Path(__file__).parent / "static"
CUSTOM_UNIT = "Мои"


class StartIn(BaseModel):
    unit: str
    part: str = "*"


class AnswerIn(BaseModel):
    said: str = ""
    alternatives: list[str] = []


class WordIn(BaseModel):
    en: str
    ru: str
    unit: str = CUSTOM_UNIT
    part: str = ""


class WordPatch(BaseModel):
    en: Optional[str] = None
    ru: Optional[str] = None


class UrlIn(BaseModel):
    url: str


class TextIn(BaseModel):
    text: str


class SettingsIn(BaseModel):
    words_per_session: Optional[int] = None
    shuffle: Optional[bool] = None
    tts_rate: Optional[float] = None
    retry_errors: Optional[bool] = None


class RuleIn(BaseModel):
    min_errors: int
    max_errors: Optional[int] = None
    points: int


def create_app(db: Database, bot_token: str, dev_mode: bool = False) -> FastAPI:
    app = FastAPI(title="English words mini app")

    # Ошибки предметной логики (ValueError) превращаем в понятный ответ 400.
    @app.exception_handler(ValueError)
    async def value_error(_, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(UnsafeUrlError)
    async def unsafe_url(_, exc: UnsafeUrlError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ScrapeError)
    async def scrape_error(_, exc: ScrapeError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def current_user(authorization: str = Header(default="")) -> int:
        # Режим разработки (MINIAPP_DEV_MODE=1): «dev:<id>» вместо подписи Telegram. В продакшене выключен.
        if dev_mode and authorization.startswith("dev:"):
            try:
                uid = int(authorization[4:])
            except ValueError:
                raise HTTPException(401, "Нет доступа")
            db.ensure_user(uid)
            return uid
        if not authorization.startswith("tma "):
            raise HTTPException(401, "Откройте приложение из Telegram")
        try:
            uid = verify_init_data(authorization[4:], bot_token)
        except AuthError as exc:
            raise HTTPException(401, str(exc))
        db.ensure_user(uid)
        return uid

    def _require_active(uid: int) -> int:
        sid = db.get_active_session_id(uid)
        if sid is None:
            raise HTTPException(409, "Нет активной тренировки")
        return sid

    def _errors(sid: int) -> int:
        return sum(1 for a in db.session_attempts(sid) if a["errors"] > 0 and not a["skipped"])

    def _state(uid: int) -> dict:
        sid = db.get_active_session_id(uid)
        if sid is None:
            return {"active": False}
        session = db.get_session(uid, sid)
        word = trainer.current_word(db, uid, sid)
        return {
            "active": True, "session_id": sid, "mode": session.mode,
            "unit": session.unit, "part": session.part,
            "index": session.current_index, "total": len(session.word_ids),
            "word_en": word.en if word else None, "errors": _errors(sid),
        }

    # ---------- тренировка ----------
    @app.get("/api/train/state")
    def train_state(uid: int = Depends(current_user)):
        return _state(uid)

    @app.get("/api/train/units")
    def train_units(uid: int = Depends(current_user)):
        out = []
        for unit in db.list_units(uid):
            parts = [{"part": p, "count": len(db.list_words(uid, unit=unit, part=p))} for p in db.list_parts(uid, unit)]
            out.append({"unit": unit, "parts": parts, "count": sum(p["count"] for p in parts)})
        return out

    @app.post("/api/train/start")
    def train_start(body: StartIn, uid: int = Depends(current_user)):
        if db.get_active_session_id(uid) is not None:
            raise HTTPException(409, "Тренировка уже идёт. Завершите её.")
        trainer.start_training(db, uid, body.unit, body.part)
        return _state(uid)

    @app.post("/api/train/answer")
    def train_answer(body: AnswerIn, uid: int = Depends(current_user)):
        sid = _require_active(uid)
        candidates = [c.strip() for c in [body.said, *body.alternatives] if c and c.strip()]
        if not candidates:
            raise HTTPException(400, "Речь не распознана — повторите, штрафа нет.")
        word = trainer.current_word(db, uid, sid)
        if word is None:
            raise HTTPException(409, "Тренировка уже завершена.")
        # Если любой из вариантов распознавания верный, засчитываем его.
        said = next((c for c in candidates if is_answer_correct(c, word.ru)), candidates[0])
        res = trainer.submit_answer(db, uid, sid, said)
        return {"correct": res.correct, "said": said, "en": res.word.en, "ru": res.word.ru,
                "done": res.done, "total": res.total, "errors": _errors(sid)}

    @app.post("/api/train/skip")
    def train_skip(uid: int = Depends(current_user)):
        sid = _require_active(uid)
        res = trainer.skip_word(db, uid, sid)
        return {"correct": False, "skipped": True, "en": res.word.en, "ru": res.word.ru,
                "done": res.done, "total": res.total, "errors": _errors(sid)}

    @app.post("/api/train/finish")
    def train_finish(uid: int = Depends(current_user)):
        sid = _require_active(uid)
        return trainer.finish(db, uid, sid)

    @app.post("/api/train/retry/{source_id}")
    def train_retry(source_id: int, uid: int = Depends(current_user)):
        session = db.get_session(uid, source_id)
        if session is None:
            raise HTTPException(404, "Тренировка не найдена")
        wrong = db.wrong_word_ids(source_id)
        if not wrong:
            raise HTTPException(400, "Ошибок нет — повторять нечего.")
        if db.get_active_session_id(uid) is not None:
            raise HTTPException(409, "Тренировка уже идёт.")
        trainer.start_training(db, uid, session.unit, session.part, mode="retry", word_ids=wrong)
        return _state(uid)

    @app.post("/api/train/again")
    def train_again(uid: int = Depends(current_user)):
        last = db.history(uid, 1)
        if not last:
            raise HTTPException(400, "Сначала пройдите тренировку.")
        if db.get_active_session_id(uid) is not None:
            raise HTTPException(409, "Тренировка уже идёт.")
        trainer.start_training(db, uid, last[0]["unit"], last[0]["part"])
        return _state(uid)

    # ---------- слова ----------
    @app.get("/api/words")
    def words_list(uid: int = Depends(current_user)):
        return [asdict(w) for w in db.list_words(uid)]

    @app.post("/api/words")
    def words_add(body: WordIn, uid: int = Depends(current_user)):
        return {"id": db.add_word(uid, body.en, body.ru, unit=body.unit, part=body.part)}

    @app.put("/api/words/{word_id}")
    def words_update(word_id: int, body: WordPatch, uid: int = Depends(current_user)):
        db.update_word(uid, word_id, en=body.en, ru=body.ru)
        return {"ok": True}

    @app.delete("/api/words/{word_id}")
    def words_delete(word_id: int, uid: int = Depends(current_user)):
        db.delete_word(uid, word_id)
        return {"ok": True}

    # ---------- источник слов ----------
    @app.post("/api/source/bundled")
    def source_bundled(uid: int = Depends(current_user)):
        rows = load_navigate_rows()
        added = db.bulk_add_words(uid, rows)
        db.update_settings(uid, source_url="встроенный словарь Navigate B1+")
        return {"loaded": len(rows), "added": added}

    @app.post("/api/source/url")
    def source_url(body: UrlIn, uid: int = Depends(current_user)):
        url = validate_url(body.url)
        rows = load_words_from_url(url)
        added = db.bulk_add_words(uid, [(r.unit, r.part, r.en, r.ru) for r in rows])
        db.update_settings(uid, source_url=url)
        return {"loaded": len(rows), "added": added}

    @app.post("/api/source/manual")
    def source_manual(body: TextIn, uid: int = Depends(current_user)):
        pairs, bad = parse_word_lines(body.text)
        added = db.bulk_add_words(uid, [(CUSTOM_UNIT, "", en, ru) for en, ru in pairs])
        return {"added": added, "bad": bad}

    # ---------- статистика, баллы, настройки ----------
    @app.get("/api/stats")
    def stats(uid: int = Depends(current_user)):
        totals = db.totals(uid)
        return {
            "totals": totals,
            "percent": round(100 * totals["correct"] / totals["total"]) if totals["total"] else 0,
            "balance": db.balance(uid),
            "by_unit_part": [dict(r) for r in db.stats_by_unit_part(uid)],
            "history": [dict(h) for h in db.history(uid, 10)],
        }

    @app.get("/api/points")
    def points(uid: int = Depends(current_user)):
        return {"balance": db.balance(uid), "history": [dict(h) for h in db.history(uid, 20)]}

    @app.get("/api/settings")
    def get_settings(uid: int = Depends(current_user)):
        cfg = db.get_settings(uid)
        return {"words_per_session": cfg["words_per_session"], "shuffle": bool(cfg["shuffle"]),
                "tts_rate": cfg["tts_rate"], "retry_errors": bool(cfg["retry_errors"]),
                "source_url": cfg["source_url"]}

    @app.put("/api/settings")
    def put_settings(body: SettingsIn, uid: int = Depends(current_user)):
        fields = {}
        if body.words_per_session is not None:
            if not 1 <= body.words_per_session <= 100:
                raise ValueError("Слов за тренировку: от 1 до 100.")
            fields["words_per_session"] = body.words_per_session
        if body.shuffle is not None:
            fields["shuffle"] = int(body.shuffle)
        if body.tts_rate is not None:
            if not 0.5 <= body.tts_rate <= 1.5:
                raise ValueError("Скорость озвучки: от 0.5 до 1.5.")
            fields["tts_rate"] = body.tts_rate
        if body.retry_errors is not None:
            fields["retry_errors"] = int(body.retry_errors)
        db.update_settings(uid, **fields)
        return get_settings(uid)

    @app.get("/api/rules")
    def rules_list(uid: int = Depends(current_user)):
        rows = db.list_rule_rows(uid)
        rules = [{"id": rid, "min_errors": r.min_errors, "max_errors": r.max_errors, "points": r.points}
                 for rid, r in rows]
        overlaps = find_overlaps([r for _, r in rows])
        return {"rules": rules, "overlaps": len(overlaps)}

    @app.post("/api/rules")
    def rules_add(body: RuleIn, uid: int = Depends(current_user)):
        return {"id": db.add_rule(uid, body.min_errors, body.max_errors, body.points)}

    @app.put("/api/rules/{rule_id}")
    def rules_update(rule_id: int, body: RuleIn, uid: int = Depends(current_user)):
        db.update_rule(uid, rule_id, body.min_errors, body.max_errors, body.points)
        return {"ok": True}

    @app.delete("/api/rules/{rule_id}")
    def rules_delete(rule_id: int, uid: int = Depends(current_user)):
        db.delete_rule(uid, rule_id)
        return {"ok": True}

    @app.post("/api/rules/reset")
    def rules_reset(uid: int = Depends(current_user)):
        db.reset_rules(uid)
        return {"ok": True}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def get_app() -> FastAPI:
    """Фабрика для uvicorn: читает настройки из .env, как бот."""
    from bot.config import load_settings
    settings = load_settings()
    db = Database(settings.db_path)
    return create_app(db, settings.bot_token, dev_mode=os.getenv("MINIAPP_DEV_MODE") == "1")
