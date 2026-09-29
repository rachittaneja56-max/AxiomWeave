import asyncio

import httpx
import pytest

from app.url_import import (
    URLImportError,
    extract_page_text,
    import_public_url,
    resolve_public_addresses,
    validate_import_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a",
        "https://user:pass@example.com/",
        "http://localhost/",
        "http://service.localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://[fd00::1]/",
        "http://[fe80::1]/",
        "http://[ff02::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
        "http://example.com:8080/",
    ],
)
def test_rejects_unsafe_or_non_http_urls(url: str) -> None:
    with pytest.raises(URLImportError):
        validate_import_url(url)


def test_accepts_public_https_url_and_normalizes_host() -> None:
    assert validate_import_url("HTTPS://Example.com/story#section") == (
        "https://Example.com/story",
        "example.com",
        443,
        "https",
    )


def test_rejects_hostname_if_any_dns_answer_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(_hostname: str, _port: int) -> list[str]:
        return ["93.184.216.34", "10.0.0.1"]

    monkeypatch.setattr("app.url_import._resolve_hostname", fake_resolve)
    with pytest.raises(URLImportError, match="public web page"):
        asyncio.run(resolve_public_addresses("example.com", 443))


def test_html_extraction_removes_non_content_and_enforces_source_bound() -> None:
    title, text = extract_page_text(
        b"<html><head><title>News</title><style>hidden</style></head><body>"
        b"<main><h1>Headline</h1><p>Article body.</p><script>steal()</script></main>"
        b"</body></html>",
        "text/html",
        "https://example.com/news",
    )
    assert title == "News"
    assert text == "Headline\nArticle body."


def test_safe_public_url_redirecting_to_private_address_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedirectResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1/admin"}

    class ResponseContext:
        async def __aenter__(self) -> RedirectResponse:
            return RedirectResponse()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def stream(self, _method: str, _url: str) -> ResponseContext:
            return ResponseContext()

    monkeypatch.setattr("app.url_import.resolve_public_addresses", _public_ip)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(URLImportError, match="public web page"):
        asyncio.run(import_public_url("https://example.com/article"))


async def _public_ip(_hostname: str, _port: int) -> list[str]:
    return ["93.184.216.34"]
