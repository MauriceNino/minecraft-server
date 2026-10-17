from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from orchestrator.logging import console

if TYPE_CHECKING:
    from orchestrator.plugins.base import ResolvedPlugin

# Only bump for breaking changes. Older images refuse to start with a newer schema, while added
# fields need no bump because `_parse` ignores unknown keys.
SCHEMA_VERSION = 1


class NewerSchemaError(Exception):
    """The lockfile was written by a newer version with an incompatible format."""


@dataclass(slots=True)
class PluginLockEntry:
    display_name: str
    version: str
    sha256: str | None
    filename: str
    updated_at: str
    target_version: str | None  # the version spec (e.g. "latest") this entry was installed for
    etag: str | None = None
    last_modified: str | None = None


@dataclass(slots=True)
class ServerJarEntry:
    project: str
    version: str
    build: str
    sha256: str | None
    filename: str
    updated_at: str


@dataclass(slots=True)
class ServerLockfile:
    path: Path
    plugins: dict[str, PluginLockEntry]
    server: ServerJarEntry | None = None
    # ISO-8601 timestamp of the last complete, error-free plugin check
    plugins_checked_at: str | None = None

    @classmethod
    def load(cls, path: Path) -> ServerLockfile:
        if not path.exists():
            return cls(path=path, plugins={}, server=None)
        try:
            return cls._parse(path, json.loads(path.read_text(encoding="utf-8")))
        except NewerSchemaError as e:
            # Starting fresh would lose track of the installed server and plugins, so leave the file alone
            raise SystemExit(
                f"{path} was written by a newer version of this image ({e}). "
                "Use that version again, or delete the file to start fresh (everything is downloaded again)."
            ) from None
        except (ValueError, TypeError, AttributeError) as e:
            backup = path.with_name(f"{path.name}.corrupt-{datetime.now(UTC):%Y%m%d%H%M%S}")
            os.replace(path, backup)
            console.print(
                f"  [warning]⚠[/warning] Lockfile is unreadable ({e}), moved it to [label]{backup.name}[/label] "
                "and starting fresh. Plugins will be re-downloaded."
            )
            return cls(path=path, plugins={}, server=None)

    @classmethod
    def _parse(cls, path: Path, raw: dict) -> ServerLockfile:
        schema_version = raw.get("schema_version", 1)
        if schema_version > SCHEMA_VERSION:
            raise NewerSchemaError(f"lockfile schema {schema_version}, this image supports up to {SCHEMA_VERSION}")
        server_raw = raw.get("server")

        plugins: dict[str, PluginLockEntry] = {}
        for key, val in raw.get("plugins", {}).items():
            plugins[key] = PluginLockEntry(
                display_name=val.get("display_name", ""),
                version=val.get("version", "unknown"),
                sha256=val.get("sha256"),
                filename=val.get("filename", ""),
                updated_at=val.get("updated_at", ""),
                target_version=val.get("target_version"),
                etag=val.get("etag"),
                last_modified=val.get("last_modified"),
            )

        server: ServerJarEntry | None = None
        if server_raw:
            server = ServerJarEntry(
                project=server_raw.get("project", ""),
                version=server_raw.get("version", ""),
                build=str(server_raw.get("build", "")),
                sha256=server_raw.get("sha256"),
                filename=server_raw.get("filename", ""),
                updated_at=server_raw.get("updated_at", ""),
            )

        return cls(
            path=path,
            plugins=plugins,
            server=server,
            plugins_checked_at=raw.get("plugins_checked_at"),
        )

    def save(self) -> None:
        data: dict = {"schema_version": SCHEMA_VERSION, "plugins": {k: asdict(v) for k, v in self.plugins.items()}}
        if self.server is not None:
            data["server"] = asdict(self.server)
        if self.plugins_checked_at is not None:
            data["plugins_checked_at"] = self.plugins_checked_at

        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file first so a crash mid-write can't leave a truncated lockfile behind
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, self.path)

    def record_plugins_checked(self) -> None:
        self.plugins_checked_at = datetime.now(UTC).isoformat()

    def is_plugins_check_fresh(self, ttl_seconds: int) -> bool:
        if not self.plugins_checked_at:
            return False
        try:
            checked = datetime.fromisoformat(self.plugins_checked_at)
        except ValueError:
            return False

        return datetime.now(UTC) - checked < timedelta(seconds=ttl_seconds)

    def get_plugin(self, key: str) -> PluginLockEntry | None:
        return self.plugins.get(key)

    def update_plugin(
        self,
        key: str,
        resolved: ResolvedPlugin,
        file_path: Path,
        target_version: str,
    ) -> None:
        self.plugins[key] = PluginLockEntry(
            display_name=resolved.display_name,
            version=resolved.version,
            sha256=_compute_sha256(file_path),
            filename=file_path.name,
            updated_at=datetime.now(UTC).isoformat(),
            target_version=target_version,
            etag=resolved.etag,
            last_modified=resolved.last_modified,
        )

    def update_server(
        self,
        project: str,
        version: str,
        build: str,
        file_path: Path,
    ) -> None:
        self.server = ServerJarEntry(
            project=project,
            version=version,
            build=build,
            sha256=_compute_sha256(file_path),
            filename=file_path.name,
            updated_at=datetime.now(UTC).isoformat(),
        )

    def needs_server_update(self, project: str, version: str, build: str) -> bool:
        if self.server is None:
            return True
        return (self.server.project, self.server.version, self.server.build) != (project, version, build)


def file_matches(path: Path, sha256: str | None) -> bool:
    """Whether *path* is a file and, if a checksum is known, has that checksum."""
    if not path.is_file():
        return False
    return sha256 is None or _compute_sha256(path) == sha256


def _compute_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def make_lock_key(spec_provider: str, spec_identifier: str) -> str:
    return f"{spec_provider}:{spec_identifier}"
