"""Встроенный словарь: Navigate B1+ Wordlist, Unit 1–12, все Part (800 слов, перевод вручную)."""
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "navigate_b1plus.txt"


def load_navigate_rows(path: Path = DATA_FILE) -> list[tuple[str, str, str, str]]:
    """Возвращает строки (unit, part, en, ru). Формат файла: юнит|часть|english|русский."""
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) != 4 or not all(f.strip() for f in fields):
            raise ValueError(f"Некорректная строка {number} в словаре: {line!r}")
        unit, part, en, ru = (f.strip() for f in fields)
        rows.append((unit, part, en, ru))
    return rows
