"""Защита от небезопасных URL: только http(s), без localhost и частных адресов."""
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
MAX_URL_LENGTH = 2048


class UnsafeUrlError(ValueError):
    pass


def _is_ip_literal(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _is_private_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def validate_url(url: str, resolve_dns: bool = True) -> str:
    """Проверяет URL и возвращает его очищенным, либо выбрасывает UnsafeUrlError."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise UnsafeUrlError("Некорректная длина ссылки.")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("Разрешены только ссылки http:// и https://.")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeUrlError("В ссылке не указан адрес сайта.")
    if host in {"localhost"} or host.endswith(".localhost") or host.endswith(".local"):
        raise UnsafeUrlError("Локальные адреса недопустимы.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Ссылки с логином и паролем недопустимы.")

    if _is_ip_literal(host) and _is_private_ip(host):
        raise UnsafeUrlError("Частные и служебные IP-адреса недопустимы.")

    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UnsafeUrlError("Не удалось найти сервер по этой ссылке.") from exc
        for info in infos:
            if _is_private_ip(info[4][0]):
                raise UnsafeUrlError("Ссылка ведёт на внутренний адрес сети.")
    return url
