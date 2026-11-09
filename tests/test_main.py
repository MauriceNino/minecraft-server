"""Tests for the mc-orchestrator subcommands that are run inside a running container."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner, Result
from pytest_httpx import HTTPXMock

from orchestrator import http
from orchestrator.__main__ import cli
from orchestrator.lockfile import PluginLockEntry, ServerLockfile
from orchestrator.server_properties import SHORTCUTS

PAPER_BUILD_URL = "https://fill.papermc.io/v3/projects/paper/versions/1.21.4/builds/100"
MODRINTH = "https://api.modrinth.com/v2/project"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(http, "BACKOFF_BASE_SECONDS", 0.0)
    names = ("TYPE", "PLUGINS", "APPLIED_TEMPLATES", "CONFIG_PATHS", "GITHUB_TOKEN", "CURSEFORGE_API_KEY", *SHORTCUTS)
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERSION", "1.21.4")
    monkeypatch.setenv("BUILD", "100")


def _invoke(*args: str) -> Result:
    result = CliRunner().invoke(cli, list(args))
    # Rich adds colours and wraps long lines, compare the plain words
    result.plain = " ".join(click.unstyle(result.output).split())  # type: ignore[attr-defined]
    return result


def _jar(name: str, version: str) -> bytes:
    return f"{name}-{version}".encode()


def _mock_paper(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=PAPER_BUILD_URL,
        json={
            "id": 100,
            "channel": "STABLE",
            "downloads": {
                "server:default": {
                    "name": "paper-1.21.4-100.jar",
                    "url": "https://cdn.example/paper.jar",
                    "checksums": {"sha256": "00"},
                }
            },
        },
    )


def _mock_modrinth(httpx_mock: HTTPXMock, slug: str, version: str, *, is_optional: bool = False) -> None:
    jar = _jar(slug, version)
    httpx_mock.add_response(
        url=f"{MODRINTH}/{slug}",
        json={"title": slug.title(), "loaders": ["paper"]},
        is_optional=is_optional,
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=re.compile(rf"{MODRINTH}/{slug}/version\?.*"),
        json=[
            {
                "id": f"{slug}-{version}",
                "version_number": version,
                "version_type": "release",
                "loaders": ["paper"],
                "game_versions": ["1.21.4"],
                "dependencies": [],
                "files": [
                    {
                        "url": f"https://cdn.example/{slug}-{version}.jar",
                        "filename": f"{slug}-{version}.jar",
                        "primary": True,
                        "hashes": {"sha512": hashlib.sha512(jar).hexdigest()},
                    }
                ],
            }
        ],
        is_optional=is_optional,
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=f"https://cdn.example/{slug}-{version}.jar", content=jar, is_optional=True, is_reusable=True
    )


def _install_plugin(tmp_path: Path, slug: str, version: str) -> None:
    """Record *slug* in the lockfile as if *version* was installed earlier."""
    plugins_dir = tmp_path / "runtime" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    jar = plugins_dir / f"{slug}-{version}.jar"
    jar.write_bytes(_jar(slug, version))
    lockfile = ServerLockfile.load(tmp_path / "runtime" / "server-lock.json")
    lockfile.plugins[f"modrinth:{slug}"] = PluginLockEntry(
        display_name=slug.title(),
        version=version,
        sha256=hashlib.sha256(jar.read_bytes()).hexdigest(),
        filename=jar.name,
        updated_at="2026-01-01T00:00:00+00:00",
        target_version="latest",
    )
    lockfile.save()


class TestReapply:
    def test_applies_templates_and_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "templates" / "base").mkdir(parents=True)
        (tmp_path / "templates" / "base" / "server.properties").write_text("motd=From template\n")
        (tmp_path / "runtime").mkdir()
        (tmp_path / "runtime" / "server.properties").write_text("motd=Old\nmax-players=20\nlevel-name=world\n")
        monkeypatch.setenv("APPLIED_TEMPLATES", "base")
        monkeypatch.setenv("CONFIG_PATHS", "props -> server.properties")
        monkeypatch.setenv("CONFIG_props", "max-players=5")

        result = _invoke("reapply")

        assert result.exit_code == 0, result.output
        assert "Successfully reapplied" in result.plain
        props = (tmp_path / "runtime" / "server.properties").read_text().splitlines()
        assert "motd=From template" in props
        assert "max-players=5" in props
        assert "level-name=world" in props

    def test_shortcuts_go_between_templates_and_overrides(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "templates" / "base").mkdir(parents=True)
        (tmp_path / "templates" / "base" / "server.properties").write_text("motd=From template\npvp=true\n")
        (tmp_path / "runtime").mkdir()
        (tmp_path / "runtime" / "server.properties").write_text("max-players=20\n")
        monkeypatch.setenv("APPLIED_TEMPLATES", "base")
        monkeypatch.setenv("MOTD", "§aHello")
        monkeypatch.setenv("MAX_PLAYERS", "10")
        monkeypatch.setenv("CONFIG_PATHS", "props -> server.properties")
        monkeypatch.setenv("CONFIG_props", "max-players=5")

        result = _invoke("reapply")

        assert result.exit_code == 0, result.output
        props = (tmp_path / "runtime" / "server.properties").read_text().splitlines()
        assert "motd=\\u00a7aHello" in props
        assert "pvp=true" in props
        assert "max-players=5" in props

    def test_nothing_configured(self) -> None:
        result = _invoke("reapply")

        assert result.exit_code == 0
        assert "No templates, server properties or config overrides configured" in result.plain

    @pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
    def test_runtime_dir_not_writable(self, tmp_path: Path) -> None:
        (tmp_path / "runtime").mkdir(mode=0o555)

        result = _invoke("reapply")

        assert result.exit_code == 1
        assert "Permission Denied" in result.plain
        assert f"sudo chown -R {os.getuid()}:{os.getgid()}" in result.plain


class TestUpdate:
    def test_updates_all_plugins(self, tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLUGINS", "modrinth:alpha\nmodrinth:beta")
        _install_plugin(tmp_path, "alpha", "1.0")
        _mock_paper(httpx_mock)
        _mock_modrinth(httpx_mock, "alpha", "2.0")
        _mock_modrinth(httpx_mock, "beta", "1.0")

        result = _invoke("update")

        assert result.exit_code == 0, result.output
        assert "Successfully updated plugins" in result.plain
        plugins = sorted(p.name for p in (tmp_path / "runtime" / "plugins").iterdir())
        assert plugins == ["alpha-2.0.jar", "beta-1.0.jar"]

    def test_single_plugin(self, tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLUGINS", "modrinth:alpha\nmodrinth:beta")
        _install_plugin(tmp_path, "alpha", "1.0")
        _install_plugin(tmp_path, "beta", "1.0")
        _mock_paper(httpx_mock)
        _mock_modrinth(httpx_mock, "alpha", "2.0")
        _mock_modrinth(httpx_mock, "beta", "2.0", is_optional=True)

        result = _invoke("update", "-p", "modrinth:alpha")

        assert result.exit_code == 0, result.output
        plugins = sorted(p.name for p in (tmp_path / "runtime" / "plugins").iterdir())
        assert plugins == ["alpha-2.0.jar", "beta-1.0.jar"]
        assert not httpx_mock.get_requests(url=f"{MODRINTH}/beta")

    def test_unknown_plugin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLUGINS", "modrinth:alpha")

        result = _invoke("update", "-p", "modrinth:missing")

        assert result.exit_code == 1
        assert "Plugin 'modrinth:missing' not found in configuration" in result.plain

    def test_failure_exits_non_zero(self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLUGINS", "modrinth:alpha")
        _mock_paper(httpx_mock)
        httpx_mock.add_response(url=f"{MODRINTH}/alpha", status_code=404)

        result = _invoke("update")

        assert result.exit_code == 1
        assert "1 plugin(s) could not be updated" in result.plain

    def test_platform_without_plugins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TYPE", "VANILLA")

        result = _invoke("update")

        assert result.exit_code == 0
        assert "VANILLA does not support plugins" in result.plain


class TestCheckUpdates:
    def test_shows_available_updates(
        self, tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGINS", "modrinth:alpha\nmodrinth:beta")
        _install_plugin(tmp_path, "alpha", "1.0")
        _install_plugin(tmp_path, "beta", "2.0")
        _mock_paper(httpx_mock)
        _mock_modrinth(httpx_mock, "alpha", "2.0")
        _mock_modrinth(httpx_mock, "beta", "2.0")

        result = _invoke("check-updates")

        assert result.exit_code == 0, result.output
        assert "Update available (2.0)" in result.plain
        assert "Up to date" in result.plain
        # Only checks, never downloads
        assert not httpx_mock.get_requests(url=re.compile(r"https://cdn\.example/.*"))
        assert sorted(p.name for p in (tmp_path / "runtime" / "plugins").iterdir()) == ["alpha-1.0.jar", "beta-2.0.jar"]

    def test_no_plugins(self) -> None:
        result = _invoke("check-updates")

        assert result.exit_code == 0
        assert "No plugins configured" in result.plain

    def test_reports_unresolvable_plugins(self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLUGINS", "modrinth:alpha")
        _mock_paper(httpx_mock)
        httpx_mock.add_response(url=f"{MODRINTH}/alpha", status_code=404, is_reusable=True)

        result = _invoke("check-updates")

        assert result.exit_code == 0
        assert "Encountered 1 error(s) during check" in result.plain


def test_version() -> None:
    result = _invoke("--version")

    assert result.exit_code == 0
    assert result.output.startswith("mc-orchestrator, version ")
