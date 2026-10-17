from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orchestrator.lockfile import SCHEMA_VERSION, ServerLockfile, file_matches


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "server-lock.json"
    path.write_text(content)
    return path


@pytest.mark.parametrize("content", ["{not json", "[]", '{"plugins": {"a": "b"}}'])
def test_corrupt_lockfile_is_moved_aside(tmp_path: Path, content: str) -> None:
    path = _write(tmp_path, content)

    lockfile = ServerLockfile.load(path)

    assert lockfile.plugins == {}
    assert lockfile.server is None
    assert not path.exists()
    backups = list(tmp_path.glob("server-lock.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == content


def test_newer_schema_stops_without_touching_the_file(tmp_path: Path) -> None:
    content = json.dumps({"schema_version": SCHEMA_VERSION + 1, "plugins": {}})
    path = _write(tmp_path, content)

    with pytest.raises(SystemExit, match="written by a newer version"):
        ServerLockfile.load(path)

    assert path.read_text() == content
    assert not list(tmp_path.glob("server-lock.json.corrupt-*"))


def test_unknown_fields_are_ignored(tmp_path: Path) -> None:
    entry = {"version": "1.0", "filename": "a.jar", "added_later": True}
    path = _write(tmp_path, json.dumps({"schema_version": SCHEMA_VERSION, "plugins": {"a": entry}, "new": 1}))

    assert ServerLockfile.load(path).plugins["a"].filename == "a.jar"


def test_save_writes_schema_version(tmp_path: Path) -> None:
    lockfile = ServerLockfile.load(tmp_path / "server-lock.json")
    lockfile.save()

    assert json.loads((tmp_path / "server-lock.json").read_text())["schema_version"] == SCHEMA_VERSION
    assert ServerLockfile.load(tmp_path / "server-lock.json").plugins == {}


def test_file_matches(tmp_path: Path) -> None:
    jar = tmp_path / "a.jar"
    jar.write_bytes(b"data")
    sha = hashlib.sha256(b"data").hexdigest()

    assert file_matches(jar, sha)
    assert file_matches(jar, None)
    assert not file_matches(jar, "0" * 64)
    assert not file_matches(tmp_path / "missing.jar", sha)
