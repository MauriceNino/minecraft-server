from __future__ import annotations

from typing import TypedDict, cast

import httpx

from orchestrator.constants import BUKKIT_BASED_PLATFORMS, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin
from orchestrator.semver import is_same_semver

API_BASE = "https://api.spiget.org/v2"


def _resource_id(identifier: str) -> str:
    """Accept both `12345` and SpigotMC URL slugs like `supervanish-be-invisible.1331`."""
    _, _, suffix = identifier.rpartition(".")
    return suffix if suffix.isdigit() else identifier


class SpigetProvider(AbstractPluginProvider):
    async def _get_resource(self, client: httpx.AsyncClient, resource_id: str) -> SpigetResource:
        resp = await client.get(f"{API_BASE}/resources/{resource_id}")
        resp.raise_for_status()
        return cast(SpigetResource, resp.json())

    async def _validate_external_download(self, client: httpx.AsyncClient, spec: PluginSpec, download_url: str) -> None:
        # External resources often redirect to a website instead of a JAR, so fail early with a useful message
        head_resp = await client.head(download_url)
        head_resp.raise_for_status()

        content_type = head_resp.headers.get("Content-Type", "").lower()
        final_url = str(head_resp.url)
        is_jar = (
            final_url.split("?")[0].endswith(".jar")
            or "application/java-archive" in content_type
            or "application/octet-stream" in content_type
        )

        if "text/html" in content_type or not is_jar:
            raise RuntimeError(
                f"Plugin '{spec.identifier}' is hosted externally and the "
                "download URL resolves to a webpage instead of a JAR file. "
                f"Please download the JAR file manually and place it in the plugins folder: {final_url}"
            )

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        resource_id = _resource_id(spec.identifier)
        resource = await self._get_resource(client, resource_id)

        if resource.get("premium", False):
            raise RuntimeError(
                f"Plugin '{spec.identifier}' is premium and cannot be downloaded. "
                "Please download the JAR file manually and place it in the plugins folder."
            )

        # Spiget has no release channels, so "experimental" is the same as "latest"
        version = str(resource["version"]["id"]) if spec.version in ("latest", "experimental") else spec.version
        if not any(version == str(v["id"]) for v in resource.get("versions", [])):
            raise self._version_could_not_be_found(spec)

        if not spec.force and platform_type not in BUKKIT_BASED_PLATFORMS:
            raise self._platform_not_supported(spec, [platform_type])

        if self._checks_mc_version(spec, mc_version) and not any(
            is_same_semver(mc_version, v) for v in resource["testedVersions"]
        ):
            raise self._version_not_supported(spec, mc_version)

        download_url = f"{API_BASE}/resources/{resource_id}/download?version={version}"
        if resource.get("external"):
            await self._validate_external_download(client, spec, download_url)

        return ResolvedPlugin(
            display_name=resource["name"],
            version=version,
            download_url=download_url,
            filename=f"{spec.identifier}-{version}.jar",
        )


class SpigetFileInfo(TypedDict):
    type: str
    size: float
    sizeUnit: str
    url: str


class SpigetVersionReference(TypedDict):
    id: int
    uuid: str


class SpigetIdReference(TypedDict):
    id: int


class SpigetRating(TypedDict):
    count: int
    average: float


class SpigetIcon(TypedDict):
    url: str
    data: str
    info: str
    hash: str


class SpigetResource(TypedDict):
    external: bool
    file: SpigetFileInfo
    description: str
    likes: int
    testedVersions: list[str]
    versions: list[SpigetVersionReference]
    updates: list[SpigetIdReference]
    reviews: list[SpigetIdReference]
    links: dict[str, str]
    name: str
    tag: str
    version: SpigetVersionReference
    author: SpigetIdReference
    category: SpigetIdReference
    rating: SpigetRating
    icon: SpigetIcon
    releaseDate: int
    updateDate: int
    downloads: int
    premium: bool
    price: int | float
    sourceCodeLink: str
    donationLink: str
    existenceStatus: int
    id: int
