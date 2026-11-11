from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from orchestrator import http
from orchestrator.http import create_http_client
from orchestrator.lockfile import ServerLockfile
from orchestrator.providers import pumpkin
from orchestrator.providers.base import ResolvedVersion
from orchestrator.providers.pumpkin import (
    PATCHBUKKIT_LOCK_KEY,
    PATCHBUKKIT_NIGHTLY_URL,
    PATCHBUKKIT_STABLE_URL,
    PUMPKIN_PLUGIN_API_SOURCE,
    PumpkinProvider,
)
from orchestrator.providers.pumpkin import _pumpkin_plugin_api as _real_plugin_api
from tests.elf_fixture import make_elf

ASSET = "libpatchbukkit-X64-Linux.so"
DOWNLOAD_URL = "https://gh.example/patchbukkit"
PATCHBUKKIT_RELEASE_URL = PATCHBUKKIT_NIGHTLY_URL
NIGHTLY = ResolvedVersion(
    project="pumpkin",
    version="1.21.4",
    build="c" * 12,
    download_url="https://github.com/Pumpkin-MC/Pumpkin/releases/download/nightly/pumpkin-X64-Linux",
    filename="pumpkin-X64-Linux",
)
STABLE = ResolvedVersion(
    project="pumpkin",
    version="26.3",
    build="0.2.2",
    download_url="https://github.com/Pumpkin-MC/Pumpkin/releases/download/0.2.2%2B26.3-26.60/pumpkin-X64-Linux",
    filename="pumpkin-X64-Linux",
)


class PumpkinApi:
    """The plugin API version the Pumpkin build has, None when it can't be determined."""

    version: int | None = None


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pumpkin, "_asset_names", lambda: ("pumpkin-X64-Linux", ASSET))
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0.0)
    PumpkinApi.version = None

    async def plugin_api(_client: object, _resolved: object) -> int | None:
        return PumpkinApi.version

    monkeypatch.setattr(pumpkin, "_pumpkin_plugin_api", plugin_api)


def _mock_release(httpx_mock: HTTPXMock, content: bytes, url: str = PATCHBUKKIT_RELEASE_URL) -> None:
    digest = hashlib.sha256(content).hexdigest()
    httpx_mock.add_response(
        url=url,
        json={
            "tag_name": "nightly" if url == PATCHBUKKIT_NIGHTLY_URL else "0.2.1",
            "draft": False,
            "prerelease": url == PATCHBUKKIT_NIGHTLY_URL,
            "assets": [{"name": ASSET, "digest": f"sha256:{digest}", "browser_download_url": DOWNLOAD_URL}],
        },
    )


async def _install(runtime: Path, lockfile: ServerLockfile, resolved: ResolvedVersion = NIGHTLY) -> None:
    async with create_http_client() as client:
        await PumpkinProvider().install_extras(resolved, runtime, client, lockfile)


async def test_follows_the_pumpkin_channel(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    _mock_release(httpx_mock, b"nightly", PATCHBUKKIT_NIGHTLY_URL)
    httpx_mock.add_response(url=DOWNLOAD_URL, content=b"nightly")
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    await _install(tmp_path, lockfile, NIGHTLY)

    _mock_release(httpx_mock, b"stable", PATCHBUKKIT_STABLE_URL)
    httpx_mock.add_response(url=DOWNLOAD_URL, content=b"stable")
    await _install(tmp_path, lockfile, STABLE)

    assert (tmp_path / "plugins" / ASSET).read_bytes() == b"stable"


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


async def test_build_for_another_plugin_api_is_disabled(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    library = make_elf(pumpkin.PATCHBUKKIT_API_SYMBOL, 3)
    PumpkinApi.version = 5
    _mock_release(httpx_mock, library)
    httpx_mock.add_response(url=DOWNLOAD_URL, content=library)
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})

    await _install(tmp_path, lockfile)

    disabled = tmp_path / "plugins" / f"{ASSET}.disabled"
    assert not (tmp_path / "plugins" / ASSET).exists()
    assert disabled.read_bytes() == library
    assert lockfile.extras[PATCHBUKKIT_LOCK_KEY].path == f"plugins/{ASSET}.disabled"


async def test_disabled_build_is_enabled_without_a_download(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    library = make_elf(pumpkin.PATCHBUKKIT_API_SYMBOL, 5)
    PumpkinApi.version = 4
    _mock_release(httpx_mock, library)
    httpx_mock.add_response(url=DOWNLOAD_URL, content=library)
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    await _install(tmp_path, lockfile)

    # Pumpkin catches up with the same PatchBukkit build
    PumpkinApi.version = 5
    _mock_release(httpx_mock, library)
    await _install(tmp_path, lockfile)

    assert (tmp_path / "plugins" / ASSET).read_bytes() == library
    assert not (tmp_path / "plugins" / f"{ASSET}.disabled").exists()
    assert lockfile.extras[PATCHBUKKIT_LOCK_KEY].path == f"plugins/{ASSET}"
    assert len(httpx_mock.get_requests(url=DOWNLOAD_URL)) == 1


async def test_enabled_build_is_disabled_when_pumpkin_moves_on(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    library = make_elf(pumpkin.PATCHBUKKIT_API_SYMBOL, 3)
    PumpkinApi.version = 3
    _mock_release(httpx_mock, library)
    httpx_mock.add_response(url=DOWNLOAD_URL, content=library)
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    await _install(tmp_path, lockfile)
    assert (tmp_path / "plugins" / ASSET).exists()

    PumpkinApi.version = 5
    _mock_release(httpx_mock, library)
    await _install(tmp_path, lockfile)

    assert not (tmp_path / "plugins" / ASSET).exists()
    assert (tmp_path / "plugins" / f"{ASSET}.disabled").read_bytes() == library
    assert len(httpx_mock.get_requests(url=DOWNLOAD_URL)) == 1


async def test_pumpkin_plugin_api_is_read_from_the_release_source(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=PUMPKIN_PLUGIN_API_SOURCE.format(ref="0.2.2%2B26.3-26.60"),
        text="/// The version\npub const PLUGIN_API_VERSION: u32 = 5;\n",
    )
    httpx_mock.add_response(url=PUMPKIN_PLUGIN_API_SOURCE.format(ref="nightly"), status_code=404)

    async with create_http_client() as client:
        assert await _real_plugin_api(client, STABLE) == 5
        assert await _real_plugin_api(client, NIGHTLY) is None
        # Not a GitHub release download
        assert await _real_plugin_api(client, replace(STABLE, download_url="https://gh.example/pumpkin")) is None
