"""Tests for the YAML merger."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from orchestrator.merger.yaml_merger import merge_yaml

_yaml = YAML()


class TestMergeYaml:
    def test_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yml"
        merge_yaml(target, "motd: Hello World\npvp: false\n")

        result = _yaml.load(target.read_text())
        assert result == {"motd": "Hello World", "pvp": False}

    def test_merge_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yml"
        target.write_text("motd: Old\nlevel-name: world\n")

        merge_yaml(target, "motd: New\npvp: false\n")

        result = _yaml.load(target.read_text())
        assert result == {"motd": "New", "level-name": "world", "pvp": False}

    def test_replace_sigil(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yml"
        target.write_text("servers:\n  lobby: localhost\n  game: localhost:25566\nother: kept\n")

        # In YAML, sigil keys must be quoted to avoid tag interpretation
        merge_yaml(target, '"!replace:servers":\n  lobby: new-host:25565\n')

        result = _yaml.load(target.read_text())
        assert result["servers"] == {"lobby": "new-host:25565"}
        assert result["other"] == "kept"

    def test_delete_sigil(self, tmp_path: Path) -> None:
        target = tmp_path / "config.yml"
        target.write_text("servers:\n  lobby: localhost\nother: kept\n")
        merge_yaml(target, '"!delete:servers": ""\n')

        result = _yaml.load(target.read_text())
        assert "servers" not in result
        assert result["other"] == "kept"

    def test_comments_preserved_on_merge(self, tmp_path: Path) -> None:
        """Existing comments must survive a merge that only changes values."""
        target = tmp_path / "config.yml"
        target.write_text(
            "# Top-level comment\nmotd: Old MOTD\n# Section comment\npvp: true\nlevel-name: world  # inline comment\n"
        )

        merge_yaml(target, "motd: New MOTD\n")

        raw = target.read_text()
        # All comment tokens must still be present
        assert "# Top-level comment" in raw
        assert "# Section comment" in raw
        assert "# inline comment" in raw
        # Value updated
        result = _yaml.load(raw)
        assert result["motd"] == "New MOTD"
        # Untouched keys kept
        assert result["pvp"] is True
        assert result["level-name"] == "world"

    def test_comments_preserved_on_nested_merge(self, tmp_path: Path) -> None:
        """Comments inside nested mappings must survive a deep merge."""
        target = tmp_path / "config.yml"
        target.write_text("storage-method: h2\ndata:\n  # DB host\n  address: localhost\n  database: luckperms\n")

        merge_yaml(target, "data:\n  address: mariadb:3306\n")

        raw = target.read_text()
        assert "# DB host" in raw
        result = _yaml.load(raw)
        assert result["data"]["address"] == "mariadb:3306"
        assert result["data"]["database"] == "luckperms"

    def test_new_file_strips_sigils(self, tmp_path: Path) -> None:
        """When no existing file, sigil keys must be stripped before writing."""
        target = tmp_path / "config.yml"
        merge_yaml(target, '"!replace:servers":\n  lobby: localhost\n')

        result = _yaml.load(target.read_text())
        assert "servers" in result
        assert "!replace:servers" not in result
