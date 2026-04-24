from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orchestrator.plugins.base import ResolvedPlugin


@dataclass(slots=True)
class PluginLockEntry:
    display_name: str
    version: str
    sha256: str | None
    filename: str
    updated_at: str
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
    # ISO-8601 timestamp of the last successful plugins check cycle
    plugins_checked_at: str | None = None

    @classmethod
    def load(cls, path: Path) -> ServerLockfile:
        if not path.exists():
            return cls(path=path, plugins={}, server=None)
        with path.open() as f:
            raw = json.load(f)
            server_raw = raw.get("server")

        plugins: dict[str, PluginLockEntry] = {}
        for key, val in raw.get("plugins", {}).items():
            plugins[key] = PluginLockEntry(
                display_name=val.get("display_name", ""),
                version=val.get("version", "unknown"),
                sha256=val.get("sha256"),
                filename=val.get("filename", ""),
                updated_at=val.get("updated_at", ""),
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
        data: dict = {"plugins": {k: asdict(v) for k, v in self.plugins.items()}}
        if self.server is not None:
            data["server"] = asdict(self.server)
        if self.plugins_checked_at is not None:
            data["plugins_checked_at"] = self.plugins_checked_at

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")

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
    ) -> None:
        sha256 = _compute_sha256(file_path)
        self.plugins[key] = PluginLockEntry(
            display_name=resolved.display_name,
            version=resolved.version,
            sha256=sha256,
            filename=resolved.filename,
            updated_at=datetime.now(UTC).isoformat(),
            etag=resolved.etag,
            last_modified=resolved.last_modified,
        )

    def update_server(
        self,
        project: str,
        version: str,
        build: str,
        filename: str,
        file_path: Path,
    ) -> None:
        sha256 = _compute_sha256(file_path)
        self.server = ServerJarEntry(
            project=project,
            version=version,
            build=build,
            sha256=sha256,
            filename=filename,
            updated_at=datetime.now(UTC).isoformat(),
        )

    def needs_plugin_update(self, key: str, resolved: ResolvedPlugin) -> bool:
        entry = self.get_plugin(key)
        if entry is None:
            return True

        if resolved.version != "url" and resolved.version != entry.version:
            return True

        if resolved.etag and resolved.etag != entry.etag:
            return True
        return bool(resolved.last_modified and resolved.last_modified != entry.last_modified)

    def needs_server_update(self, version: str, build: str) -> bool:
        if self.server is None:
            return True
        return self.server.version != version or self.server.build != build


def _compute_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def make_lock_key(spec_provider: str, spec_identifier: str) -> str:
    return f"{spec_provider}:{spec_identifier}"
