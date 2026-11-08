from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict, cast

import httpx

from orchestrator.constants import HANGAR_PLATFORM_TAGS, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginDependency, PluginSpec, ResolvedPlugin
from orchestrator.semver import is_same_semver

API_BASE = "https://hangar.papermc.io/api/v1"
PAGE_SIZE = 25  # maximum allowed by the API, larger limits are lowered to it


class HangarProvider(AbstractPluginProvider):
    async def _get_project(self, spec: PluginSpec, client: httpx.AsyncClient) -> HangarProject:
        resp = await client.get(f"{API_BASE}/projects/{spec.identifier}")
        resp.raise_for_status()
        return cast(HangarProject, resp.json())

    async def _get_version(self, spec: PluginSpec, client: httpx.AsyncClient, hangar_platform: str) -> HangarVersion:
        resp = await client.get(f"{API_BASE}/projects/{spec.identifier}/versions/{spec.version}")
        if resp.status_code == 404:
            raise self._version_could_not_be_found_for_platform(spec, [hangar_platform])
        resp.raise_for_status()
        return cast(HangarVersion, resp.json())

    async def _find_newest_version(
        self,
        spec: PluginSpec,
        client: httpx.AsyncClient,
        hangar_platform: str,
        channels: list[str],
        predicate: Callable[[HangarVersion], bool],
    ) -> HangarVersion | None:
        """The newest version for *hangar_platform* in one of *channels* that matches *predicate*."""
        offset = 0
        while True:
            resp = await client.get(
                f"{API_BASE}/projects/{spec.identifier}/versions",
                params={"offset": offset, "limit": PAGE_SIZE, "platform": hangar_platform, "channel": channels},
            )
            resp.raise_for_status()
            page = cast(HangarVersionPage, resp.json())

            for version in page["result"]:
                if predicate(version):
                    return version

            offset += len(page["result"])
            if not page["result"] or offset >= page["pagination"]["count"]:
                return None

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        custom_platform = spec.param("platform")
        mapped_platform = custom_platform.upper() if custom_platform else HANGAR_PLATFORM_TAGS.get(platform_type)

        project = await self._get_project(spec, client)

        if not spec.force:
            if not mapped_platform:
                raise self._platform_not_supported(spec, [custom_platform or platform_type.value])
            if platform_type == PlatformType.FOLIA and "SUPPORTS_FOLIA" not in project["settings"]["tags"]:
                raise self._platform_not_supported(spec, [PlatformType.FOLIA.value])
            if not project["supportedPlatforms"].get(mapped_platform):
                raise self._platform_not_supported(spec, [mapped_platform])

        hangar_platform = mapped_platform or "PAPER"

        def supports_mc_version(version: HangarVersion) -> bool:
            supported = version.get("platformDependencies", {}).get(hangar_platform, [])
            return spec.force or any(is_same_semver(mc_version, v) for v in supported)

        if spec.version in ("latest", "experimental"):
            channels = ["Release"] if spec.version == "latest" else ["Beta", "Alpha", "Snapshot"]

            def matches(version: HangarVersion) -> bool:
                return (
                    version["channel"]["name"] in channels
                    and hangar_platform in version["downloads"]
                    and supports_mc_version(version)
                )

            version_data = await self._find_newest_version(spec, client, hangar_platform, channels, matches)
            if version_data is None:
                if spec.force:
                    raise self._version_could_not_be_found_for_platform(spec, [hangar_platform])
                raise self._version_not_supported(spec, mc_version)
        else:
            version_data = await self._get_version(spec, client, hangar_platform)
            if hangar_platform not in version_data["downloads"]:
                raise self._version_could_not_be_found_for_platform(spec, [hangar_platform])
            if not supports_mc_version(version_data):
                raise self._version_not_supported(spec, mc_version)

        download = version_data["downloads"][hangar_platform]
        file_info = download["fileInfo"]
        if file_info is None or not download["downloadUrl"]:
            external = download.get("externalUrl")
            raise RuntimeError(
                f"Plugin {spec.identifier} is hosted externally and cannot be downloaded automatically"
                + (f": {external}" if external else "")
            )

        return ResolvedPlugin(
            display_name=project["name"],
            version=version_data["name"],
            download_url=download["downloadUrl"],
            filename=file_info["name"],
            sha256=file_info["sha256Hash"],
            dependencies=tuple(
                PluginDependency(name=d["name"])
                for d in version_data.get("pluginDependencies", {}).get(hangar_platform, [])
                if d["required"]
            ),
        )


class HangarNamespace(TypedDict):
    owner: str
    slug: str


class HangarStats(TypedDict):
    views: int
    downloads: int
    recentViews: int
    recentDownloads: int
    stars: int
    watchers: int


class HangarUserActions(TypedDict):
    starred: bool
    watching: bool
    flagged: bool


class HangarLink(TypedDict):
    id: int
    name: str
    url: str


class HangarLinkGroup(TypedDict):
    id: int
    type: str
    title: str
    links: list[HangarLink]


class HangarLicense(TypedDict):
    name: str
    url: str
    type: str


class HangarDonation(TypedDict):
    subject: str
    enable: bool


class HangarProjectSettings(TypedDict):
    links: list[HangarLinkGroup]
    tags: list[str]
    license: HangarLicense
    keywords: list[str]
    sponsors: str
    donation: HangarDonation


class HangarProject(TypedDict):
    createdAt: str
    id: int
    name: str
    namespace: HangarNamespace
    stats: HangarStats
    category: str
    description: str
    lastUpdated: str
    visibility: str
    userActions: HangarUserActions
    settings: HangarProjectSettings
    supportedPlatforms: dict[str, list[str]]
    mainPageContent: str | None
    memberNames: list[str] | None
    avatarUrl: str


class HangarPagination(TypedDict):
    count: int
    limit: int
    offset: int


class HangarVersionStats(TypedDict):
    totalDownloads: int
    platformDownloads: dict[str, int]


class HangarChannel(TypedDict):
    createdAt: str
    name: str
    description: str
    color: str
    flags: list[str]


class HangarFileInfo(TypedDict):
    name: str
    sizeBytes: int
    sha256Hash: str


class HangarDownload(TypedDict):
    fileInfo: HangarFileInfo | None
    externalUrl: str | None
    downloadUrl: str | None


class HangarPluginDependency(TypedDict):
    name: str
    projectId: int | None
    required: bool
    externalUrl: str | None
    platform: str


class HangarVersion(TypedDict):
    createdAt: str
    id: int
    projectId: int
    name: str
    visibility: str
    description: str
    stats: HangarVersionStats
    author: str
    reviewState: str
    channel: HangarChannel
    pinnedStatus: str
    # Platform name (e.g. "PAPER") -> download info
    downloads: dict[str, HangarDownload]
    # Platform name -> dependencies
    pluginDependencies: dict[str, list[HangarPluginDependency]]
    # Platform name -> supported Minecraft versions, e.g. {"PAPER": ["1.21", "1.21.1"]}
    platformDependencies: dict[str, list[str]]
    platformDependenciesFormatted: dict[str, list[str]]
    memberNames: list[str]


class HangarVersionPage(TypedDict):
    pagination: HangarPagination
    result: list[HangarVersion]
