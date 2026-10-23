"""Разбор пользовательского ввода: диапазоны ошибок, строки слов, команды редактирования."""
import re

RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:[-–—]\s*(\d+)|\+)?\s*$")
WORD_SEP_RE = re.compile(r"\s+[-–—:]\s+|\s*[-–—]\s*|\s*:\s*")


class ParseError(ValueError):
    pass


def parse_range(text: str) -> tuple[int, int | None]:
    """'5' -> (5, 5); '3-4' -> (3, 4); '11+' -> (11, None)."""
    match = RANGE_RE.match(text or "")
    if not match:
        raise ParseError("Введите диапазон ошибок: например 5, 3-4 или 11+.")
    low = int(match.group(1))
    if match.group(2) is not None:
        high = int(match.group(2))
        if high < low:
            raise ParseError("Конец диапазона не может быть меньше начала.")
        return low, high
    if text.strip().endswith("+"):
        return low, None
    return low, low


def parse_word_line(line: str) -> tuple[str, str]:
    """'apple - яблоко' -> ('apple', 'яблоко'). Разделители: тире или двоеточие."""
    parts = WORD_SEP_RE.split(line.strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ParseError(f"Не удалось разобрать строку: «{line.strip()}». Формат: apple - яблоко")
    return parts[0].strip(), parts[1].strip()


def parse_word_lines(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Возвращает (успешные пары, строки с ошибками)."""
    pairs, bad = [], []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        try:
            pairs.append(parse_word_line(line))
        except ParseError:
            bad.append(line.strip())
    return pairs, bad


def parse_edit_command(text: str) -> tuple[str, int | None, tuple[str, str] | None]:
    """Команды в разделе слов:
    '+ apple - яблоко'        -> ('add', None, (en, ru))
    'e 12 apple - яблоко'     -> ('edit', 12, (en, ru))
    'd 12'                    -> ('delete', 12, None)
    """
    text = (text or "").strip()
    if text.startswith("+"):
        return ("add", None, parse_word_line(text[1:]))
    if text.lower().startswith("e "):
        rest = text[2:].strip()
        head, _, tail = rest.partition(" ")
        if not head.isdigit() or not tail:
            raise ParseError("Формат: e 12 apple - яблоко")
        return ("edit", int(head), parse_word_line(tail))
    if text.lower().startswith("d "):
        head = text[2:].strip()
        if not head.isdigit():
            raise ParseError("Формат: d 12")
        return ("delete", int(head), None)
    raise ParseError("Команды: «+ слово - перевод», «e 12 слово - перевод», «d 12».")


UNIT_CMD_RE = re.compile(r"^\s*(?:unit|юнит)\s*(\d+)(?:\s*(?:part|часть)\s*(\d+))?\s*$", re.IGNORECASE)


def parse_unit_command(text: str) -> tuple[str, str | None] | None:
    """'Unit 4 Part 2' -> ('4', '2'); 'unit 4' -> ('4', None); иначе None."""
    match = UNIT_CMD_RE.match(text or "")
    if not match:
        return None
    return match.group(1), match.group(2)
