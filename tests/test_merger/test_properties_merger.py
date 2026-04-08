"""Tests for the properties merger."""

from __future__ import annotations

from pathlib import Path

from orchestrator.merger.properties_merger import merge_properties


class TestMergeProperties:
    def test_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "server.properties"
        merge_properties(target, "motd=Hello World\npvp=false\n")

        result = target.read_text()
        assert "motd=Hello World" in result
        assert "pvp=false" in result

    def test_merge_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "server.properties"
        target.write_text("motd=Old\nlevel-name=world\n")

        merge_properties(target, "motd=New\npvp=false\n")

        result = target.read_text()
        assert "motd=New" in result
        assert "level-name=world" in result
        assert "pvp=false" in result

    def test_replace_sigil(self, tmp_path: Path) -> None:
        target = tmp_path / "server.properties"
        target.write_text("lobby=localhost\ngame=localhost:25566\nother=kept\n")

        merge_properties(target, "!replace:lobby=new-host:25565\n")

        result = target.read_text().splitlines()
        assert "lobby=new-host:25565" in result
        assert "other=kept" in result

    def test_delete_sigil(self, tmp_path: Path) -> None:
        target = tmp_path / "server.properties"
        target.write_text("lobby=localhost\nother=kept\n")

        merge_properties(target, "!delete:lobby=\n")

        result = target.read_text().splitlines()
        assert "lobby=localhost" not in result
        assert "other=kept" in result
        assert "!delete:lobby=" not in result
        assert "lobby=" not in result

    def test_new_file_strips_sigils(self, tmp_path: Path) -> None:
        target = tmp_path / "server.properties"
        merge_properties(target, "!replace:lobby=localhost\n!delete:old_cache=ignored\n")

        result = target.read_text().splitlines()
        assert "lobby=localhost" in result
        assert "!replace:lobby=localhost" not in result
        assert "old_cache=ignored" not in result
