from __future__ import annotations

import re
import tomllib
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from orchestrator import http
from orchestrator.cli import load_config
from orchestrator.constants import PlatformType, PluginProviderType, PluginUpdateStrategy
from orchestrator.http import ApiTokens, create_http_client
from orchestrator.lockfile import ServerLockfile
from orchestrator.plugins import download_plugins
from orchestrator.plugins.base import PluginSpec, ResolvedPlugin
from orchestrator.plugins.pumpkin_market import (
    API_BASE,
    PermissionGrant,
    PumpkinMarketProvider,
    apply_permission_grants,
    permission_grants,
)

WASM = b"\0asm\x0d\0\x01\0component"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0.0)


def _plugin(public_id: str = "ID0WVaaw", name: str = "Perfmon", version: str | None = "0.3.2") -> dict:
    return {
        "id": 184,
        "public_id": public_id,
        "name": name,
        "version": version,
        "api_version": "0.1.0",
        "category": "Utilities",
        "type": "free",
        "price": 0.0,
        "downloads": 3,
        "dev_name": "dev",
        "created_at": "2026-11-01T00:00:00+00:00",
        "updated_at": "2026-11-10T00:00:00+00:00",
    }


def _spec(identifier: str = "ID0WVaaw", version: str = "latest", force: bool = False) -> PluginSpec:
    return PluginSpec(PluginProviderType.PUMPKIN, identifier, version, force=force)


async def _resolve(spec: PluginSpec, platform: PlatformType = PlatformType.PUMPKIN) -> ResolvedPlugin:
    async with create_http_client() as client:
        return await PumpkinMarketProvider().resolve(spec, platform, "26.3", client)


async def test_resolves_by_id(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw", json=_plugin())

    resolved = await _resolve(_spec())

    assert resolved == ResolvedPlugin(
        display_name="Perfmon",
        version="0.3.2",
        download_url=f"{API_BASE}/plugins/ID0WVaaw/download",
        filename="Perfmon.wasm",
    )


async def test_slug_of_the_url_is_ignored(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{API_BASE}/plugins/CAUifsaq", json=_plugin("CAUifsaq", "Mobs Night Spawn", "0.1.6"))

    resolved = await _resolve(_spec("CAUifsaq-anything-goes-here"))

    assert resolved.download_url == f"{API_BASE}/plugins/CAUifsaq/download"
    assert resolved.filename == "Mobs_Night_Spawn.wasm"


async def test_unknown_plugin(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{API_BASE}/plugins/Nope1234", status_code=404, text="Plugin not found")

    with pytest.raises(RuntimeError, match="'Nope1234' was not found on the Pumpkin Market"):
        await _resolve(_spec("Nope1234-perfmon"))


async def test_missing_id() -> None:
    with pytest.raises(RuntimeError, match="is not a Pumpkin Market plugin ID"):
        await _resolve(_spec("-perfmon"))


async def test_only_the_current_version_can_be_pinned(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw", json=_plugin(), is_reusable=True)

    assert (await _resolve(_spec(version="0.3.2"))).version == "0.3.2"
    with pytest.raises(RuntimeError, match=r"only offers the current version.*@0\.3\.2"):
        await _resolve(_spec(version="0.3.1"))


async def test_plugin_without_version_uses_its_last_update(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw", json=_plugin(version=None))
    assert (await _resolve(_spec())).version == "2026-11-10T00:00:00+00:00"


async def test_only_for_pumpkin(httpx_mock: HTTPXMock) -> None:
    with pytest.raises(RuntimeError, match="does not support platform 'PUMPKIN'"):
        await _resolve(_spec(), PlatformType.PAPER)

    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw", json=_plugin())
    assert (await _resolve(_spec(force=True), PlatformType.PAPER)).filename == "Perfmon.wasm"


async def test_refused_download_explains_why(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = f"{API_BASE}/plugins/gJeyR3mC/download"
    httpx_mock.add_response(url=url, status_code=403, text="This plugin is not yet published.", is_reusable=True)
    resolved = ResolvedPlugin("Jobs", "1.1.0", url, "Jobs.wasm")

    async with create_http_client() as client:
        with pytest.raises(RuntimeError, match=r"refused the download of Jobs: This plugin is not yet published\."):
            await PumpkinMarketProvider().download(resolved, tmp_path, client)
    assert not (tmp_path / "Jobs.wasm").exists()


async def test_refused_download_without_a_reason(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = f"{API_BASE}/plugins/gJeyR3mC/download"
    page = "<!DOCTYPE html><html>Cloudflare</html>"
    httpx_mock.add_response(url=url, status_code=403, html=page, is_reusable=True)
    resolved = ResolvedPlugin("Jobs", "1.1.0", url, "Jobs.wasm")

    async with create_http_client() as client:
        with pytest.raises(RuntimeError, match=r"refused the download of Jobs: 403 Forbidden\. Paid plugins"):
            await PumpkinMarketProvider().download(resolved, tmp_path, client)


async def test_token_is_only_sent_to_the_market(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw/download", content=WASM)
    httpx_mock.add_response(url="https://cdn.example/file", content=b"")

    async with create_http_client(tokens=ApiTokens(pumpkin_market="pmk_secret")) as client:
        await client.get(f"{API_BASE}/plugins/ID0WVaaw/download")
        await client.get("https://cdn.example/file")

    market, other = httpx_mock.get_requests()
    assert market.headers["Authorization"] == "Bearer pmk_secret"
    assert "Authorization" not in other.headers
    assert load_config({"PUMPKIN_MARKET_TOKEN": " pmk_x "}).api_tokens.pumpkin_market == "pmk_x"


async def test_wasm_plugins_go_next_to_patchbukkit(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw", json=_plugin())
    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw/download", content=WASM)
    config = load_config({"TYPE": "PUMPKIN", "DATA_DIR": str(tmp_path), "PLUGINS": "pumpkin:ID0WVaaw"})
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})

    async def install(specs: list[PluginSpec]) -> list[str]:
        return await download_plugins(
            plugin_specs=specs,
            platform_type=PlatformType.PUMPKIN,
            mc_version="26.3",
            plugins_dir=config.plugins_dir,
            lockfile=lockfile,
            strategy=PluginUpdateStrategy.AUTO,
            check_cache_seconds=0,
            wasm_plugins_dir=config.wasm_plugins_dir,
        )

    assert await install(config.plugin_specs) == []
    wasm = tmp_path / "runtime" / "plugins" / "Perfmon.wasm"
    assert wasm.read_bytes() == WASM
    assert not (config.plugins_dir / "Perfmon.wasm").exists()

    # Installed and unchanged: no new download
    httpx_mock.add_response(url=f"{API_BASE}/plugins/ID0WVaaw", json=_plugin())
    assert await install(config.plugin_specs) == []
    assert len(httpx_mock.get_requests(url=f"{API_BASE}/plugins/ID0WVaaw/download")) == 1

    # Removed from PLUGINS: deleted from the WebAssembly plugin directory
    assert await install([]) == []
    assert not wasm.exists()
    assert "pumpkin:ID0WVaaw" not in lockfile.plugins


def test_spec_is_parsed() -> None:
    spec = load_config({"TYPE": "PUMPKIN", "PLUGINS": "pumpkin:ID0WVaaw-perfmon@0.3.2"}).plugin_specs[0]
    assert (spec.provider, spec.identifier, spec.version) == (PluginProviderType.PUMPKIN, "ID0WVaaw-perfmon", "0.3.2")


@pytest.mark.parametrize("status", [500, 404])
async def test_other_download_errors_are_raised(httpx_mock: HTTPXMock, tmp_path: Path, status: int) -> None:
    url = f"{API_BASE}/plugins/x/download"
    httpx_mock.add_response(url=url, status_code=status, is_reusable=True)
    async with create_http_client() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await PumpkinMarketProvider().download(ResolvedPlugin("X", "1", url, "X.wasm"), tmp_path, client)


def test_allow_grants_permissions_to_the_plugins_own_name(tmp_path: Path) -> None:
    plugins = (
        "pumpkin:ID0WVaaw[allow=sys.info, fs.read.data]\n"
        "pumpkin:CAUifsaq-mobs-night-spawn[allow=network.tcp,name=mob-spawner]\n"
        "pumpkin:gJeyR3mC-jobs[allow=]\n"
        "pumpkin:abcdefgh[allow=fs.read.data]\n"
        "pumpkin:NoGrant\n"
        "modrinth:luckperms[allow=sys.env]"
    )
    specs = load_config({"TYPE": "PUMPKIN", "PLUGINS": plugins}).plugin_specs
    lockfile = ServerLockfile(tmp_path / "lock.json", plugins={})
    lockfile.update_plugin(
        "pumpkin:ID0WVaaw", ResolvedPlugin("Perfmon", "0.3.2", "u", "Perfmon.wasm"), _file(tmp_path), "latest"
    )

    config = tmp_path / "pumpkin.toml"
    config.write_text(
        "use_favicon = true\n\n[plugins]\nenabled = true\n\n[plugins.overrides.perfmon]\nmax_memory_mb = 64\n"
    )
    apply_permission_grants(permission_grants(specs, lockfile), config)

    data = tomllib.loads(config.read_text())
    assert data["use_favicon"] is True
    assert data["plugins"]["enabled"] is True
    assert data["plugins"]["overrides"] == {
        # The market name from the lockfile, in lowercase, keeping the other settings
        "perfmon": {"max_memory_mb": 64, "allowed_permissions": ["sys.info", "fs.read.data"]},
        "mob-spawner": {"allowed_permissions": ["network.tcp"]},
        # Not installed yet: the slug of the market URL, else the ID
        "jobs": {"allowed_permissions": []},
        "abcdefgh": {"allowed_permissions": ["fs.read.data"]},
    }


def test_no_allow_no_overrides() -> None:
    specs = load_config({"TYPE": "PUMPKIN", "PLUGINS": "pumpkin:ID0WVaaw-perfmon"}).plugin_specs
    assert permission_grants(specs, ServerLockfile(Path("lock.json"), plugins={})) == []


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "Perfmon.wasm"
    path.write_bytes(WASM)
    return path


def test_each_grant_is_logged_with_its_plugin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    grants = [
        PermissionGrant("pumpkin:ID0WVaaw-perfmon", "perfmon", ["sys.info", "http.outbound"]),
        PermissionGrant("pumpkin:gJeyR3mC-jobs", "jobs", []),
    ]

    apply_permission_grants(grants, tmp_path / "pumpkin.toml")

    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "pumpkin:ID0WVaaw-perfmon (perfmon: sys.info, http.outbound)" in out
    assert "pumpkin:gJeyR3mC-jobs (jobs: no permissions)" in out
