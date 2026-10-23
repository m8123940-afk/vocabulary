import pytest

from bot.url_safety import UnsafeUrlError, validate_url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/words",
    "javascript:alert(1)",
    "http://localhost:8000/words",
    "http://127.0.0.1/admin",
    "http://192.168.1.10/table",
    "http://10.0.0.5/",
    "http://169.254.169.254/latest/meta-data",
    "http://user:pass@example.com/",
    "https://",
    "",
])
def test_unsafe_urls_rejected(url):
    with pytest.raises(UnsafeUrlError):
        validate_url(url, resolve_dns=False)


def test_public_url_accepted_without_dns():
    assert validate_url("https://example.com/words", resolve_dns=False) == "https://example.com/words"


def test_too_long_url_rejected():
    with pytest.raises(UnsafeUrlError):
        validate_url("https://example.com/" + "a" * 3000, resolve_dns=False)
