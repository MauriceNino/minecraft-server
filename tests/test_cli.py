from __future__ import annotations

import pytest

from orchestrator.cli import _collect_config_overrides, load_config
from orchestrator.constants import BUNGEE_RCON_URL, PlatformType
from orchestrator.http import ApiTokens
from orchestrator.sigils import DirSigil


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

    def test_unknown_plugin_provider(self) -> None:
        with pytest.raises(SystemExit, match="Unknown plugin provider"):
            load_config(environ={"PLUGINS": "foo:bar@latest"})

    @pytest.mark.parametrize("port", ["abc", "0", "70000"])
    def test_invalid_rcon_port(self, port: str) -> None:
        with pytest.raises(SystemExit, match="Invalid RCON_PORT"):
            load_config(environ={"RCON_PORT": port})

    @pytest.mark.parametrize("memory", ["2G", "1536M", "512m", "4096"])
    def test_valid_memory(self, memory: str) -> None:
        assert load_config(environ={"MEMORY": memory}).memory == memory

    @pytest.mark.parametrize("memory", ["2GB", "1.5G", "-1G", ""])
    def test_invalid_memory(self, memory: str) -> None:
        with pytest.raises(SystemExit, match="Invalid MEMORY"):
            load_config(environ={"MEMORY": memory})

    def test_empty_rcon_password_is_generated(self) -> None:
        assert load_config(environ={"RCON_PASSWORD": ""}).rcon_password

    def test_plugins_multiline(self) -> None:
        config = load_config(environ={"PLUGINS": "modrinth:luckperms@latest\nhangar:libertybans@latest\n"})
        assert config.plugin_specs[0].identifier == "luckperms"
        assert config.plugin_specs[1].identifier == "libertybans"

    def test_applied_templates(self) -> None:
        config = load_config(environ={"APPLIED_TEMPLATES": "all\nbackends\n"})
        assert config.applied_templates == ["all", "backends"]

    def test_rcon_disabled(self) -> None:
        config = load_config(environ={"RCON_ENABLED": "false"})
        assert config.rcon_enabled is False

    def test_jvm_flags(self) -> None:
        config = load_config(environ={"JVM_FLAGS": "-XX:+UseG1GC -Dfoo=bar"})
        assert config.jvm_flags == ["-XX:+UseG1GC", "-Dfoo=bar"]

    def test_custom_requires_custom_jar(self) -> None:
        with pytest.raises(SystemExit, match="CUSTOM_JAR"):
            load_config(environ={"TYPE": "CUSTOM"})

    def test_custom_jar_is_the_build(self) -> None:
        config = load_config(environ={"TYPE": "CUSTOM", "CUSTOM_JAR": " /jars/server.jar ", "BUILD": "5"})
        assert config.build == "/jars/server.jar"

    @pytest.mark.parametrize("platform", ["WATERFALL", "BUNGEECORD"])
    def test_bungee_proxies_get_the_rcon_bridge(self, platform: str) -> None:
        config = load_config(environ={"TYPE": platform})
        assert [s.identifier for s in config.plugin_specs] == [BUNGEE_RCON_URL]
        assert "-XX:MaxInlineLevel=15" in config.jvm_flags

    def test_jvm_extra_flags_are_appended_to_defaults(self) -> None:
        config = load_config(environ={"JVM_EXTRA_FLAGS": "-Dfoo=bar -Dbaz=1"})
        assert "-XX:+UseG1GC" in config.jvm_flags
        assert config.jvm_flags[-2:] == ["-Dfoo=bar", "-Dbaz=1"]

    def test_jvm_extra_flags_are_appended_to_jvm_flags(self) -> None:
        config = load_config(environ={"JVM_FLAGS": "-XX:+UseZGC", "JVM_EXTRA_FLAGS": "-Dfoo=bar"})
        assert config.jvm_flags == ["-XX:+UseZGC", "-Dfoo=bar"]

    def test_small_heap_uses_default_aikar_flags(self) -> None:
        flags = load_config(environ={"MEMORY": "8G"}).jvm_flags
        assert "-XX:G1HeapRegionSize=8M" in flags
        assert "-XX:G1NewSizePercent=30" in flags

    @pytest.mark.parametrize("memory", ["12G", "16384M", "1T"])
    def test_large_heap_uses_large_aikar_flags(self, memory: str) -> None:
        flags = load_config(environ={"MEMORY": memory}).jvm_flags
        assert "-XX:G1HeapRegionSize=16M" in flags
        assert "-XX:G1NewSizePercent=40" in flags
        assert "-XX:G1MaxNewSizePercent=50" in flags
        assert "-XX:G1ReservePercent=15" in flags
        assert "-XX:InitiatingHeapOccupancyPercent=20" in flags
        assert "-XX:G1HeapRegionSize=8M" not in flags

    def test_large_heap_does_not_change_proxy_flags(self) -> None:
        flags = load_config(environ={"TYPE": "VELOCITY", "MEMORY": "16G"}).jvm_flags
        assert "-XX:G1HeapRegionSize=4M" in flags

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

    def test_api_tokens(self) -> None:
        assert load_config(environ={}).api_tokens == ApiTokens()
        config = load_config(environ={"GITHUB_TOKEN": " ghp_x ", "CURSEFORGE_API_KEY": "cf"})
        assert config.api_tokens == ApiTokens(github="ghp_x", curseforge="cf")


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
