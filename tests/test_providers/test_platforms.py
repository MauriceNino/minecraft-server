from __future__ import annotations

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from orchestrator.http import create_http_client
from orchestrator.providers import pumpkin
from orchestrator.providers.base import ResolvedVersion
from orchestrator.providers.bungeecord import BungeeCordProvider
from orchestrator.providers.pumpkin import PumpkinProvider
from orchestrator.providers.purpur import PurpurProvider
from orchestrator.providers.spigotmc import GetBukkitProvider
from orchestrator.providers.vanilla import MANIFEST_URL, VanillaProvider

MANIFEST = {
    "latest": {"release": "1.21.4", "snapshot": "25w14a"},
    "versions": [
        {"id": "25w14a", "url": "https://meta.example/25w14a.json"},
        {"id": "1.21.4", "url": "https://meta.example/1.21.4.json"},
    ],
}


async def test_vanilla(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=MANIFEST_URL, json=MANIFEST)
    httpx_mock.add_response(
        url="https://meta.example/25w14a.json",
        json={"downloads": {"server": {"url": "https://cdn.example/server.jar", "sha1": "aa"}}},
    )

    async with create_http_client() as client:
        resolved = await VanillaProvider().resolve_version("experimental", "latest", client)

    assert (resolved.version, resolved.filename, resolved.sha1) == ("25w14a", "vanilla-25w14a.jar", "aa")


async def test_vanilla_unknown_version(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=MANIFEST_URL, json=MANIFEST)

    async with create_http_client() as client:
        with pytest.raises(RuntimeError, match="not found"):
            await VanillaProvider().resolve_version("1.0.0", "latest", client)


async def test_purpur(httpx_mock: HTTPXMock) -> None:
    api = "https://api.purpurmc.org/v2/purpur"
    httpx_mock.add_response(url=api, json={"metadata": {"current": "1.21.4"}})
    httpx_mock.add_response(url=f"{api}/1.21.4", json={"builds": {"latest": "2400"}})
    httpx_mock.add_response(url=f"{api}/1.21.4/2400", json={"md5": "bb"})

    async with create_http_client() as client:
        resolved = await PurpurProvider().resolve_version("latest", "latest", client)

    assert resolved.filename == "purpur-1.21.4-2400.jar"
    assert resolved.download_url == f"{api}/1.21.4/2400/download"
    assert resolved.md5 == "bb"


async def test_getbukkit_latest_and_404(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://getbukkit.org/download/spigot",
        text="<div><h4>Version</h4>\n  <h2>1.21.4</h2></div><div><h4>Version</h4><h2>1.21.3</h2></div>",
    )
    httpx_mock.add_response(url="https://cdn.getbukkit.org/spigot/spigot-1.21.4.jar", status_code=404)
    provider = GetBukkitProvider(project="spigot")

    async with create_http_client() as client:
        resolved = await provider.resolve_version("latest", "latest", client)
        assert resolved.version == "1.21.4"
        with pytest.raises(RuntimeError, match=r"failed \(404\)"):
            await provider.download(resolved, tmp_path, client)


async def test_pumpkin_build_follows_asset_checksum(httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pumpkin, "_asset_names", lambda: ("pumpkin-X64-Linux", "libpatchbukkit-X64-Linux.so"))
    httpx_mock.add_response(
        url=pumpkin.PUMPKIN_RELEASE_URL,
        json={
            "tag_name": "nightly",
            "draft": False,
            "prerelease": True,
            "assets": [
                {
                    "name": "pumpkin-X64-Linux",
                    "digest": "sha256:" + "c" * 64,
                    "browser_download_url": "https://gh.example/pumpkin",
                }
            ],
        },
    )
    httpx_mock.add_response(url=MANIFEST_URL, json=MANIFEST)

    async with create_http_client() as client:
        resolved = await PumpkinProvider().resolve_version("experimental", "latest", client)

    assert resolved == ResolvedVersion(
        project="pumpkin",
        version="1.21.4",
        build="c" * 12,
        download_url="https://gh.example/pumpkin",
        filename="pumpkin-X64-Linux",
        sha256="c" * 64,
    )


async def test_pumpkin_requires_experimental() -> None:
    async with create_http_client() as client:
        with pytest.raises(ValueError, match="VERSION=experimental"):
            await PumpkinProvider().resolve_version("latest", "latest", client)


BUNGEE_JOB = "https://hub.spigotmc.org/jenkins/job/BungeeCord"
BUNGEE_TREE = "?tree=number%2Cresult%2Cartifacts%5BrelativePath%5D"


async def test_bungeecord_latest(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BUNGEE_JOB}/lastSuccessfulBuild/api/json{BUNGEE_TREE}",
        json={"number": 2111, "result": "SUCCESS", "artifacts": [{"relativePath": "bootstrap/target/BungeeCord.jar"}]},
    )

    async with create_http_client() as client:
        resolved = await BungeeCordProvider().resolve_version("latest", "latest", client)

    assert resolved == ResolvedVersion(
        project="bungeecord",
        version="unknown",
        build="2111",
        download_url=f"{BUNGEE_JOB}/2111/artifact/bootstrap/target/BungeeCord.jar",
        filename="bungeecord-2111.jar",
    )


async def test_bungeecord_pinned_build_not_found(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BUNGEE_JOB}/99999/api/json{BUNGEE_TREE}", status_code=404)

    async with create_http_client() as client:
        with pytest.raises(RuntimeError, match="not found"):
            await BungeeCordProvider().resolve_version("latest", "99999", client)


async def test_bungeecord_failed_build(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BUNGEE_JOB}/2000/api/json{BUNGEE_TREE}", json={"number": 2000, "result": "FAILURE"})

    async with create_http_client() as client:
        with pytest.raises(RuntimeError, match="did not succeed"):
            await BungeeCordProvider().resolve_version("latest", "2000", client)
