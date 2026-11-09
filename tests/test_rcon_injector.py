"""Tests for enabling RCON in the platforms' config files."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit
from ruamel.yaml import YAML

from orchestrator.constants import PlatformType
from orchestrator.rcon import inject_rcon


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
        assert config["colors"] is True

    def test_pumpkin_toml_keeps_special_characters(self, tmp_path: Path) -> None:
        inject_rcon(PlatformType.PUMPKIN, tmp_path, tmp_path / "plugins", 25575, self.TRICKY_VALUE)

        config = tomlkit.loads((tmp_path / "config" / "features.toml").read_text())
        assert config["networking"]["rcon"]["password"] == self.TRICKY_VALUE  # type: ignore[index]
        assert config["networking"]["rcon"]["enabled"] is True  # type: ignore[index]

    @pytest.mark.parametrize("platform", [PlatformType.WATERFALL, PlatformType.BUNGEECORD])
    def test_bungee_yaml(self, tmp_path: Path, platform: PlatformType) -> None:
        inject_rcon(platform, tmp_path, tmp_path / "plugins", 25577, self.TRICKY_VALUE)

        config = YAML().load((tmp_path / "plugins" / "bungee-rcon" / "config.yml").read_text())
        assert config == {"port": 25577, "password": self.TRICKY_VALUE, "colored": True}
        assert not (tmp_path / "server.properties").exists()

    @pytest.mark.parametrize("platform", [PlatformType.VANILLA, PlatformType.FOLIA, PlatformType.PURPUR])
    def test_server_platforms_use_server_properties(self, tmp_path: Path, platform: PlatformType) -> None:
        inject_rcon(platform, tmp_path, tmp_path / "plugins", 25575, "secret")

        assert "rcon.password=secret" in (tmp_path / "server.properties").read_text().splitlines()

    def test_keeps_other_settings(self, tmp_path: Path) -> None:
        (tmp_path / "server.properties").write_text("motd=Hello\nenable-rcon=false\nrcon.port=1234\n")

        inject_rcon(PlatformType.PAPER, tmp_path, tmp_path / "plugins", 25575, "secret")

        props = (tmp_path / "server.properties").read_text().splitlines()
        assert "motd=Hello" in props
        assert "enable-rcon=true" in props
        assert "rcon.port=25575" in props
        assert "enable-rcon=false" not in props
        assert "rcon.port=1234" not in props

    def test_pumpkin_keeps_other_settings(self, tmp_path: Path) -> None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "features.toml").write_text(
            "[networking.rcon]\nenabled = false\nmax_connections = 5\n\n[networking.query]\nenabled = true\n"
        )

        inject_rcon(PlatformType.PUMPKIN, tmp_path, tmp_path / "plugins", 25580, "secret")

        config = tomlkit.loads((tmp_path / "config" / "features.toml").read_text())
        rcon = config["networking"]["rcon"]  # type: ignore[index]
        assert rcon["enabled"] is True  # type: ignore[index]
        assert rcon["address"] == "0.0.0.0:25580"  # type: ignore[index]
        assert rcon["max_connections"] == 5  # type: ignore[index]
        assert config["networking"]["query"]["enabled"] is True  # type: ignore[index]

    def test_new_password_replaces_the_old_one(self, tmp_path: Path) -> None:
        inject_rcon(PlatformType.PAPER, tmp_path, tmp_path / "plugins", 25575, "a-much-longer-old-password")
        inject_rcon(PlatformType.PAPER, tmp_path, tmp_path / "plugins", 25575, "new")

        props = (tmp_path / "server.properties").read_text().splitlines()
        assert [p for p in props if p.startswith("rcon.password=")] == ["rcon.password=new"]
        assert (tmp_path / ".rcon-password").read_text() == "new"
        assert (tmp_path / ".rcon-password").stat().st_mode & 0o777 == 0o600
