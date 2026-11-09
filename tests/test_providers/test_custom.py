from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from orchestrator import http
from orchestrator.constants import UNKNOWN_MC_VERSION, PlatformType
from orchestrator.http import create_http_client
from orchestrator.lockfile import ServerLockfile
from orchestrator.providers import prepare_platform
from orchestrator.providers.custom import CustomProvider

URL = "https://cdn.example/builds/myfork-1.21.4.jar"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0.0)


async def test_url_and_last_modified_are_the_build(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="HEAD", url=URL, headers={"Last-Modified": "Wed, 01 Jan 2026 10:00:00 GMT"})

    async with create_http_client() as client:
        resolved = await CustomProvider().resolve_version("1.21.4", URL, client)

    assert resolved.build == f"{URL}#2026-01-01_10-00-00"
    assert (resolved.version, resolved.download_url, resolved.filename) == ("1.21.4", URL, "myfork-1.21.4.jar")


async def test_url_without_headers_is_the_build(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="HEAD", url=URL)

    async with create_http_client() as client:
        resolved = await CustomProvider().resolve_version("1.21.4", URL, client)

    assert resolved.build == URL


async def test_url_without_jar_name_and_unknown_version(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="HEAD", url="https://cdn.example/download?id=4")
    async with create_http_client() as client:
        resolved = await CustomProvider().resolve_version("latest", "https://cdn.example/download?id=4", client)

    assert resolved.version == UNKNOWN_MC_VERSION
    assert resolved.filename == "custom-server.jar"


async def test_missing_file() -> None:
    async with create_http_client() as client:
        with pytest.raises(RuntimeError, match="is not a file"):
            await CustomProvider().resolve_version("latest", "/nonexistent/server.jar", client)


async def test_url_is_only_downloaded_again_when_it_changes(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="HEAD", url=URL, headers={"ETag": '"a"'}, is_reusable=True)
    httpx_mock.add_response(method="GET", url=URL, content=b"jar-a")
    lockfile = ServerLockfile.load(tmp_path / "server-lock.json")

    for _ in range(2):
        executable, mc_version, offline = await prepare_platform(tmp_path, PlatformType.CUSTOM, "1.21.4", URL, lockfile)
    assert executable.read_bytes() == b"jar-a"
    assert (mc_version, offline) == ("1.21.4", False)
    assert len(httpx_mock.get_requests(method="GET")) == 1

    httpx_mock.reset()
    httpx_mock.add_response(method="HEAD", url=URL, headers={"ETag": '"b"'})
    httpx_mock.add_response(method="GET", url=URL, content=b"jar-b")
    executable, _, _ = await prepare_platform(tmp_path, PlatformType.CUSTOM, "1.21.4", URL, lockfile)
    assert executable.read_bytes() == b"jar-b"


async def test_unreachable_url_starts_the_installed_jar(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="HEAD", url=URL, headers={"ETag": '"a"'})
    httpx_mock.add_response(method="GET", url=URL, content=b"jar-a")
    lockfile = ServerLockfile.load(tmp_path / "server-lock.json")
    await prepare_platform(tmp_path, PlatformType.CUSTOM, "1.21.4", URL, lockfile)

    httpx_mock.add_exception(httpx.ConnectError("no network"), url=URL, is_reusable=True)
    executable, _, offline = await prepare_platform(tmp_path, PlatformType.CUSTOM, "1.21.4", URL, lockfile)

    assert offline is True
    assert executable.read_bytes() == b"jar-a"


async def test_file_is_copied_again_when_it_changes(tmp_path: Path) -> None:
    source = tmp_path / "jars" / "server.jar"
    source.parent.mkdir()
    source.write_bytes(b"v1")
    runtime = tmp_path / "runtime"
    lockfile = ServerLockfile.load(runtime / "server-lock.json")

    executable, _, _ = await prepare_platform(runtime, PlatformType.CUSTOM, "latest", str(source), lockfile)
    assert executable == runtime / "server.jar"
    assert executable.read_bytes() == b"v1"

    source.write_bytes(b"v2")
    executable, _, _ = await prepare_platform(runtime, PlatformType.CUSTOM, "latest", str(source), lockfile)
    assert executable.read_bytes() == b"v2"
