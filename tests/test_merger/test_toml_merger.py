"""Tests for the TOML merger."""

from __future__ import annotations

from pathlib import Path

import tomlkit

from orchestrator.merger.toml_merger import merge_toml


class TestMergeToml:
    def test_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        merge_toml(target, 'motd = "Hello World"\npvp = false\n')

        result = tomlkit.loads(target.read_text())
        assert result == {"motd": "Hello World", "pvp": False}

    def test_merge_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        target.write_text('motd = "Old"\nlevel-name = "world"\n')

        merge_toml(target, 'motd = "New"\npvp = false\n')

        result = tomlkit.loads(target.read_text())
        assert result == {"motd": "New", "level-name": "world", "pvp": False}

    def test_replace_sigil_table(self, tmp_path: Path) -> None:
        # Users write bare sigil keys; _escape_sigils quotes them before parsing
        target = tmp_path / "config.toml"
        target.write_text('[servers]\nlobby = "localhost"\ngame = "localhost:25566"\n\n[other]\nkeep = "kept"\n')

        # bare table-header sigil: [!replace:servers]
        merge_toml(target, '[!replace:servers]\nlobby = "new-host:25565"\n')

        result = tomlkit.loads(target.read_text())
        assert result["servers"]["lobby"] == "new-host:25565"
        assert "game" not in result["servers"]
        assert result["other"]["keep"] == "kept"

    def test_replace_sigil_key(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        target.write_text('[servers]\nlobby = "localhost"\n')

        # bare inline sigil: !replace:lobby = "new-host"
        merge_toml(target, '[servers]\n!replace:lobby = "new-host"\n')

        result = tomlkit.loads(target.read_text())
        assert result["servers"]["lobby"] == "new-host"

    def test_delete_sigil_table(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        target.write_text("[servers]\nlobby = 'localhost'\n\n[other]\nkeep = true\n")

        # bare table-header sigil: [!delete:servers]
        # value under a deleted table doesn't matter; use a dummy key
        merge_toml(target, "[!delete:servers]\n_x = true\n")

        result = tomlkit.loads(target.read_text())
        assert "servers" not in result
        assert "other" in result

    def test_delete_sigil_key(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        target.write_text("[servers]\nlobby = 'localhost'\nkeep = true\n")

        # bare inline sigil: !delete:lobby = true
        merge_toml(target, "[servers]\n!delete:lobby = true\n")

        result = tomlkit.loads(target.read_text())
        assert "lobby" not in result["servers"]
        assert result["servers"]["keep"] is True

    def test_comments_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        target.write_text('# Top level\nmotd = "Old MOTD" # In line\n[section]\n# Section comment\npvp = true\n')

        merge_toml(target, 'motd = "New MOTD"\n')

        raw = target.read_text()
        assert "# Top level" in raw
        assert "# In line" in raw
        assert "# Section comment" in raw

        result = tomlkit.loads(raw)
        assert result["motd"] == "New MOTD"
        assert result["section"]["pvp"] is True

    def test_new_file_strips_sigils(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        merge_toml(target, '[!replace:servers]\nlobby = "localhost"\n')

        result = tomlkit.loads(target.read_text())
        assert "servers" in result
        assert "!replace:servers" not in result
