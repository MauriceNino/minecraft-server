from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from orchestrator.constants import PlatformType, PluginProviderType
from orchestrator.http import download_file, safe_filename


@dataclass(frozen=True, slots=True)
class PluginSpec:
    """A single line of the PLUGINS variable, e.g. `github:owner/repo[regex=...]@1.2.3!`."""

    provider: PluginProviderType
    identifier: str  # project slug / ID / URL
    version: str  # "latest", "experimental" or a provider-specific version
    force: bool  # trailing `!`: skip compatibility checks
    params: dict[str, str] = field(default_factory=dict)

    def param(self, key: str, default: str | None = None) -> str | None:
        return self.params.get(key, default)


@dataclass(frozen=True, slots=True)
class ResolvedPlugin:
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

    async def download(self, resolved: ResolvedPlugin, dest: Path, client: httpx.AsyncClient) -> Path:
        """Download the plugin JAR into the *dest* directory and return the written path."""
        target = dest / safe_filename(resolved.filename)
        checksums = {"sha1": resolved.sha1, "sha256": resolved.sha256, "sha512": resolved.sha512}
        await download_file(client, resolved.download_url, target, checksums)
        return target

    @staticmethod
    def _join_platforms(platform_types: list[str]) -> str:
        quoted = [f"'{p}'" for p in platform_types]
        if len(quoted) > 1:
            return ", ".join(quoted[:-1]) + " or " + quoted[-1]
        return quoted[0] if quoted else "''"

    def _platform_not_supported(self, spec: PluginSpec, platform_types: list[str]) -> RuntimeError:
        return RuntimeError(
            f"Plugin {spec.identifier} does not support platform {self._join_platforms(platform_types)}."
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
        hint = ""
        if spec.provider in (PluginProviderType.MODRINTH, PluginProviderType.HANGAR):
            hint = (
                " You could try to change the platform using "
                f"[info]{spec.provider}:{spec.identifier}\\[platform=AnotherPlatform]@{spec.version}[/info] "
                "and see if that has a different outcome."
            )
        return RuntimeError(
            f"Plugin {spec.identifier} does not have a version '{spec.version}' compatible "
            f"with platform {self._join_platforms(platform_types)}.{hint} Otherwise, try using a different version."
        )
