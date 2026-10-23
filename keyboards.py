"""Проверка русского перевода с учётом синонимов и нескольких вариантов.

В базе перевод может быть записан как «кот; кошка; котик» или «дом (здание)».
Содержимое скобок — синоним или пояснение, тоже принимается. Разделители: ; , / |.
"""
import re
from difflib import SequenceMatcher

SEPARATORS = re.compile(r"[;,/|]")
PARENS = re.compile(r"\(([^)]*)\)")
NOISE = re.compile(r"[^а-яa-z0-9\s]")
FUZZY_THRESHOLD = 0.8


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = NOISE.sub(" ", text)
    return " ".join(text.split())


def split_translations(ru: str) -> list[str]:
    """Разбирает поле перевода на отдельные варианты.

    «дом (здание)» даёт варианты «дом» и «здание»: содержимое скобок тоже считается синонимом.
    """
    without = PARENS.sub(" ; ", ru)
    inside = [m for m in PARENS.findall(ru)]
    pieces = SEPARATORS.split(without) + [part for chunk in inside for part in SEPARATORS.split(chunk)]
    variants = [normalize(part) for part in pieces]
    return [v for v in variants if v]


def is_answer_correct(user_answer: str, ru: str) -> bool:
    answer = normalize(user_answer)
    if not answer:
        return False
    for variant in split_translations(ru):
        if answer == variant:
            return True
        # Допускаем небольшие ошибки распознавания (окончания, одна буква).
        if SequenceMatcher(None, answer, variant).ratio() >= FUZZY_THRESHOLD:
            return True
    return False
