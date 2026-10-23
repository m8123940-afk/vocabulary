"""Правила начисления баллов.

Правило: диапазон ошибок [min_errors, max_errors] -> points (от -5 до +5).
max_errors = None означает «и более».
"""
from dataclasses import dataclass

POINTS_MIN = -5
POINTS_MAX = 5

DEFAULT_RULES = [
    (0, 2, 5),
    (3, 4, 4),
    (5, 6, 3),
    (7, 8, 2),
    (9, 10, 1),
    (11, None, 0),
]


@dataclass(frozen=True)
class Rule:
    min_errors: int
    max_errors: int | None
    points: int


def validate_rule(min_errors: int, max_errors: int | None, points: int) -> None:
    if min_errors < 0:
        raise ValueError("Минимум ошибок не может быть меньше 0.")
    if max_errors is not None and max_errors < min_errors:
        raise ValueError("Максимум ошибок меньше минимума.")
    if not POINTS_MIN <= points <= POINTS_MAX:
        raise ValueError(f"Баллы должны быть от {POINTS_MIN} до {POINTS_MAX}.")


def find_overlaps(rules: list[Rule]) -> list[tuple[Rule, Rule]]:
    """Возвращает пары правил с пересекающимися диапазонами ошибок."""
    ordered = sorted(rules, key=lambda r: r.min_errors)
    overlaps = []
    for a, b in zip(ordered, ordered[1:]):
        a_end = float("inf") if a.max_errors is None else a.max_errors
        if b.min_errors <= a_end:
            overlaps.append((a, b))
    return overlaps


def compute_points(rules: list[Rule], errors: int) -> int:
    """Баллы за тренировку с заданным числом ошибок. 0, если подходящее правило не найдено."""
    for rule in rules:
        upper = float("inf") if rule.max_errors is None else rule.max_errors
        if rule.min_errors <= errors <= upper:
            return rule.points
    return 0


def default_rules() -> list[Rule]:
    return [Rule(a, b, p) for a, b, p in DEFAULT_RULES]
