"""Загрузка английских слов и переводов с сайта (BeautifulSoup).

Ожидается HTML-таблица, где в строке первая ячейка — английское слово,
вторая — русский перевод. Заголовки вида «Unit 3» и «Part A» (или «Часть A»)
задают текущие Unit и Part для последующих строк.
"""
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from bot.url_safety import UnsafeUrlError, validate_url

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10.0
UNIT_RE = re.compile(r"\bunit\s*(\d+)\b", re.IGNORECASE)
PART_RE = re.compile(r"\b(?:part|часть)\s*([A-Za-zА-Яа-я0-9]+)\b", re.IGNORECASE)
LATIN_RE = re.compile(r"[A-Za-z]")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


class ScrapeError(Exception):
    """Ошибка загрузки или разбора страницы. Сообщение можно показать пользователю."""


@dataclass(frozen=True)
class WordRow:
    unit: str
    part: str
    en: str
    ru: str


def parse_words(html: str) -> list[WordRow]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    rows: list[WordRow] = []
    unit, part = "", ""
    for element in soup.find_all(True):
        if element.name == "tr":
            cells = element.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            en = cells[0].get_text(" ", strip=True)
            ru = cells[1].get_text(" ", strip=True)
            if en and ru and LATIN_RE.search(en) and CYRILLIC_RE.search(ru) and not LATIN_RE.search(ru):
                rows.append(WordRow(unit, part, en, ru))
        elif element.name in {"h1", "h2", "h3", "h4", "h5", "h6", "caption", "strong", "b"}:
            text = element.get_text(" ", strip=True)
            unit_match = UNIT_RE.search(text)
            part_match = PART_RE.search(text)
            if unit_match:
                unit, part = unit_match.group(1), ""
            if part_match:
                part = part_match.group(1).upper()
    return rows


def list_units(rows: list[WordRow]) -> list[str]:
    return sorted({r.unit for r in rows}, key=lambda u: (len(u), u))


def list_parts(rows: list[WordRow], unit: str) -> list[str]:
    return sorted({r.part for r in rows if r.unit == unit})


def fetch_html(url: str) -> str:
    try:
        safe_url = validate_url(url)
    except UnsafeUrlError as exc:
        raise ScrapeError(str(exc)) from exc
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True, max_redirects=5) as client:
            with client.stream("GET", safe_url, headers={"User-Agent": "EnglishWordsBot/1.0"}) as response:
                response.raise_for_status()
                try:
                    validate_url(str(response.url))  # защита от редиректа на внутренний адрес
                except UnsafeUrlError as exc:
                    raise ScrapeError(str(exc)) from exc
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text" not in content_type:
                    raise ScrapeError("По ссылке не найдена HTML-страница.")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ScrapeError("Страница слишком большая.")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                return b"".join(chunks).decode(encoding, errors="replace")
    except httpx.HTTPStatusError as exc:
        raise ScrapeError(f"Сайт ответил ошибкой {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise ScrapeError("Не удалось загрузить сайт. Проверьте ссылку или попробуйте позже.") from exc


def load_words_from_url(url: str) -> list[WordRow]:
    rows = parse_words(fetch_html(url))
    if not rows:
        raise ScrapeError("На странице не найдено пар «английское слово — перевод».")
    return rows
