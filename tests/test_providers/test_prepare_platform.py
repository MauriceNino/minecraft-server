from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from orchestrator import http
from orchestrator.constants import PlatformType, PluginProviderType, PluginUpdateStrategy
from orchestrator.lockfile import PluginLockEntry, ServerLockfile
from orchestrator.plugins import download_plugins
from orchestrator.plugins.base import PluginSpec
from orchestrator.providers import prepare_platform

PAPER_API = re.compile(r"https://fill\.papermc\.io/.*")
JAR = b"paper-jar"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0.0)


def _installed_lockfile(runtime_dir: Path, *, version: str = "1.21.4", content: bytes = JAR) -> ServerLockfile:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    jar = runtime_dir / f"paper-{version}-100.jar"
    jar.write_bytes(JAR)
    lockfile = ServerLockfile.load(runtime_dir / "server-lock.json")
    lockfile.update_server(project="paper", version=version, build="100", file_path=jar)
    jar.write_bytes(content)
    return lockfile


def _paper_unreachable(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("no network"), url=PAPER_API, is_reusable=True)


async def test_falls_back_to_installed_jar(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    _paper_unreachable(httpx_mock)
    lockfile = _installed_lockfile(tmp_path)

    executable, mc_version, offline = await prepare_platform(tmp_path, PlatformType.PAPER, "latest", "latest", lockfile)

    assert executable == tmp_path / "paper-1.21.4-100.jar"
    assert mc_version == "1.21.4"
    assert offline is True


@pytest.mark.parametrize(
    ("platform", "version", "content"),
    [
        (PlatformType.PAPER, "1.20.4", JAR),  # pinned to a different version
        (PlatformType.FOLIA, "latest", JAR),  # different project
        (PlatformType.PAPER, "latest", b"corrupt"),  # checksum mismatch
    ],
)
async def test_no_fallback_when_installed_jar_does_not_fit(
    tmp_path: Path, httpx_mock: HTTPXMock, platform: PlatformType, version: str, content: bytes
) -> None:
    _paper_unreachable(httpx_mock)
    lockfile = _installed_lockfile(tmp_path, content=content)

    with pytest.raises(httpx.ConnectError):
        await prepare_platform(tmp_path, platform, version, "latest", lockfile)


async def test_resolves_and_downloads_when_online(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://fill.papermc.io/v3/projects/paper/versions/1.21.4/builds",
        json=[
            {"id": 101, "channel": "BETA", "downloads": {}},
            {
                "id": 100,
                "channel": "STABLE",
                "downloads": {
                    "server:default": {
                        "name": "paper-1.21.4-100.jar",
                        "url": "https://cdn.example/paper.jar",
                        "checksums": {"sha256": hashlib.sha256(JAR).hexdigest()},
                    }
                },
            },
        ],
    )
    httpx_mock.add_response(url="https://cdn.example/paper.jar", content=JAR)
    lockfile = ServerLockfile.load(tmp_path / "server-lock.json")

    executable, mc_version, offline = await prepare_platform(tmp_path, PlatformType.PAPER, "1.21.4", "latest", lockfile)

    assert executable.read_bytes() == JAR
    assert (mc_version, offline) == ("1.21.4", False)
    assert lockfile.server is not None
    assert lockfile.server.build == "100"


async def test_offline_plugins_keep_installed_and_report_missing(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "a.jar").write_bytes(b"a")
    lockfile = ServerLockfile.load(tmp_path / "server-lock.json")
    lockfile.plugins["url:https://x/a.jar"] = PluginLockEntry(
        display_name="a", version="1", sha256=None, filename="a.jar", updated_at="", target_version="latest"
    )

    failures = await download_plugins(
        plugin_specs=[
            PluginSpec(PluginProviderType.URL, "https://x/a.jar", "latest", force=False),
            PluginSpec(PluginProviderType.URL, "https://x/b.jar", "latest", force=False),
        ],
        platform_type=PlatformType.PAPER,
        mc_version="1.21.4",
        plugins_dir=plugins_dir,
        lockfile=lockfile,
        strategy=PluginUpdateStrategy.AUTO,
        check_cache_seconds=0,
        offline=True,
    )

    assert failures == ["url:https://x/b.jar: not installed and the APIs are unreachable"]
    assert (plugins_dir / "a.jar").exists()
    assert lockfile.plugins_checked_at is None
