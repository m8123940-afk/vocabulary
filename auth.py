"""Хранение данных в SQLite: пользователи, слова, правила баллов, тренировки."""
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from bot.scoring import DEFAULT_RULES, Rule, compute_points, validate_rule

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    source_url TEXT,
    unit TEXT NOT NULL DEFAULT '',
    part TEXT NOT NULL DEFAULT '',
    words_per_session INTEGER NOT NULL DEFAULT 10,
    shuffle INTEGER NOT NULL DEFAULT 1,
    tts_rate REAL NOT NULL DEFAULT 1.0,
    retry_errors INTEGER NOT NULL DEFAULT 1,
    active_session_id INTEGER
);
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    part TEXT NOT NULL DEFAULT '',
    en TEXT NOT NULL,
    ru TEXT NOT NULL,
    UNIQUE (user_id, unit, part, en)
);
CREATE TABLE IF NOT EXISTS scoring_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    min_errors INTEGER NOT NULL,
    max_errors INTEGER,
    points INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    part TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'train',
    word_ids TEXT NOT NULL,
    current_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    points INTEGER NOT NULL DEFAULT 0,
    awarded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS attempts (
    session_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    correct INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, word_id)
);
"""


@dataclass
class Word:
    id: int
    user_id: int
    unit: str
    part: str
    en: str
    ru: str


@dataclass
class Session:
    id: int
    user_id: int
    unit: str
    part: str
    mode: str
    word_ids: list[int]
    current_index: int
    status: str
    points: int
    awarded: bool


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    # ---------- пользователи и настройки ----------
    def ensure_user(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            count = self._conn.execute(
                "SELECT COUNT(*) FROM scoring_rules WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            if count == 0:
                self._conn.executemany(
                    "INSERT INTO scoring_rules (user_id, min_errors, max_errors, points) VALUES (?, ?, ?, ?)",
                    [(user_id, a, b, p) for a, b, p in DEFAULT_RULES],
                )

    def get_settings(self, user_id: int) -> dict:
        self.ensure_user(user_id)
        row = self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(row)

    _SETTINGS_FIELDS = {"source_url", "unit", "part", "words_per_session", "shuffle", "tts_rate", "retry_errors"}

    def update_settings(self, user_id: int, **fields) -> None:
        self.ensure_user(user_id)
        bad = set(fields) - self._SETTINGS_FIELDS
        if bad:
            raise ValueError(f"Неизвестные настройки: {bad}")
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._execute(f"UPDATE users SET {assignments} WHERE user_id = ?", (*fields.values(), user_id))

    # ---------- слова ----------
    def add_word(self, user_id: int, en: str, ru: str, unit: str = "", part: str = "") -> int:
        en, ru = en.strip(), ru.strip()
        if not en or not ru:
            raise ValueError("Слово и перевод не могут быть пустыми.")
        self.ensure_user(user_id)
        cur = self._execute(
            "INSERT OR REPLACE INTO words (user_id, unit, part, en, ru) VALUES (?, ?, ?, ?, ?)",
            (user_id, unit, part, en, ru),
        )
        return cur.lastrowid

    def bulk_add_words(self, user_id: int, rows: list[tuple[str, str, str, str]]) -> int:
        """rows: (unit, part, en, ru). Возвращает число добавленных слов."""
        self.ensure_user(user_id)
        with self._lock, self._conn:
            before = self._conn.total_changes
            self._conn.executemany(
                "INSERT OR IGNORE INTO words (user_id, unit, part, en, ru) VALUES (?, ?, ?, ?, ?)",
                [(user_id, u, p, en, ru) for u, p, en, ru in rows],
            )
            return self._conn.total_changes - before

    def update_word(self, user_id: int, word_id: int, en: str | None = None, ru: str | None = None) -> None:
        word = self.get_word(user_id, word_id)
        if word is None:
            raise ValueError("Слово не найдено.")
        en = (en if en is not None else word.en).strip()
        ru = (ru if ru is not None else word.ru).strip()
        if not en or not ru:
            raise ValueError("Слово и перевод не могут быть пустыми.")
        self._execute("UPDATE words SET en = ?, ru = ? WHERE id = ? AND user_id = ?", (en, ru, word_id, user_id))

    def delete_word(self, user_id: int, word_id: int) -> None:
        self._execute("DELETE FROM words WHERE id = ? AND user_id = ?", (word_id, user_id))

    def get_word(self, user_id: int, word_id: int) -> Word | None:
        row = self._fetchone("SELECT * FROM words WHERE id = ? AND user_id = ?", (word_id, user_id))
        return Word(**dict(row)) if row else None

    def list_words(self, user_id: int, unit: str | None = None, part: str | None = None) -> list[Word]:
        sql = "SELECT * FROM words WHERE user_id = ?"
        params: list = [user_id]
        if unit is not None:
            sql += " AND unit = ?"
            params.append(unit)
        if part is not None:
            sql += " AND part = ?"
            params.append(part)
        sql += " ORDER BY unit, part, id"
        return [Word(**dict(r)) for r in self._fetchall(sql, tuple(params))]

    def list_units(self, user_id: int) -> list[str]:
        rows = self._fetchall("SELECT DISTINCT unit FROM words WHERE user_id = ? ORDER BY unit", (user_id,))
        return [r["unit"] for r in rows]

    def list_parts(self, user_id: int, unit: str) -> list[str]:
        rows = self._fetchall(
            "SELECT DISTINCT part FROM words WHERE user_id = ? AND unit = ? ORDER BY part", (user_id, unit)
        )
        return [r["part"] for r in rows]

    def clear_words(self, user_id: int) -> None:
        self._execute("DELETE FROM words WHERE user_id = ?", (user_id,))

    # ---------- правила баллов ----------
    def get_rules(self, user_id: int) -> list[Rule]:
        self.ensure_user(user_id)
        rows = self._fetchall(
            "SELECT min_errors, max_errors, points FROM scoring_rules WHERE user_id = ? "
            "ORDER BY min_errors, id",
            (user_id,),
        )
        return [Rule(r["min_errors"], r["max_errors"], r["points"]) for r in rows]

    def list_rule_rows(self, user_id: int) -> list[tuple[int, Rule]]:
        self.ensure_user(user_id)
        rows = self._fetchall(
            "SELECT id, min_errors, max_errors, points FROM scoring_rules WHERE user_id = ? "
            "ORDER BY min_errors, id",
            (user_id,),
        )
        return [(r["id"], Rule(r["min_errors"], r["max_errors"], r["points"])) for r in rows]

    def add_rule(self, user_id: int, min_errors: int, max_errors: int | None, points: int) -> int:
        validate_rule(min_errors, max_errors, points)
        self.ensure_user(user_id)
        return self._execute(
            "INSERT INTO scoring_rules (user_id, min_errors, max_errors, points) VALUES (?, ?, ?, ?)",
            (user_id, min_errors, max_errors, points),
        ).lastrowid

    def update_rule(self, user_id: int, rule_id: int, min_errors: int, max_errors: int | None, points: int) -> None:
        validate_rule(min_errors, max_errors, points)
        self._execute(
            "UPDATE scoring_rules SET min_errors = ?, max_errors = ?, points = ? WHERE id = ? AND user_id = ?",
            (min_errors, max_errors, points, rule_id, user_id),
        )

    def delete_rule(self, user_id: int, rule_id: int) -> None:
        self._execute("DELETE FROM scoring_rules WHERE id = ? AND user_id = ?", (rule_id, user_id))

    def reset_rules(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM scoring_rules WHERE user_id = ?", (user_id,))
            self._conn.executemany(
                "INSERT INTO scoring_rules (user_id, min_errors, max_errors, points) VALUES (?, ?, ?, ?)",
                [(user_id, a, b, p) for a, b, p in DEFAULT_RULES],
            )

    # ---------- тренировки ----------
    def create_session(self, user_id: int, unit: str, part: str, word_ids: list[int], mode: str = "train") -> int:
        self.ensure_user(user_id)
        return self._execute(
            "INSERT INTO sessions (user_id, unit, part, mode, word_ids) VALUES (?, ?, ?, ?, ?)",
            (user_id, unit, part, mode, json.dumps(word_ids)),
        ).lastrowid

    def get_session(self, user_id: int, session_id: int) -> Session | None:
        row = self._fetchone("SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
        if row is None:
            return None
        return Session(
            id=row["id"], user_id=row["user_id"], unit=row["unit"], part=row["part"], mode=row["mode"],
            word_ids=json.loads(row["word_ids"]), current_index=row["current_index"], status=row["status"],
            points=row["points"], awarded=bool(row["awarded"]),
        )

    def set_active_session(self, user_id: int, session_id: int | None) -> None:
        self._execute("UPDATE users SET active_session_id = ? WHERE user_id = ?", (session_id, user_id))

    def get_active_session_id(self, user_id: int) -> int | None:
        self.ensure_user(user_id)
        row = self._fetchone("SELECT active_session_id FROM users WHERE user_id = ?", (user_id,))
        return row["active_session_id"]

    def set_current_index(self, session_id: int, index: int) -> None:
        self._execute("UPDATE sessions SET current_index = ? WHERE id = ?", (index, session_id))

    def record_attempt(self, session_id: int, word_id: int, correct: bool, skipped: bool, errors: int) -> None:
        """Записывает результат слова. Повторный вызов для того же слова обновляет запись."""
        self._execute(
            "INSERT INTO attempts (session_id, word_id, correct, skipped, errors) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, word_id) DO UPDATE SET correct = excluded.correct, "
            "skipped = excluded.skipped, errors = excluded.errors",
            (session_id, word_id, int(correct), int(skipped), errors),
        )

    def session_attempts(self, session_id: int) -> list[sqlite3.Row]:
        return self._fetchall("SELECT * FROM attempts WHERE session_id = ?", (session_id,))

    def wrong_word_ids(self, session_id: int) -> list[int]:
        rows = self._fetchall(
            "SELECT word_id FROM attempts WHERE session_id = ? AND (correct = 0 OR skipped = 1)", (session_id,)
        )
        return [r["word_id"] for r in rows]

    def finish_session(self, user_id: int, session_id: int) -> int:
        """Начисляет баллы ровно один раз. Возвращает начисленные баллы (0 при повторном вызове)."""
        session = self.get_session(user_id, session_id)
        if session is None:
            raise ValueError("Тренировка не найдена.")
        if session.awarded:
            return 0
        errors = sum(1 for a in self.session_attempts(session_id) if a["errors"] > 0 or a["skipped"])
        # Повторы ошибок (mode='retry') баллов не дают: баллы — только за основную тренировку.
        points = compute_points(self.get_rules(user_id), errors) if session.mode == "train" else 0
        with self._lock, self._conn:
            # Условие awarded = 0 делает начисление атомарным: повторный вызов ничего не изменит.
            cur = self._conn.execute(
                "UPDATE sessions SET status = 'finished', awarded = 1, points = ? WHERE id = ? AND awarded = 0",
                (points, session_id),
            )
            if cur.rowcount == 0:
                return 0
        return points

    def balance(self, user_id: int) -> int:
        row = self._fetchone(
            "SELECT COALESCE(SUM(points), 0) AS total FROM sessions WHERE user_id = ? AND awarded = 1", (user_id,)
        )
        return int(row["total"])

    def history(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM sessions WHERE user_id = ? AND status = 'finished' ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )

    def stats_by_unit_part(self, user_id: int) -> list[sqlite3.Row]:
        """Статистика по Unit и Part: сколько слов проверено и какой процент верных."""
        return self._fetchall(
            """
            SELECT s.unit AS unit, s.part AS part,
                   COUNT(a.word_id) AS total,
                   SUM(CASE WHEN a.correct = 1 AND a.skipped = 0 THEN 1 ELSE 0 END) AS correct
            FROM attempts a JOIN sessions s ON s.id = a.session_id
            WHERE s.user_id = ? AND s.mode = 'train'
            GROUP BY s.unit, s.part ORDER BY s.unit, s.part
            """,
            (user_id,),
        )

    def totals(self, user_id: int) -> dict:
        row = self._fetchone(
            """
            SELECT COUNT(a.word_id) AS total,
                   COALESCE(SUM(CASE WHEN a.correct = 1 AND a.skipped = 0 THEN 1 ELSE 0 END), 0) AS correct,
                   COALESCE(SUM(CASE WHEN a.errors > 0 AND a.skipped = 0 THEN 1 ELSE 0 END), 0) AS errors,
                   COALESCE(SUM(a.skipped), 0) AS skipped
            FROM attempts a JOIN sessions s ON s.id = a.session_id
            WHERE s.user_id = ? AND s.mode = 'train'
            """,
            (user_id,),
        )
        return dict(row)
