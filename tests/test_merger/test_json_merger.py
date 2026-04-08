"""Tests for the JSON merger."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.merger.json_merger import deep_merge, merge_json


class TestMergeJson:
    def test_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        merge_json(target, json.dumps({"motd": "Hello World", "pvp": False}))

        result = json.loads(target.read_text())
        assert result == {"motd": "Hello World", "pvp": False}

    def test_merge_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"motd": "Old", "level": "world"}))

        merge_json(target, json.dumps({"motd": "New", "pvp": False}))

        result = json.loads(target.read_text())
        assert result == {"motd": "New", "level": "world", "pvp": False}

    def test_replace_sigil(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"servers": {"lobby": "localhost", "game": "localhost:25566"}, "other": "kept"}))

        merge_json(target, json.dumps({"!replace:servers": {"lobby": "new-host:25565"}}))

        result = json.loads(target.read_text())
        assert result["servers"] == {"lobby": "new-host:25565"}
        assert result["other"] == "kept"

    def test_delete_sigil(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"servers": "something", "other": "kept"}))

        merge_json(target, json.dumps({"!delete:servers": None}))

        result = json.loads(target.read_text())
        assert "servers" not in result
        assert result["other"] == "kept"

    def test_new_file_strips_sigils(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        merge_json(target, json.dumps({"!replace:servers": {"lobby": "localhost"}, "!delete:should_be_ignored": None}))

        result = json.loads(target.read_text())
        assert "servers" in result
        assert "!replace:servers" not in result
        assert "should_be_ignored" not in result


class TestDeepMerge:
    def test_simple_merge(self) -> None:
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        assert deep_merge(base, overlay) == {"a": 1, "b": 3, "c": 4}

    def test_recursive_merge(self) -> None:
        base = {"top": {"a": 1, "b": 2}}
        overlay = {"top": {"b": 3, "c": 4}}
        assert deep_merge(base, overlay) == {"top": {"a": 1, "b": 3, "c": 4}}

    def test_replace_sigil(self) -> None:
        base = {"servers": {"lobby": "localhost", "game": "localhost:25566"}}
        overlay = {"!replace:servers": {"lobby": "new-host:25565"}}
        result = deep_merge(base, overlay)
        # The entire servers dict should be replaced
        assert result == {"servers": {"lobby": "new-host:25565"}}

    def test_replace_scalar(self) -> None:
        base = {"forwarding-mode": "none"}
        overlay = {"!replace:forwarding-mode": "modern"}
        result = deep_merge(base, overlay)
        assert result == {"forwarding-mode": "modern"}

    def test_delete_sigil(self) -> None:
        base = {"servers": "lobbby", "keep": "this"}
        overlay = {"!delete:servers": True}  # value shouldn't matter
        result = deep_merge(base, overlay)
        assert result == {"keep": "this"}

    def test_no_mutation(self) -> None:
        base = {"a": {"b": 1}}
        overlay = {"a": {"c": 2}}
        result = deep_merge(base, overlay)
        assert result["a"] == {"b": 1, "c": 2}
        assert base["a"] == {"b": 1}  # base not mutated
