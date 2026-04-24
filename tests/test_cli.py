"""Tests for CLI config loading."""

from __future__ import annotations

import pytest

from orchestrator.cli import _collect_config_overrides, load_config
from orchestrator.constants import PlatformType
from orchestrator.fs_orchestrator.sigils import DirSigil


class TestLoadConfig:
    def test_defaults(self) -> None:
        config = load_config(environ={})
        assert config.platform == PlatformType.PAPER
        assert config.version == "latest"
        assert config.build == "latest"
        assert config.memory == "1G"
        assert config.rcon_enabled is True
        assert config.rcon_port == 25575
        assert config.plugins_update_strategy == "auto"

    def test_platform_parsing(self) -> None:
        config = load_config(environ={"TYPE": "velocity"})
        assert config.platform == PlatformType.VELOCITY

    def test_invalid_platform(self) -> None:
        with pytest.raises(SystemExit, match="Unknown platform"):
            load_config(environ={"TYPE": "INVALID"})

    def test_plugins_multiline(self) -> None:
        config = load_config(environ={"PLUGINS": "modrinth:luckperms@latest\nhangar:libertybans@latest\n"})
        assert config.plugin_lines == [
            "modrinth:luckperms@latest",
            "hangar:libertybans@latest",
        ]

    def test_applied_templates(self) -> None:
        config = load_config(environ={"APPLIED_TEMPLATES": "all\nbackends\n"})
        assert config.applied_templates == ["all", "backends"]

    def test_rcon_disabled(self) -> None:
        config = load_config(environ={"RCON_ENABLED": "false"})
        assert config.rcon_enabled is False

    def test_jvm_flags(self) -> None:
        config = load_config(environ={"JVM_FLAGS": "-XX:+UseG1GC -Dfoo=bar"})
        assert config.jvm_flags == ["-XX:+UseG1GC", "-Dfoo=bar"]

    # VERSION / BUILD normalisation
    def test_version_stable_alias(self) -> None:
        config = load_config(environ={"VERSION": "stable"})
        assert config.version == "latest"

    def test_version_latest_passthrough(self) -> None:
        config = load_config(environ={"VERSION": "latest"})
        assert config.version == "latest"

    def test_version_experimental_alias(self) -> None:
        config = load_config(environ={"VERSION": "experimental"})
        assert config.version == "experimental"

    def test_version_beta_alias(self) -> None:
        config = load_config(environ={"VERSION": "beta"})
        assert config.version == "experimental"

    def test_version_explicit(self) -> None:
        config = load_config(environ={"VERSION": "1.21.4"})
        assert config.version == "1.21.4"

    def test_build_stable_alias(self) -> None:
        config = load_config(environ={"BUILD": "stable"})
        assert config.build == "latest"

    def test_build_experimental_alias(self) -> None:
        config = load_config(environ={"BUILD": "experimental"})
        assert config.build == "experimental"

    def test_build_beta_alias(self) -> None:
        config = load_config(environ={"BUILD": "beta"})
        assert config.build == "experimental"

    def test_build_explicit_number(self) -> None:
        config = load_config(environ={"BUILD": "456"})
        assert config.build == "456"

    def test_config_overrides_via_paths(self) -> None:
        config = load_config(
            environ={
                "CONFIG_PATHS": "server_properties -> server.properties\nluckperms -> plugins/luckperms/config.yml\n",
                "CONFIG_server_properties": "motd=Hello",
                "CONFIG_luckperms": "server: proxy",
            }
        )
        assert len(config.config_overrides) == 2
        sigils = {path: sigil for sigil, path, _ in config.config_overrides}
        assert sigils["server.properties"] == DirSigil.NONE
        assert sigils["plugins/luckperms/config.yml"] == DirSigil.NONE

    def test_config_overrides_force_sigil(self) -> None:
        config = load_config(
            environ={
                "CONFIG_PATHS": "!force:server_properties -> server.properties\n",
                "CONFIG_server_properties": "motd=Hello",
            }
        )
        assert len(config.config_overrides) == 1
        sigil, path, content = config.config_overrides[0]
        assert sigil == DirSigil.FORCE
        assert path == "server.properties"
        assert "motd=Hello" in content

    def test_config_overrides_replace_sigil(self) -> None:
        config = load_config(
            environ={
                "CONFIG_PATHS": "!replace:forwarding_secret -> forwarding.secret\n",
                "CONFIG_forwarding_secret": "mysecret",
            }
        )
        assert len(config.config_overrides) == 1
        sigil, path, _ = config.config_overrides[0]
        assert sigil == DirSigil.REPLACE
        assert path == "forwarding.secret"

    def test_config_overrides_delete_sigil(self) -> None:
        config = load_config(
            environ={
                "CONFIG_PATHS": "!delete:old_config -> old-config.yml\n",
            }
        )
        assert len(config.config_overrides) == 1
        sigil, path, content = config.config_overrides[0]
        assert sigil == DirSigil.DELETE
        assert path == "old-config.yml"
        assert content == ""

    def test_config_overrides_missing_content_skipped(self) -> None:
        """Entries in CONFIG_PATHS with no matching CONFIG_<key> are skipped."""
        config = load_config(
            environ={
                "CONFIG_PATHS": "server_properties -> server.properties\n",
                # CONFIG_server_properties intentionally absent
            }
        )
        assert config.config_overrides == []

    def test_config_overrides_empty_paths(self) -> None:
        config = load_config(environ={})
        assert config.config_overrides == []

    def test_plugins_update_strategy_parsing(self) -> None:
        config = load_config(environ={"PLUGINS_UPDATE_STRATEGY": "force"})
        assert config.plugins_update_strategy == "force"

        config = load_config(environ={"PLUGINS_UPDATE_STRATEGY": "AUTO"})
        assert config.plugins_update_strategy == "auto"

    def test_invalid_plugins_update_strategy(self) -> None:
        with pytest.raises(SystemExit, match="Unknown PLUGINS_UPDATE_STRATEGY"):
            load_config(environ={"PLUGINS_UPDATE_STRATEGY": "INVALID"})


class TestCollectConfigOverrides:
    def test_basic_mapping(self) -> None:
        result = _collect_config_overrides(
            {
                "CONFIG_PATHS": "mykey -> some/path.yml\n",
                "CONFIG_mykey": "content: true",
            }
        )
        assert len(result) == 1
        sigil, path, content = result[0]
        assert sigil == DirSigil.NONE
        assert path == "some/path.yml"
        assert content == "content: true"

    def test_force_sigil(self) -> None:
        result = _collect_config_overrides(
            {
                "CONFIG_PATHS": "!force:mykey -> config.yml\n",
                "CONFIG_mykey": "x: 1",
            }
        )
        assert result[0][0] == DirSigil.FORCE

    def test_replace_sigil(self) -> None:
        result = _collect_config_overrides(
            {
                "CONFIG_PATHS": "!replace:sec -> forwarding.secret\n",
                "CONFIG_sec": "secretvalue",
            }
        )
        assert result[0][0] == DirSigil.REPLACE

    def test_delete_sigil_no_content_needed(self) -> None:
        result = _collect_config_overrides(
            {
                "CONFIG_PATHS": "!delete:dead -> old.yml\n",
                # no CONFIG_dead in env
            }
        )
        assert len(result) == 1
        sigil, path, content = result[0]
        assert sigil == DirSigil.DELETE
        assert path == "old.yml"
        assert content == ""

    def test_preserves_order(self) -> None:
        result = _collect_config_overrides(
            {
                "CONFIG_PATHS": "a -> a.yml\nb -> b.yml\nc -> c.yml\n",
                "CONFIG_a": "a",
                "CONFIG_b": "b",
                "CONFIG_c": "c",
            }
        )
        assert [path for _, path, _ in result] == ["a.yml", "b.yml", "c.yml"]

    def test_malformed_line_ignored(self) -> None:
        result = _collect_config_overrides(
            {
                "CONFIG_PATHS": "this-has-no-arrow\nvalid -> path.yml\n",
                "CONFIG_valid": "content",
            }
        )
        assert len(result) == 1

    def test_empty_config_paths(self) -> None:
        assert _collect_config_overrides({}) == []
        assert _collect_config_overrides({"CONFIG_PATHS": ""}) == []
        assert _collect_config_overrides({"CONFIG_PATHS": "   \n  \n"}) == []
