import pytest

from bot.scoring import DEFAULT_RULES


def test_default_rules_seeded_for_new_user(db):
    rules = db.get_rules(1)
    assert [(r.min_errors, r.max_errors, r.points) for r in rules] == DEFAULT_RULES


def test_rules_edit_persist_across_reopen(tmp_path):
    from bot.db import Database
    path = tmp_path / "p.sqlite3"
    first = Database(path)
    rule_id = first.add_rule(7, 12, 13, -2)
    first.update_rule(7, rule_id, 12, 14, 4)
    first.close()
    second = Database(path)
    assert (12, 14, 4) in [(r.min_errors, r.max_errors, r.points) for r in second.get_rules(7)]
    second.close()


def test_reset_rules_restores_defaults(db):
    db.add_rule(1, 20, None, 3)
    db.delete_rule(1, db.list_rule_rows(1)[0][0])
    db.reset_rules(1)
    assert [(r.min_errors, r.max_errors, r.points) for r in db.get_rules(1)] == DEFAULT_RULES


def test_words_crud_and_user_isolation(db):
    wid = db.add_word(1, "apple", "яблоко", unit="1", part="A")
    assert db.get_word(2, wid) is None  # другой пользователь не видит слово
    db.update_word(1, wid, ru="яблоки")
    assert db.get_word(1, wid).ru == "яблоки"
    db.delete_word(1, wid)
    assert db.get_word(1, wid) is None


def test_bulk_add_skips_duplicates(db):
    added = db.bulk_add_words(1, [("1", "A", "cat", "кот"), ("1", "A", "cat", "кот"), ("1", "B", "dog", "собака")])
    assert added == 2
    assert db.list_units(1) == ["1"]
    assert db.list_parts(1, "1") == ["A", "B"]


def test_empty_word_rejected(db):
    with pytest.raises(ValueError):
        db.add_word(1, "  ", "яблоко")


def test_settings_roundtrip_and_unknown_field_rejected(db):
    db.update_settings(1, words_per_session=15, shuffle=0)
    cfg = db.get_settings(1)
    assert cfg["words_per_session"] == 15 and cfg["shuffle"] == 0
    with pytest.raises(ValueError):
        db.update_settings(1, evil="x")


def test_points_awarded_exactly_once(db):
    from bot.trainer import finish, start_training, submit_answer
    db.bulk_add_words(1, [("1", "A", "cat", "кот"), ("1", "A", "dog", "собака")])
    sid = start_training(db, 1, "1", "A")
    submit_answer(db, 1, sid, "кот")
    submit_answer(db, 1, sid, "кот")  # второе слово тоже проверяется
    first = finish(db, 1, sid)
    assert first["points"] == 5
    assert db.finish_session(1, sid) == 0  # повторное начисление невозможно
    assert db.balance(1) == 5
