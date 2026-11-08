from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from orchestrator.constants import PlatformType, PluginProviderType, PluginUpdateStrategy
from orchestrator.http import download_file, safe_filename
from orchestrator.lockfile import ServerLockfile
from orchestrator.plugins import download_plugins
from orchestrator.plugins.base import PluginSpec
from orchestrator.plugins.modrinth import ModrinthProvider

API = "https://api.modrinth.com/v2/project/demo"
JAR = b"jar-bytes"


def _version(number: str, game_versions: list[str], version_id: str = "", channel: str = "release") -> dict:
    return {
        "id": version_id or f"id-{number}",
        "version_number": number,
        "version_type": channel,
        "loaders": ["paper"],
        "game_versions": game_versions,
        "files": [
            {"url": "https://cdn.example/other.jar", "filename": "other.jar", "primary": False, "hashes": {}},
            {
                "url": f"https://cdn.example/demo-{number}.jar",
                "filename": f"demo-{number}.jar",
                "primary": True,
                "hashes": {"sha512": hashlib.sha512(JAR).hexdigest()},
            },
        ],
    }


def _mock_modrinth(httpx_mock: HTTPXMock, versions: list[dict], *, is_reusable: bool = True) -> None:
    """Mock the project and its versions, applying the `loaders` and `game_versions` filters like the API."""

    def versions_response(request: httpx.Request) -> httpx.Response:
        loaders = json.loads(request.url.params.get("loaders", "null"))
        game_versions = json.loads(request.url.params.get("game_versions", "null"))
        return httpx.Response(
            200,
            json=[
                v
                for v in versions
                if (loaders is None or set(loaders) & set(v["loaders"]))
                and (game_versions is None or set(game_versions) & set(v["game_versions"]))
            ],
        )

    httpx_mock.add_response(url=API, json={"title": "Demo", "loaders": ["paper"]}, is_reusable=is_reusable)
    httpx_mock.add_callback(versions_response, url=re.compile(rf"{API}/version\?.*"), is_reusable=is_reusable)


def _spec(version: str = "latest") -> PluginSpec:
    return PluginSpec(PluginProviderType.MODRINTH, "demo", version, force=False)


class TestModrinthResolve:
    async def test_latest_picks_newest_compatible_version(self, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"]), _version("1.9", ["1.20.4"])])

        async with httpx.AsyncClient() as client:
            resolved = await ModrinthProvider().resolve(_spec(), PlatformType.PAPER, "1.20.4", client)

        assert resolved.version == "1.9"
        assert resolved.filename == "demo-1.9.jar"  # primary file, not the first one

    async def test_specific_version_by_id(self, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"], version_id="P3y2MXnd")])

        async with httpx.AsyncClient() as client:
            resolved = await ModrinthProvider().resolve(_spec("P3y2MXnd"), PlatformType.PAPER, "1.21.4", client)

        assert resolved.version == "2.0"

    async def test_no_compatible_version(self, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"])])

        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="does not support platform version"):
                await ModrinthProvider().resolve(_spec(), PlatformType.PAPER, "1.8.8", client)

    async def test_no_version_for_platform(self, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"]) | {"loaders": ["fabric"]}])

        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="compatible with platform"):
                await ModrinthProvider().resolve(_spec(), PlatformType.PAPER, "1.21.4", client)

    async def test_filters_on_the_server(self, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"])])

        async with httpx.AsyncClient() as client:
            await ModrinthProvider().resolve(_spec(), PlatformType.PAPER, "1.21.4", client)

        params = httpx_mock.get_requests(url=re.compile(rf"{API}/version\?.*"))[0].url.params
        assert "paper" in json.loads(params["loaders"])
        assert json.loads(params["game_versions"]) == ["1.21.4"]
        assert params["include_changelog"] == "false"


class TestDownloadPlugins:
    async def _run(self, plugins_dir: Path, lockfile: ServerLockfile) -> list[str]:
        return await download_plugins(
            plugin_specs=[_spec()],
            platform_type=PlatformType.PAPER,
            mc_version="1.21.4",
            plugins_dir=plugins_dir,
            lockfile=lockfile,
            strategy=PluginUpdateStrategy.MANUAL,
            check_cache_seconds=300,
        )

    async def test_missing_jar_is_reinstalled(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"])])
        httpx_mock.add_response(url="https://cdn.example/demo-2.0.jar", content=JAR, is_reusable=True)
        plugins_dir = tmp_path / "plugins"
        lockfile = ServerLockfile.load(tmp_path / "server-lock.json")

        assert await self._run(plugins_dir, lockfile) == []
        jar = plugins_dir / "demo-2.0.jar"
        assert jar.read_bytes() == JAR

        # Deleted by hand while the check cache is still fresh and the strategy is manual
        jar.unlink()
        assert await self._run(plugins_dir, ServerLockfile.load(tmp_path / "server-lock.json")) == []
        assert jar.read_bytes() == JAR

    async def test_modified_jar_is_replaced(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"])])
        httpx_mock.add_response(url="https://cdn.example/demo-2.0.jar", content=JAR, is_reusable=True)
        plugins_dir = tmp_path / "plugins"

        await self._run(plugins_dir, ServerLockfile.load(tmp_path / "server-lock.json"))
        jar = plugins_dir / "demo-2.0.jar"
        jar.write_bytes(b"half-copied")

        assert await self._run(plugins_dir, ServerLockfile.load(tmp_path / "server-lock.json")) == []
        assert jar.read_bytes() == JAR

    async def test_modified_jar_is_removed_when_filename_changes(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        for number in ("2.0", "2.1"):
            _mock_modrinth(httpx_mock, [_version(number, ["1.21.4"])], is_reusable=False)
            httpx_mock.add_response(url=f"https://cdn.example/demo-{number}.jar", content=JAR)
        plugins_dir = tmp_path / "plugins"

        await self._run(plugins_dir, ServerLockfile.load(tmp_path / "server-lock.json"))
        (plugins_dir / "demo-2.0.jar").write_bytes(b"half-copied")

        assert await self._run(plugins_dir, ServerLockfile.load(tmp_path / "server-lock.json")) == []
        assert sorted(p.name for p in plugins_dir.iterdir()) == ["demo-2.1.jar"]

    async def test_failure_is_reported(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        _mock_modrinth(httpx_mock, [_version("2.0", ["1.21.4"])])
        httpx_mock.add_response(url="https://cdn.example/demo-2.0.jar", content=b"tampered")
        plugins_dir = tmp_path / "plugins"
        lockfile = ServerLockfile.load(tmp_path / "server-lock.json")

        failures = await self._run(plugins_dir, lockfile)

        assert len(failures) == 1
        assert "checksum mismatch" in failures[0]
        assert lockfile.plugins == {}
        assert [p.name for p in plugins_dir.iterdir()] == []


class TestDownloadFile:
    async def test_checksum_mismatch_removes_file(self, tmp_path: Path, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url="https://cdn.example/a.jar", content=b"data")
        target = tmp_path / "a.jar"

        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="SHA256 checksum mismatch"):
                await download_file(client, "https://cdn.example/a.jar", target, {"sha256": "00"})

        assert not target.exists()


@pytest.mark.parametrize(
    ("name", "expected"),
    [("plugin.jar", "plugin.jar"), ("../../etc/passwd", "passwd"), ("..\\evil.jar", "evil.jar")],
)
def test_safe_filename(name: str, expected: str) -> None:
    assert safe_filename(name) == expected


def test_safe_filename_rejects_empty() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        safe_filename("..")
