from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from orchestrator.http import download_file

if TYPE_CHECKING:
    from orchestrator.lockfile import ServerLockfile


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
    project: str  # stored in the lockfile as `server.project`

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

    async def install_extras(  # noqa: B027
        self, runtime_dir: Path, client: httpx.AsyncClient, lockfile: ServerLockfile
    ) -> None:
        """Install or update additional files the platform needs, tracked in `lockfile.extras`.

        Called on every start once the server executable is in place.
        """
