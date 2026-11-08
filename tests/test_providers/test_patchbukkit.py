from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from orchestrator import http
from orchestrator.http import create_http_client
from orchestrator.lockfile import ServerLockfile
from orchestrator.providers import pumpkin
from orchestrator.providers.pumpkin import PATCHBUKKIT_LOCK_KEY, PATCHBUKKIT_RELEASE_URL, PumpkinProvider

ASSET = "libpatchbukkit-X64-Linux.so"
DOWNLOAD_URL = "https://gh.example/patchbukkit"


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pumpkin, "_asset_names", lambda: ("pumpkin-X64-Linux", ASSET))
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0.0)


def _mock_release(httpx_mock: HTTPXMock, content: bytes) -> None:
    digest = hashlib.sha256(content).hexdigest()
    httpx_mock.add_response(
        url=PATCHBUKKIT_RELEASE_URL,
        json={
            "tag_name": "nightly",
            "draft": False,
            "prerelease": True,
            "assets": [{"name": ASSET, "digest": f"sha256:{digest}", "browser_download_url": DOWNLOAD_URL}],
        },
    )


async def _install(runtime: Path, lockfile: ServerLockfile) -> None:
    async with create_http_client() as client:
        await PumpkinProvider().install_extras(runtime, client, lockfile)


async def test_downloads_and_locks(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    _mock_release(httpx_mock, b"v1")
    httpx_mock.add_response(url=DOWNLOAD_URL, content=b"v1")
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})

    await _install(tmp_path, lockfile)

    assert (tmp_path / "plugins" / ASSET).read_bytes() == b"v1"
    entry = lockfile.extras[PATCHBUKKIT_LOCK_KEY]
    assert entry.path == f"plugins/{ASSET}"
    assert entry.sha256 == hashlib.sha256(b"v1").hexdigest()


async def test_unchanged_build_is_not_downloaded_again(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    _mock_release(httpx_mock, b"v1")
    httpx_mock.add_response(url=DOWNLOAD_URL, content=b"v1")
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    await _install(tmp_path, lockfile)

    _mock_release(httpx_mock, b"v1")
    await _install(tmp_path, lockfile)

    assert len(httpx_mock.get_requests(url=DOWNLOAD_URL)) == 1


@pytest.mark.parametrize("change", ["new build", "modified file", "deleted file"])
async def test_downloads_again(httpx_mock: HTTPXMock, tmp_path: Path, change: str) -> None:
    _mock_release(httpx_mock, b"v1")
    httpx_mock.add_response(url=DOWNLOAD_URL, content=b"v1")
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    await _install(tmp_path, lockfile)

    expected = b"v1"
    if change == "new build":
        expected = b"v2"
    elif change == "modified file":
        (tmp_path / "plugins" / ASSET).write_bytes(b"tampered")
    else:
        (tmp_path / "plugins" / ASSET).unlink()
    _mock_release(httpx_mock, expected)
    httpx_mock.add_response(url=DOWNLOAD_URL, content=expected)
    await _install(tmp_path, lockfile)

    assert (tmp_path / "plugins" / ASSET).read_bytes() == expected


async def test_api_failure_keeps_installed_file(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    _mock_release(httpx_mock, b"v1")
    httpx_mock.add_response(url=DOWNLOAD_URL, content=b"v1")
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    await _install(tmp_path, lockfile)

    httpx_mock.add_response(url=PATCHBUKKIT_RELEASE_URL, status_code=503, is_reusable=True)
    await _install(tmp_path, lockfile)

    assert (tmp_path / "plugins" / ASSET).read_bytes() == b"v1"


async def test_api_failure_without_installed_file_raises(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=PATCHBUKKIT_RELEASE_URL, status_code=503, is_reusable=True)
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})

    with pytest.raises(Exception, match="503"):
        await _install(tmp_path, lockfile)


def test_extras_survive_a_save(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / ASSET).write_bytes(b"v1")
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    lockfile.update_extra(PATCHBUKKIT_LOCK_KEY, tmp_path, tmp_path / "plugins" / ASSET, "abc")
    lockfile.save()

    assert ServerLockfile.load(tmp_path / "lock.json").extras == lockfile.extras
