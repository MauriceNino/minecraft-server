from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True, slots=True)
class ResolvedVersion:
    project: str
    version: str
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
        """Resolve *version* / *build* (may be ``"latest"`` or ``"experimental"``) into a concrete download target."""

    @abstractmethod
    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        """Download the server JAR to *dest* and return the written path."""
