from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit
from pytest_httpx import HTTPXMock
from ruamel.yaml import YAML

from orchestrator.constants import PlatformType
from orchestrator.http import create_http_client
from orchestrator.providers import pumpkin
from orchestrator.providers.base import ResolvedVersion
from orchestrator.providers.pumpkin import PumpkinProvider
from orchestrator.providers.purpur import PurpurProvider
from orchestrator.providers.spigotmc import GetBukkitProvider
from orchestrator.providers.vanilla import MANIFEST_URL, VanillaProvider
from orchestrator.rcon import inject_rcon

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


class TestInjectRcon:
    TRICKY_VALUE = "p'a: ss\"word"  # quotes and YAML syntax

    def test_server_properties(self, tmp_path: Path) -> None:
        inject_rcon(PlatformType.PAPER, tmp_path, tmp_path / "plugins", 25575, self.TRICKY_VALUE)

        props = (tmp_path / "server.properties").read_text().splitlines()
        assert "enable-rcon=true" in props
        assert f"rcon.password={self.TRICKY_VALUE}" in props
        assert (tmp_path / ".rcon-password").read_text() == self.TRICKY_VALUE
        assert (tmp_path / ".rcon-password").stat().st_mode & 0o777 == 0o600

    def test_server_properties_escapes_password(self, tmp_path: Path) -> None:
        inject_rcon(PlatformType.PAPER, tmp_path, tmp_path / "plugins", 25575, " a\\b\nü😀")

        props = (tmp_path / "server.properties").read_text().splitlines()
        assert "rcon.password=\\ a\\\\b\\n\\u00fc\\ud83d\\ude00" in props
        assert (tmp_path / ".rcon-password").read_text() == " a\\b\nü😀"

    def test_velocity_yaml_keeps_special_characters(self, tmp_path: Path) -> None:
        inject_rcon(PlatformType.VELOCITY, tmp_path, tmp_path / "plugins", 25576, self.TRICKY_VALUE)

        config = YAML().load((tmp_path / "plugins" / "velocircon" / "rcon.yml").read_text())
        assert config["password"] == self.TRICKY_VALUE
        assert config["port"] == 25576

    def test_pumpkin_toml_keeps_special_characters(self, tmp_path: Path) -> None:
        inject_rcon(PlatformType.PUMPKIN, tmp_path, tmp_path / "plugins", 25575, self.TRICKY_VALUE)

        config = tomlkit.loads((tmp_path / "config" / "features.toml").read_text())
        assert config["networking"]["rcon"]["password"] == self.TRICKY_VALUE  # type: ignore[index]
        assert config["networking"]["rcon"]["enabled"] is True  # type: ignore[index]
