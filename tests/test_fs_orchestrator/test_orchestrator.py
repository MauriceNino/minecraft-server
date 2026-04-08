"""Tests for the filesystem orchestrator."""

from __future__ import annotations

from pathlib import Path

import yaml

from orchestrator.fs_orchestrator import orchestrate_templates


class TestOrchestrateTemplates:
    def _make_template(self, templates_dir: Path, name: str, structure: dict[str, object]) -> None:
        """Create a template directory with the given file structure.

        structure keys are relative paths; values are file contents (str)
        or None for directories.
        """
        root = templates_dir / name
        for rel_path, content in structure.items():
            path = root / rel_path
            if content is None:
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(content))

    def test_simple_copy(self, tmp_path: Path) -> None:
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"

        self._make_template(
            templates,
            "base",
            {
                "server.properties": "motd=Hello\n",
                "plugins/": None,
            },
        )

        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "server.properties").write_text("")

        orchestrate_templates(templates, runtime, ["base"])

        assert (runtime / "server.properties").read_text() == "motd=Hello\n"
        assert (runtime / "plugins").is_dir()

    def test_replace_directory(self, tmp_path: Path) -> None:
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"

        # Pre-populate runtime
        (runtime / "worldedit").mkdir(parents=True)
        (runtime / "worldedit" / "old.txt").write_text("old")

        self._make_template(
            templates,
            "base",
            {
                "!replace:worldedit/config.yml": "new: true\n",
            },
        )

        orchestrate_templates(templates, runtime, ["base"])

        assert not (runtime / "worldedit" / "old.txt").exists()
        assert (runtime / "worldedit" / "config.yml").read_text() == "new: true\n"

    def test_merge_config_across_templates(self, tmp_path: Path) -> None:
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"

        self._make_template(
            templates,
            "all",
            {
                "config.yml": yaml.dump({"a": 1, "b": 2}),
            },
        )
        self._make_template(
            templates,
            "extra",
            {
                "config.yml": yaml.dump({"b": 3, "c": 4}),
            },
        )

        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "config.yml").write_text("")

        orchestrate_templates(templates, runtime, ["all", "extra"])

        result = yaml.safe_load((runtime / "config.yml").read_text())
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_ignore_skipped(self, tmp_path: Path) -> None:
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"

        self._make_template(
            templates,
            "base",
            {
                "keep.txt": "kept",
                "!ignore": "",  # should be skipped
            },
        )

        orchestrate_templates(templates, runtime, ["base"])

        # keep.txt was NOT pre-populated, so it should be skipped
        assert not (runtime / "keep.txt").exists()
        assert not (runtime / "!ignore").exists()

    def test_replace_then_merge_from_later_template(self, tmp_path: Path) -> None:
        """A !replace_ in template 1, then template 2 merges into the same dir."""
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"

        # Pre-populate
        wp = runtime / "plugins" / "worldedit"
        wp.mkdir(parents=True)
        (wp / "stale.txt").write_text("stale")

        # Template 1: replaces worldedit
        self._make_template(
            templates,
            "all",
            {
                "plugins/!replace:worldedit/base.yml": yaml.dump({"setting": "a"}),
            },
        )
        # Template 2 merges into worldedit (which was replaced by T1, but T1 didn't create extra.yml)
        # So extra.yml should be SKIPPED!
        self._make_template(
            templates,
            "backends",
            {
                "plugins/worldedit/extra.yml": yaml.dump({"extra": True}),
            },
        )

        orchestrate_templates(templates, runtime, ["all", "backends"])

        # stale.txt should be gone (replaced by template 1)
        assert not (runtime / "plugins" / "worldedit" / "stale.txt").exists()
        # base.yml from template 1 (copied via !replace_)
        assert (runtime / "plugins" / "worldedit" / "base.yml").exists()
        # extra.yml from template 2 was skipped because it didn't exist
        assert not (runtime / "plugins" / "worldedit" / "extra.yml").exists()

    # !force: sigil tests
    def test_force_creates_absent_file(self, tmp_path: Path) -> None:
        """!force: creates a file that does not yet exist in the runtime dir."""
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True)

        self._make_template(
            templates,
            "base",
            {
                "!force:new-config.yml": yaml.dump({"key": "value"}),
            },
        )

        orchestrate_templates(templates, runtime, ["base"])

        target = runtime / "new-config.yml"
        assert target.exists()
        assert yaml.safe_load(target.read_text()) == {"key": "value"}

    def test_force_merges_when_existing(self, tmp_path: Path) -> None:
        """!force: still deep-merges when the target already exists."""
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True)

        (runtime / "config.yml").write_text(yaml.dump({"a": 1, "b": 2}))

        self._make_template(
            templates,
            "base",
            {
                "!force:config.yml": yaml.dump({"b": 99, "c": 3}),
            },
        )

        orchestrate_templates(templates, runtime, ["base"])

        result = yaml.safe_load((runtime / "config.yml").read_text())
        assert result == {"a": 1, "b": 99, "c": 3}

    # !delete: sigil tests
    def test_delete_removes_existing_file(self, tmp_path: Path) -> None:
        """!delete: removes a file that exists in the runtime dir."""
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True)

        (runtime / "old-config.yml").write_text("old: true\n")

        self._make_template(
            templates,
            "base",
            {
                "!delete:old-config.yml": "",
            },
        )

        orchestrate_templates(templates, runtime, ["base"])

        assert not (runtime / "old-config.yml").exists()

    def test_delete_noop_when_absent(self, tmp_path: Path) -> None:
        """!delete: is a no-op when the target file doesn't exist."""
        templates = tmp_path / "templates"
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True)

        self._make_template(
            templates,
            "base",
            {
                "!delete:ghost.yml": "",
            },
        )

        # Should not raise
        orchestrate_templates(templates, runtime, ["base"])
        assert not (runtime / "ghost.yml").exists()
