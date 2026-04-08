"""Tests for the merge engine (apply_config_overrides dispatch)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.fs_orchestrator.sigils import DirSigil
from orchestrator.merger.engine import apply_config_overrides


class TestApplyConfigOverrides:
    def test_none_sigil_merges_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "server.properties"
        target.write_text("motd=Old\ndifficulty=easy\n")

        apply_config_overrides(
            [(DirSigil.NONE, "server.properties", "motd=New\n")],
            tmp_path,
        )

        lines = target.read_text().splitlines()
        assert "motd=New" in lines
        assert "difficulty=easy" in lines

    def test_none_sigil_skips_absent(self, tmp_path: Path) -> None:
        apply_config_overrides(
            [(DirSigil.NONE, "missing.properties", "motd=Hi\n")],
            tmp_path,
        )
        assert not (tmp_path / "missing.properties").exists()

    def test_force_sigil_creates_absent(self, tmp_path: Path) -> None:
        apply_config_overrides(
            [(DirSigil.FORCE, "new.properties", "key=value\n")],
            tmp_path,
        )
        assert (tmp_path / "new.properties").read_text() == "key=value\n"

    def test_force_sigil_merges_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yml"
        target.write_text("a: 1\nb: 2\n")

        apply_config_overrides(
            [(DirSigil.FORCE, "config.yml", "b: 99\nc: 3\n")],
            tmp_path,
        )

        import yaml

        result = yaml.safe_load(target.read_text())
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_replace_sigil_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "forwarding.secret"
        target.write_text("oldsecret")

        apply_config_overrides(
            [(DirSigil.REPLACE, "forwarding.secret", "newsecret")],
            tmp_path,
        )

        assert target.read_text() == "newsecret"

    def test_replace_sigil_creates_absent(self, tmp_path: Path) -> None:
        apply_config_overrides(
            [(DirSigil.REPLACE, "brand-new.txt", "hello")],
            tmp_path,
        )
        assert (tmp_path / "brand-new.txt").read_text() == "hello"

    def test_delete_sigil_removes_file(self, tmp_path: Path) -> None:
        target = tmp_path / "old.yml"
        target.write_text("old: true\n")

        apply_config_overrides(
            [(DirSigil.DELETE, "old.yml", "")],
            tmp_path,
        )

        assert not target.exists()

    def test_delete_sigil_noop_when_absent(self, tmp_path: Path) -> None:
        # Should not raise
        apply_config_overrides(
            [(DirSigil.DELETE, "ghost.yml", "")],
            tmp_path,
        )

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        apply_config_overrides(
            [(DirSigil.REPLACE, "plugins/luckperms/config.yml", "server: proxy\n")],
            tmp_path,
        )
        assert (tmp_path / "plugins" / "luckperms" / "config.yml").read_text() == "server: proxy\n"

    def test_multiple_overrides_applied_in_order(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yml"
        target.write_text("a: 1\n")

        apply_config_overrides(
            [
                (DirSigil.NONE, "config.yml", "b: 2\n"),
                (DirSigil.NONE, "config.yml", "c: 3\n"),
            ],
            tmp_path,
        )

        import yaml

        result = yaml.safe_load(target.read_text())
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3
