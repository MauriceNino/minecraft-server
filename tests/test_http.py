from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from orchestrator import http
from orchestrator.http import create_http_client, download_file
from orchestrator.plugins.github import raise_for_github_status

URL = "https://api.example/thing"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0.0)


async def test_retries_transient_status(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL, status_code=503)
    httpx_mock.add_response(url=URL, json={"ok": True})

    async with create_http_client() as client:
        resp = await client.get(URL)

    assert resp.json() == {"ok": True}
    assert len(httpx_mock.get_requests()) == 2


async def test_gives_up_after_max_attempts(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL, status_code=502, is_reusable=True)

    async with create_http_client() as client:
        resp = await client.get(URL)

    assert resp.status_code == 502
    assert len(httpx_mock.get_requests()) == http.MAX_ATTEMPTS


async def test_long_retry_after_is_not_waited_for(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL, status_code=429, headers={"Retry-After": "3600"})

    async with create_http_client() as client:
        resp = await client.get(URL)

    assert resp.status_code == 429
    assert len(httpx_mock.get_requests()) == 1


async def test_retries_connection_errors(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("boom"), url=URL)
    httpx_mock.add_response(url=URL, text="ok")

    async with create_http_client() as client:
        resp = await client.get(URL)

    assert resp.text == "ok"


async def test_post_is_not_retried(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL, method="POST", status_code=503)

    async with create_http_client() as client:
        resp = await client.post(URL)

    assert resp.status_code == 503
    assert len(httpx_mock.get_requests()) == 1


class _BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"half"
        raise httpx.ReadError("connection reset")


async def test_download_restarts_after_interruption(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_callback(lambda _: httpx.Response(200, stream=_BrokenStream()), url=URL)
    httpx_mock.add_response(url=URL, content=b"complete")
    target = tmp_path / "server.jar"

    async with create_http_client() as client:
        await download_file(client, URL, target, {"sha256": hashlib.sha256(b"complete").hexdigest()})

    assert target.read_bytes() == b"complete"


async def test_download_gives_up_after_repeated_interruptions(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_callback(lambda _: httpx.Response(200, stream=_BrokenStream()), url=URL, is_reusable=True)
    target = tmp_path / "server.jar"

    async with create_http_client() as client:
        with pytest.raises(httpx.ReadError):
            await download_file(client, URL, target)

    assert not target.exists()
    assert len(httpx_mock.get_requests()) == http.MAX_ATTEMPTS


async def test_github_rate_limit_message(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL, status_code=403, headers={"x-ratelimit-remaining": "0"})

    async with create_http_client() as client:
        resp = await client.get(URL)

    with pytest.raises(RuntimeError, match=r"rate limit exceeded\. Set GITHUB_TOKEN"):
        raise_for_github_status(resp)
