from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import httpx

from orchestrator.http import download_file


@dataclass(frozen=True, slots=True)
class ResolvedVersion:
    project: str
    version: str  # the Minecraft version, used for plugin compatibility checks
    build: str
    download_url: str
    filename: str
    sha256: str | None = None
    sha1: str | None = None
    md5: str | None = None


class AbstractPlatformProvider(ABC):
    @abstractmethod
    async def resolve_version(
        self,
        version: str,
        build: str,
        client: httpx.AsyncClient,
    ) -> ResolvedVersion:
        """Resolve *version* / *build* (may be `"latest"` or `"experimental"`) into a concrete download target."""

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        """Download the server executable into the *dest* directory and return the written path."""
        target = dest / resolved.filename
        checksums = {"sha256": resolved.sha256, "sha1": resolved.sha1, "md5": resolved.md5}
        await download_file(client, resolved.download_url, target, checksums)
        return target

    async def install_extras(self, runtime_dir: Path, client: httpx.AsyncClient) -> None:  # noqa: B027
        """Install additional files the platform needs, called after a new server executable was installed."""
