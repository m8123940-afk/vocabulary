import pytest

from bot.scoring import Rule, compute_points, default_rules, find_overlaps, validate_rule


@pytest.mark.parametrize("errors, expected", [
    (0, 5), (2, 5), (3, 4), (4, 4), (5, 3), (6, 3), (7, 2), (8, 2), (9, 1), (10, 1), (11, 0), (50, 0),
])
def test_default_table_matches_spec(errors, expected):
    assert compute_points(default_rules(), errors) == expected


def test_no_matching_rule_gives_zero():
    assert compute_points([Rule(0, 2, 5)], 7) == 0


def test_open_ended_rule():
    assert compute_points([Rule(11, None, -3)], 100) == -3


def test_negative_points_allowed_within_limits():
    validate_rule(0, 0, -5)
    validate_rule(0, 0, 5)
    with pytest.raises(ValueError):
        validate_rule(0, 0, 6)
    with pytest.raises(ValueError):
        validate_rule(0, 0, -6)


def test_invalid_range_rejected():
    with pytest.raises(ValueError):
        validate_rule(5, 3, 1)
    with pytest.raises(ValueError):
        validate_rule(-1, 3, 1)


def test_overlaps_detected():
    overlaps = find_overlaps([Rule(0, 4, 1), Rule(4, 6, 2)])
    assert len(overlaps) == 1
    assert find_overlaps(default_rules()) == []
