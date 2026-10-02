import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from typing import cast
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpcore
import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from app.domain.transformation import SOURCE_TEXT_MAX_LENGTH
from app.source_versions import normalize_source_text

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
_ALLOWED_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
    )


class URLImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


class URLImportResult(BaseModel):
    source_url: str
    final_url: str
    title: str
    character_count: int
    source_text: str
    extraction_method: str = "url_html"
    media_type: str = "text/html"
    source_id: int | None = None
    source_version_id: int | None = None


class URLImportError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_import_url(value: str) -> tuple[str, str, int, str]:
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise URLImportError("invalid_url", "Enter a valid public HTTP or HTTPS URL.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        _ = parsed.hostname
    except ValueError:
        raise URLImportError("invalid_url", "Enter a valid public HTTP or HTTPS URL.") from None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise URLImportError("invalid_url", "Only public HTTP and HTTPS pages can be imported.")
    if parsed.username is not None or parsed.password is not None:
        raise URLImportError("invalid_url", "URLs with embedded credentials are not allowed.")
    scheme = parsed.scheme.lower()
    port = port or (443 if scheme == "https" else 80)
    if (
        port not in {80, 443}
        or (scheme == "https" and port != 443)
        or (scheme == "http" and port != 80)
    ):
        raise URLImportError("invalid_url", "Only the standard HTTP and HTTPS ports are allowed.")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname in {"metadata.google.internal", "metadata", "instance-data.ec2.internal"}
    ):
        raise URLImportError("unsafe_url", "This address is not a public web page.")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not _is_public_ip(literal):
        raise URLImportError("unsafe_url", "This address is not a public web page.")
    clean = urlunsplit((scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    return clean, hostname, port, scheme


async def _resolve_hostname(hostname: str, port: int) -> list[str]:
    records = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(hostname, port, type=socket.SOCK_STREAM),
        timeout=5,
    )
    return list(dict.fromkeys(cast(str, record[4][0]) for record in records))


async def resolve_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [str(literal)]
    except ValueError:
        try:
            addresses = await _resolve_hostname(hostname, port)
        except (OSError, TimeoutError):
            raise URLImportError("url_unavailable", "The page could not be reached.") from None
    if not addresses or any(
        not _is_public_ip(ipaddress.ip_address(address)) for address in addresses
    ):
        raise URLImportError("unsafe_url", "This address is not a public web page.")
    return addresses


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Connect only to an address checked for the current request hop."""

    def __init__(self, address: str):
        self.address = address
        self.backend = cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[
            tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
        ]
        | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self.backend.connect_tcp(
            self.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[
            tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
        ]
        | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise OSError("Unix sockets are not supported")

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, address: str):
        super().__init__(trust_env=False, retries=0, http2=False)
        self._pool = httpcore.AsyncConnectionPool(
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
            network_backend=_PinnedBackend(address),
        )


def extract_page_text(content: bytes, media_type: str, source_url: str) -> tuple[str, str]:
    decoded = content.decode("utf-8", errors="replace")
    if media_type == "text/plain":
        title = urlsplit(source_url).hostname or "Imported page"
        text = decoded
    else:
        soup = BeautifulSoup(decoded, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        for node in soup(
            [
                "script",
                "style",
                "noscript",
                "template",
                "svg",
                "canvas",
                "iframe",
                "form",
                "nav",
                "footer",
            ]
        ):
            node.decompose()
        main = soup.find("article") or soup.find("main") or soup.body or soup
        blocks = main.find_all(["h1", "h2", "h3", "p", "li", "blockquote"])
        extracted_blocks: list[str] = []
        for block in blocks:
            if any(parent in blocks for parent in block.parents if parent is not main):
                continue
            block_text = block.get_text(" ", strip=True)
            if block_text:
                extracted_blocks.append(block_text)
        text = "\n".join(extracted_blocks) or main.get_text("\n", strip=True)
        heading = soup.find("h1")
        title = title or (heading.get_text(" ", strip=True) if heading else "Imported page")
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    try:
        text = normalize_source_text(text)
    except ValueError as error:
        raise URLImportError("empty_source", str(error)) from None
    if len(text) > SOURCE_TEXT_MAX_LENGTH:
        raise URLImportError("source_too_large", "The extracted page exceeds 20,000 characters.")
    return title[:300], text


async def import_public_url(url: str) -> URLImportResult:
    original, current = url, url
    seen: set[str] = set()
    for hop in range(MAX_REDIRECTS + 1):
        current, hostname, port, _scheme = validate_import_url(current)
        if current in seen:
            raise URLImportError("redirect_loop", "The page returned a redirect loop.")
        seen.add(current)
        addresses = await resolve_public_addresses(hostname, port)
        transport = _PinnedTransport(addresses[0])
        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": "AxiomWeave-Source-Importer/1.0",
                "Accept": "text/html,application/xhtml+xml,text/plain",
            },
        ) as client:
            try:
                next_url = await asyncio.wait_for(
                    _read_page(client, original, current, hop), timeout=10
                )
                if isinstance(next_url, URLImportResult):
                    return next_url
                current = next_url
            except URLImportError:
                raise
            except (httpx.HTTPError, ValueError, TimeoutError):
                raise URLImportError("url_unavailable", "The page could not be imported.") from None
    raise URLImportError("url_unavailable", "The page could not be imported.")


async def _read_page(
    client: httpx.AsyncClient, original: str, current: str, hop: int
) -> URLImportResult | str:
    async with client.stream("GET", current) as response:
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise URLImportError("url_unavailable", "The page could not be imported.")
            if hop == MAX_REDIRECTS:
                raise URLImportError("too_many_redirects", "The page redirected too many times.")
            return urljoin(current, location)
        if response.status_code < 200 or response.status_code >= 300:
            raise URLImportError("url_unavailable", "The page could not be imported.")
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in _ALLOWED_TYPES:
            raise URLImportError(
                "unsupported_content", "This page is not a supported text or HTML page."
            )
        length = response.headers.get("content-length")
        if length and int(length) > MAX_RESPONSE_BYTES:
            raise URLImportError("response_too_large", "The page is larger than 2 MiB.")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise URLImportError("response_too_large", "The page is larger than 2 MiB.")
            chunks.append(chunk)
        title, text = extract_page_text(b"".join(chunks), media_type, current)
        return URLImportResult(
            source_url=original,
            final_url=current,
            title=title,
            character_count=len(text),
            source_text=text,
            media_type=media_type,
        )
