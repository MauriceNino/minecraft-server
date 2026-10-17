from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from orchestrator.constants import USER_AGENT

RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.0
# Don't stall startup for longer than this on a single Retry-After
MAX_RETRY_AFTER_SECONDS = 30.0
MAX_CONNECTIONS = 8


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    if value.strip().isdigit():
        return float(value)
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return None


class RetryTransport(httpx.AsyncBaseTransport):
    """Retries idempotent requests on connection errors and transient status codes, with exponential backoff."""

    def __init__(self, wrapped: httpx.AsyncBaseTransport, max_attempts: int = MAX_ATTEMPTS) -> None:
        self._wrapped = wrapped
        self._max_attempts = max_attempts

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in ("GET", "HEAD"):
            return await self._wrapped.handle_async_request(request)

        for attempt in range(1, self._max_attempts + 1):
            delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
            try:
                response = await self._wrapped.handle_async_request(request)
            except httpx.TransportError:
                if attempt == self._max_attempts:
                    raise
            else:
                if response.status_code not in RETRY_STATUS_CODES or attempt == self._max_attempts:
                    return response
                retry_after = _retry_after_seconds(response)
                if retry_after is not None:
                    if retry_after > MAX_RETRY_AFTER_SECONDS:
                        return response
                    delay = retry_after
                await response.aclose()
            await asyncio.sleep(delay)

        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self._wrapped.aclose()


def create_http_client(*, timeout: float = 60.0, connect_timeout: float = 15.0) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(limits=httpx.Limits(max_connections=MAX_CONNECTIONS))
    return httpx.AsyncClient(
        transport=RetryTransport(transport),
        follow_redirects=True,
        # No pool timeout: with the connection limit, requests may wait for a long download to finish
        timeout=httpx.Timeout(timeout, connect=connect_timeout, pool=None),
        headers={"User-Agent": USER_AGENT},
    )


def safe_filename(name: str) -> str:
    """Strip any directory components from a remotely supplied filename."""
    clean = Path(name.replace("\\", "/")).name
    if clean in ("", ".", ".."):
        raise ValueError(f"Refusing to use unsafe filename {name!r}")
    return clean


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    checksums: dict[str, str | None] | None = None,
) -> None:
    """Stream *url* into *target*, verifying any given checksums (keyed by hashlib algorithm name).

    A download that breaks off midway is started over, since the client only retries until the response
    headers arrive. The partially written file is removed if the download or verification fails.
    """
    expected = {algo: value.lower() for algo, value in (checksums or {}).items() if value}

    hashers = {algo: hashlib.new(algo) for algo in expected}

    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if attempt > 1:
                hashers = {algo: hashlib.new(algo) for algo in expected}
            receiving = False
            try:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    receiving = True
                    with target.open("wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65_536):
                            f.write(chunk)
                            for hasher in hashers.values():
                                hasher.update(chunk)
                break
            except httpx.TransportError:
                # Errors before the body are already retried by RetryTransport
                if not receiving or attempt == MAX_ATTEMPTS:
                    raise
            await asyncio.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))

        for algo, hasher in hashers.items():
            if hasher.hexdigest() != expected[algo]:
                raise RuntimeError(f"{algo.upper()} checksum mismatch for {target.name}")
    except BaseException:
        target.unlink(missing_ok=True)  # noqa: ASYNC240
        raise
