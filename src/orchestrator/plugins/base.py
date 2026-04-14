from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from orchestrator.constants import PlatformType


@dataclass(frozen=True, slots=True)
class PluginSpec:
    provider: str  # e.g. "modrinth", "hangar", "url"
    identifier: str  # project slug / ID / URL
    version: str  # "latest", "5.4", etc.
    force: bool  # True if ``@latest!`` — bypass compatibility filters
    params: dict[str, str] = field(default_factory=dict)  # optional provider-specific args, e.g. {"regex": "..."}

    def param(self, key: str, default: str | None = None) -> str | None:
        """Convenience accessor for optional provider parameters."""
        return self.params.get(key, default)


@dataclass(frozen=True, slots=True)
class ResolvedPlugin:
    spec: PluginSpec
    display_name: str
    version: str
    download_url: str
    filename: str
    sha1: str | None = None
    sha256: str | None = None
    sha512: str | None = None
    etag: str | None = None
    last_modified: str | None = None


class AbstractPluginProvider(ABC):
    @abstractmethod
    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        """Resolve a plugin spec into a concrete download target."""

    @abstractmethod
    async def download(
        self,
        resolved: ResolvedPlugin,
        dest: Path,
        client: httpx.AsyncClient,
    ) -> Path:
        """Download the plugin JAR to *dest* and return the written path."""

    def _raise_platform_not_supported(self, spec: PluginSpec, platform_type: PlatformType) -> None:
        raise ValueError(f"Plugin {spec.identifier} does not support platform {platform_type.value}")

    def _raise_version_not_supported(self, spec: PluginSpec, mc_version: str) -> None:
        raise ValueError(
            f"Plugin {spec.identifier}, version {spec.version} does not support "
            f"platform version {mc_version} - use @{spec.version}! to force"
        )
