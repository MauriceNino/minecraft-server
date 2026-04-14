from __future__ import annotations

from pathlib import Path
from typing import TypedDict, cast

import httpx

from orchestrator.constants import USER_AGENT, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin
from orchestrator.semver import is_same_semver

API_BASE = "https://api.spiget.org/v2"


class SpigetProvider(AbstractPluginProvider):
    async def _get_plugin_info(self, client: httpx.AsyncClient, resource_id: str) -> SpigotResource:
        resp = await client.get(
            f"{API_BASE}/resources/{resource_id}",
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(SpigotResource, resp.json())

    async def _validate_external_download(self, client: httpx.AsyncClient, spec: PluginSpec, download_url: str) -> None:
        # External resources often redirect to a website (e.g., GitHub, personal site)
        # rather than a direct JAR download. We check if it's a JAR to fail early.
        head_resp = await client.head(download_url, follow_redirects=True)
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
        resource_id = spec.identifier
        if "." in resource_id:
            try:
                # SpigotMC resource URLs end with .<id>
                int(resource_id.split(".")[-1])
                resource_id = resource_id.split(".")[-1]
            except ValueError:
                pass

        project_info = await self._get_plugin_info(client, resource_id)
        version = str(project_info["version"]["id"]) if spec.version in ("latest", "experimental") else spec.version

        if not any(version == str(v.get("id")) for v in project_info.get("versions", [])):
            raise RuntimeError(f"Version {version} not found for {spec.identifier}")

        if project_info.get("premium", False):
            raise RuntimeError(
                f"Plugin '{spec.identifier}' is premium and cannot be downloaded. "
                "Please download the JAR file manually and place it in the plugins folder."
            )

        if not spec.force and platform_type not in (PlatformType.PAPER, PlatformType.FOLIA):
            self._raise_platform_not_supported(spec, platform_type)

        if not spec.force and not any(is_same_semver(mc_version, v) for v in project_info["testedVersions"]):
            self._raise_version_not_supported(spec, mc_version)

        filename = f"{spec.identifier}-{version}.jar"
        download_url = f"{API_BASE}/resources/{resource_id}/download?version={version}"

        if project_info.get("external"):
            await self._validate_external_download(client, spec, download_url)

        return ResolvedPlugin(
            spec=spec,
            display_name=project_info["name"],
            version=version,
            download_url=download_url,
            filename=filename,
        )

    async def download(
        self,
        resolved: ResolvedPlugin,
        dest: Path,
        client: httpx.AsyncClient,
    ) -> Path:
        target = dest / resolved.filename
        async with client.stream("GET", resolved.download_url, follow_redirects=True) as resp:
            resp.raise_for_status()
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)

        return target


class FileInfo(TypedDict):
    type: str
    size: float
    sizeUnit: str
    url: str


class VersionReference(TypedDict):
    id: int
    uuid: str


class IdReference(TypedDict):
    id: int


class RatingInfo(TypedDict):
    count: int
    average: float


class IconInfo(TypedDict):
    url: str
    data: str
    info: str
    hash: str


class SpigotResource(TypedDict):
    external: bool
    file: FileInfo
    description: str
    likes: int
    testedVersions: list[str]
    versions: list[VersionReference]
    updates: list[IdReference]
    reviews: list[IdReference]
    links: dict[str, str]
    name: str
    tag: str
    version: VersionReference
    author: IdReference
    category: IdReference
    rating: RatingInfo
    icon: IconInfo
    releaseDate: int
    updateDate: int
    downloads: int
    premium: bool
    price: int | float
    sourceCodeLink: str
    donationLink: str
    existenceStatus: int
    id: int
