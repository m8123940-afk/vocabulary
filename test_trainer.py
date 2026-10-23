import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from bot.bundled import load_navigate_rows
from bot.db import Database
from miniapp.auth import AuthError, verify_init_data
from miniapp.server import create_app

TOKEN = "123456:TEST-TOKEN"


def sign(user_id: int, token: str = TOKEN, auth_date: int | None = None) -> str:
    """Формирует initData так же, как Telegram: поля, подписанные HMAC от токена бота."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":"), ensure_ascii=False),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def client(tmp_path):
    db = Database(tmp_path / "app.sqlite3")
    yield TestClient(create_app(db, TOKEN)), db
    db.close()


def auth(uid: int = 1) -> dict:
    return {"Authorization": "tma " + sign(uid)}


# ---------- проверка подписи ----------
def test_valid_signature_returns_user_id():
    assert verify_init_data(sign(42), TOKEN) == 42


def test_wrong_token_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign(42, token="999:OTHER"), TOKEN)


def test_tampered_user_rejected():
    init = sign(42).replace("%22id%22%3A42", "%22id%22%3A43")
    with pytest.raises(AuthError):
        verify_init_data(init, TOKEN)


def test_expired_data_rejected():
    with pytest.raises(AuthError):
        verify_init_data(sign(42, auth_date=int(time.time()) - 2 * 24 * 3600), TOKEN)


def test_missing_hash_rejected():
    with pytest.raises(AuthError):
        verify_init_data("auth_date=1&user=%7B%7D", TOKEN)


# ---------- доступ к API ----------
def test_api_requires_telegram_auth(client):
    c, _ = client
    assert c.get("/api/settings").status_code == 401
    assert c.get("/api/settings", headers={"Authorization": "tma " + sign(1, token="x:bad")}).status_code == 401


def test_users_are_isolated(client):
    c, _ = client
    c.post("/api/words", json={"en": "cat", "ru": "кот"}, headers=auth(1))
    assert c.get("/api/words", headers=auth(2)).json() == []


def test_static_app_is_served(client):
    c, _ = client
    res = c.get("/")
    assert res.status_code == 200 and "Английские слова" in res.text


# ---------- основной сценарий ----------
def test_full_training_flow_through_api(client):
    c, db = client
    h = auth(7)
    assert c.post("/api/source/bundled", headers=h).json()["loaded"] == 800
    units = c.get("/api/train/units", headers=h).json()
    assert {u["unit"] for u in units} == {str(i) for i in range(1, 13)}
    c.put("/api/settings", json={"words_per_session": 100, "shuffle": False}, headers=h)

    st = c.post("/api/train/start", json={"unit": "4", "part": "2"}, headers=h).json()
    assert st["active"] and st["total"] == 19 and st["word_en"]

    # Правильный ответ: берём перевод из базы (как если бы пользователь сказал его голосом).
    sid = st["session_id"]
    word = db.get_word(7, db.get_session(7, sid).word_ids[0])
    ans = c.post("/api/train/answer", json={"said": "ничего не то", "alternatives": [word.ru.split(";")[0]]}, headers=h).json()
    assert ans["correct"] is True and ans["done"] == 1

    # Второе слово — пропуск.
    skip = c.post("/api/train/skip", headers=h).json()
    assert skip["skipped"] is True and skip["done"] == 2

    # Пустой ответ (речь не распознана) — без штрафа.
    assert c.post("/api/train/answer", json={"said": "", "alternatives": []}, headers=h).status_code == 400
    assert db.get_session(7, sid).current_index == 2

    # Досрочно завершаем тренировку: баллы начисляются один раз.
    rep = c.post("/api/train/finish", headers=h).json()
    assert rep["total"] == 19 and rep["skipped"] == 1 and rep["mode"] == "train"
    assert c.post("/api/train/finish", headers=h).status_code == 409  # активной тренировки уже нет
    assert c.get("/api/points", headers=h).json()["balance"] == rep["balance"]


def test_retry_gives_no_points(client):
    c, db = client
    h = auth(3)
    c.post("/api/words", json={"en": "cat", "ru": "кот", "unit": "1", "part": "1"}, headers=h)
    c.post("/api/words", json={"en": "dog", "ru": "собака", "unit": "1", "part": "1"}, headers=h)
    c.put("/api/settings", json={"shuffle": False}, headers=h)
    c.post("/api/train/start", json={"unit": "1", "part": "1"}, headers=h)
    c.post("/api/train/answer", json={"said": "стол", "alternatives": []}, headers=h)
    c.post("/api/train/skip", headers=h)
    rep = c.post("/api/train/finish", headers=h).json()
    balance = rep["balance"]
    assert rep["wrong_ids"]
    retry = c.post(f"/api/train/retry/{rep['session_id']}", headers=h).json()
    assert retry["mode"] == "retry"
    c.post("/api/train/answer", json={"said": "кот", "alternatives": []}, headers=h)
    c.post("/api/train/answer", json={"said": "собака", "alternatives": []}, headers=h)
    retry_rep = c.post("/api/train/finish", headers=h).json()
    assert retry_rep["points"] == 0
    assert c.get("/api/points", headers=h).json()["balance"] == balance


def test_words_crud(client):
    c, _ = client
    h = auth(5)
    wid = c.post("/api/words", json={"en": "apple", "ru": "яблоко"}, headers=h).json()["id"]
    assert c.put(f"/api/words/{wid}", json={"ru": "яблоки"}, headers=h).status_code == 200
    assert c.get("/api/words", headers=h).json()[0]["ru"] == "яблоки"
    assert c.delete(f"/api/words/{wid}", headers=h).status_code == 200
    assert c.get("/api/words", headers=h).json() == []


def test_scoring_rules_crud_and_reset(client):
    c, _ = client
    h = auth(9)
    data = c.get("/api/rules", headers=h).json()
    assert len(data["rules"]) == 6 and data["overlaps"] == 0
    rid = c.post("/api/rules", json={"min_errors": 20, "max_errors": None, "points": -5}, headers=h).json()["id"]
    assert any(r["id"] == rid for r in c.get("/api/rules", headers=h).json()["rules"])
    assert c.put(f"/api/rules/{rid}", json={"min_errors": 20, "max_errors": 25, "points": 3}, headers=h).status_code == 200
    assert c.post("/api/rules", json={"min_errors": 0, "max_errors": 0, "points": 9}, headers=h).status_code == 400
    assert c.post("/api/rules/reset", headers=h).status_code == 200
    assert len(c.get("/api/rules", headers=h).json()["rules"]) == 6


def test_settings_validation(client):
    c, _ = client
    h = auth(4)
    assert c.put("/api/settings", json={"words_per_session": 0}, headers=h).status_code == 400
    assert c.put("/api/settings", json={"tts_rate": 9}, headers=h).status_code == 400
    s = c.put("/api/settings", json={"words_per_session": 15, "shuffle": False, "tts_rate": 0.7}, headers=h).json()
    assert s["words_per_session"] == 15 and s["shuffle"] is False and s["tts_rate"] == 0.7


def test_unsafe_url_rejected_by_api(client):
    c, _ = client
    for url in ["file:///etc/passwd", "http://127.0.0.1/admin", "http://localhost/x"]:
        assert c.post("/api/source/url", json={"url": url}, headers=auth(6)).status_code == 400


def test_manual_words_and_stats(client):
    c, _ = client
    h = auth(8)
    res = c.post("/api/source/manual", json={"text": "cat - кот\nбессмыслица\ndog: собака"}, headers=h).json()
    assert res["added"] == 2 and res["bad"] == ["бессмыслица"]
    stats = c.get("/api/stats", headers=h).json()
    assert stats["totals"]["total"] == 0 and stats["balance"] == 0
