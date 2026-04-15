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

    def _get_platform_types_str(self, platform_types: list[str]) -> str:
        # platform_types -> 'xxx', 'yyy' or 'zzz'
        quoted_platform_types = [f"'{platform_type}'" for platform_type in platform_types]
        if len(quoted_platform_types) > 1:
            platform_types_str = ", ".join(quoted_platform_types[:-1]) + " or " + quoted_platform_types[-1]
        else:
            platform_types_str = quoted_platform_types[0]

        return platform_types_str

    def _platform_not_supported(self, spec: PluginSpec, platform_types: list[str]) -> RuntimeError:
        return RuntimeError(
            f"Plugin {spec.identifier} does not support platform {self._get_platform_types_str(platform_types)}."
        )

    def _version_not_supported(self, spec: PluginSpec, mc_version: str) -> RuntimeError:
        return RuntimeError(
            f"Plugin {spec.identifier}, version '{spec.version}' does not support "
            f"platform version '{mc_version}' - use [info]@{spec.version}![/info] to force"
        )

    def _version_could_not_be_found(self, spec: PluginSpec) -> RuntimeError:
        return RuntimeError(
            f"Plugin {spec.identifier} does not have a version '{spec.version}'. Try using a different version."
        )

    def _version_could_not_be_found_for_platform(self, spec: PluginSpec, platform_types: list[str]) -> RuntimeError:
        platform_example = (
            "You could try to change the platform using "
            f"[info]{spec.provider}:{spec.identifier}[platform=AnotherPlatform]@{spec.identifier}[/info] "
            "and see if that has a different outcome. "
        )
        return RuntimeError(
            f"Plugin {spec.identifier} does not have a version '{spec.version}' compatible "
            f"with platform {self._get_platform_types_str(platform_types)}."
            f" {platform_example if spec.provider in ('modrinth', 'hangar') else ''}"
            " Otherwise, try using a different version."
        )
