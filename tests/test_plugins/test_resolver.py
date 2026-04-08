"""Tests for plugin spec resolver."""

from __future__ import annotations

import pytest

from orchestrator.plugins.resolver import parse_plugin_lines, parse_plugin_spec


class TestParsePluginSpec:
    def test_modrinth_latest(self) -> None:
        spec = parse_plugin_spec("modrinth:luckperms@latest")
        assert spec.provider == "modrinth"
        assert spec.identifier == "luckperms"
        assert spec.version == "latest"
        assert spec.force is False

    def test_specific_version(self) -> None:
        spec = parse_plugin_spec("modrinth:luckperms@5.4.137")
        assert spec.version == "5.4.137"
        assert spec.force is False

    def test_hangar(self) -> None:
        spec = parse_plugin_spec("hangar:libertybans@latest")
        assert spec.provider == "hangar"
        assert spec.identifier == "libertybans"

    def test_spiget(self) -> None:
        spec = parse_plugin_spec("spiget:28140@latest")
        assert spec.provider == "spiget"
        assert spec.identifier == "28140"

    def test_spiget_with_slug(self) -> None:
        spec = parse_plugin_spec("spiget:supervanish-be-invisible.1331@latest")
        assert spec.provider == "spiget"
        assert spec.identifier == "supervanish-be-invisible.1331"

    def test_url(self) -> None:
        spec = parse_plugin_spec("url:https://example.com/plugin/latest/plugin.jar")
        assert spec.provider == "url"
        assert spec.identifier == "https://example.com/plugin/latest/plugin.jar"
        assert spec.version == "latest"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty"):
            parse_plugin_spec("")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            parse_plugin_spec("just-a-name")

    # Version alias normalisation
    def test_stable_alias_normalises_to_latest(self) -> None:
        spec = parse_plugin_spec("modrinth:luckperms@stable")
        assert spec.version == "latest"

    def test_experimental_alias_stays_experimental(self) -> None:
        spec = parse_plugin_spec("modrinth:luckperms@experimental")
        assert spec.version == "experimental"

    def test_beta_alias_normalises_to_experimental(self) -> None:
        spec = parse_plugin_spec("hangar:libertybans@beta")
        assert spec.version == "experimental"

    def test_beta_with_force_flag(self) -> None:
        spec = parse_plugin_spec("modrinth:luckperms@beta!")
        assert spec.version == "experimental"
        assert spec.force is True

    def test_explicit_version_unchanged(self) -> None:
        spec = parse_plugin_spec("modrinth:luckperms@5.4.137")
        assert spec.version == "5.4.137"


class TestParsePluginLines:
    def test_skips_blanks_and_comments(self) -> None:
        specs = parse_plugin_lines(
            [
                "modrinth:luckperms@latest",
                "",
                "# This is a comment",
                "hangar:libertybans@latest",
                "  ",
            ]
        )
        assert len(specs) == 2
        assert specs[0].provider == "modrinth"
        assert specs[1].provider == "hangar"
