import pytest

from bot.parsing import ParseError, parse_edit_command, parse_range, parse_word_line, parse_word_lines


@pytest.mark.parametrize("text, expected", [
    ("5", (5, 5)), ("3-4", (3, 4)), ("3–4", (3, 4)), ("11+", (11, None)), (" 0 - 2 ", (0, 2)),
])
def test_parse_range(text, expected):
    assert parse_range(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "5-3", "-2"])
def test_parse_range_errors(text):
    with pytest.raises(ParseError):
        parse_range(text)


def test_parse_word_line_variants():
    assert parse_word_line("apple - яблоко") == ("apple", "яблоко")
    assert parse_word_line("apple: яблоко") == ("apple", "яблоко")
    assert parse_word_line("apple — яблоко") == ("apple", "яблоко")


def test_bad_word_line():
    with pytest.raises(ParseError):
        parse_word_line("just a word")


def test_parse_word_lines_collects_bad_lines():
    pairs, bad = parse_word_lines("cat - кот\n\nnonsense\ndog - собака")
    assert pairs == [("cat", "кот"), ("dog", "собака")]
    assert bad == ["nonsense"]


def test_edit_commands():
    assert parse_edit_command("+ cat - кот") == ("add", None, ("cat", "кот"))
    assert parse_edit_command("e 12 cat - кот") == ("edit", 12, ("cat", "кот"))
    assert parse_edit_command("d 12") == ("delete", 12, None)
    with pytest.raises(ParseError):
        parse_edit_command("e x cat - кот")
    with pytest.raises(ParseError):
        parse_edit_command("hello")
