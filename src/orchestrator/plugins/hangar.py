from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypedDict, cast

import httpx

from orchestrator.constants import PLATFORM_HANGAR_TAGS, USER_AGENT, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin
from orchestrator.semver import is_same_semver

API_BASE = "https://hangar.papermc.io/api/v1"


class HangarProvider(AbstractPluginProvider):
    async def _get_plugin_info(self, spec: PluginSpec, client: httpx.AsyncClient) -> HangarProjectResponse:
        resp = await client.get(
            f"{API_BASE}/projects/{spec.identifier}",
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(HangarProjectResponse, resp.json())

    async def _get_plugin_versions(
        self, spec: PluginSpec, client: httpx.AsyncClient, offset: int = 0, limit: int = 25
    ) -> HangarVersionResponse:
        resp = await client.get(
            f"{API_BASE}/projects/{spec.identifier}/versions",
            params={"offset": offset, "limit": limit},
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(HangarVersionResponse, resp.json())

    async def _get_plugin_version(self, spec: PluginSpec, client: httpx.AsyncClient, version: str) -> VersionDict:
        resp = await client.get(
            f"{API_BASE}/projects/{spec.identifier}/versions/{version}",
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(VersionDict, resp.json())

    async def _get_first_plugin_version_by_channel(
        self,
        spec: PluginSpec,
        client: httpx.AsyncClient,
        channel_names: list[str],
        offset: int = 0,
        limit: int = 25,
    ) -> VersionDict:
        versions = await self._get_plugin_versions(spec, client, offset=offset, limit=limit)

        version_data = next((v for v in versions["result"] if v.get("channel", {}).get("name") in channel_names), None)
        if not version_data:
            if versions["pagination"]["offset"] + versions["pagination"]["limit"] < versions["pagination"]["count"]:
                return await self._get_first_plugin_version_by_channel(
                    spec, client, channel_names, offset + limit, limit
                )
            else:
                raise RuntimeError(f"No {spec.version} Hangar versions found for {spec.identifier}")

        return version_data

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        hangar_platform = PLATFORM_HANGAR_TAGS.get(platform_type, "PAPER")
        project_info = await self._get_plugin_info(spec, client)

        # Make sure platform is supported
        if not spec.force:
            if not project_info["supportedPlatforms"].get(hangar_platform):
                self._raise_platform_not_supported(spec, platform_type)

            if platform_type == PlatformType.FOLIA and "SUPPORTS_FOLIA" not in project_info["settings"]["tags"]:
                self._raise_platform_not_supported(spec, platform_type)

        # Iterate through versions to find one that matches the spec
        if spec.version in ("latest", "experimental"):
            channel_names = ["Release"] if spec.version == "latest" else ["Beta", "Alpha", "Snapshot"]
            version_data = await self._get_first_plugin_version_by_channel(spec, client, channel_names)

            if not version_data:
                raise RuntimeError(f"No {spec.version} Hangar versions found for {spec.identifier}")

        # Just load the specific version
        else:
            version_data = await self._get_plugin_version(spec, client, spec.version)

        supported_platform_versions = version_data.get("platformDependencies", {}).get(hangar_platform, [])
        if not spec.force and not any(is_same_semver(mc_version, v) for v in supported_platform_versions):
            self._raise_version_not_supported(spec, mc_version)

        platform_dl = version_data["downloads"][hangar_platform]
        file_info = platform_dl["fileInfo"]

        if file_info is None:
            raise RuntimeError(f"No file info found for {spec.identifier} on {hangar_platform}")

        return ResolvedPlugin(
            spec=spec,
            display_name=spec.identifier,
            version=version_data["name"],
            download_url=str(platform_dl.get("downloadUrl") or ""),
            filename=file_info["name"],
            sha256=file_info["sha256Hash"],
        )

    async def download(
        self,
        resolved: ResolvedPlugin,
        dest: Path,
        client: httpx.AsyncClient,
    ) -> Path:
        target = dest / resolved.filename
        async with client.stream("GET", resolved.download_url) as resp:
            resp.raise_for_status()
            sha = hashlib.sha256()
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    sha.update(chunk)

        if resolved.sha256 and sha.hexdigest() != resolved.sha256:
            target.unlink()
            raise RuntimeError(f"SHA-256 mismatch for {resolved.filename}")

        return target


class NamespaceDict(TypedDict):
    owner: str
    slug: str


class StatsDict(TypedDict):
    views: int
    downloads: int
    recentViews: int
    recentDownloads: int
    stars: int
    watchers: int


class UserActionsDict(TypedDict):
    starred: bool
    watching: bool
    flagged: bool


class SubLinkDict(TypedDict):
    id: int
    name: str
    url: str


class LinkGroupDict(TypedDict):
    id: int
    type: str
    title: str
    links: list[SubLinkDict]


class LicenseDict(TypedDict):
    name: str
    url: str
    type: str


class DonationDict(TypedDict):
    subject: str
    enable: bool


class SettingsDict(TypedDict):
    links: list[LinkGroupDict]
    tags: list[str]
    license: LicenseDict
    keywords: list[str]
    sponsors: str
    donation: DonationDict


class HangarProjectResponse(TypedDict):
    createdAt: str
    id: int
    name: str
    namespace: NamespaceDict
    stats: StatsDict
    category: str
    description: str
    lastUpdated: str
    visibility: str
    userActions: UserActionsDict
    settings: SettingsDict
    supportedPlatforms: dict[str, list[str]]
    mainPageContent: str | None
    memberNames: list[str] | None
    avatarUrl: str


class PaginationDict(TypedDict):
    count: int
    limit: int
    offset: int


class VersionStatsDict(TypedDict):
    totalDownloads: int
    platformDownloads: dict[str, int]


class ChannelDict(TypedDict):
    createdAt: str
    name: str
    description: str
    color: str
    flags: list[str]


class FileInfoDto(TypedDict):
    name: str
    sizeBytes: int
    sha256Hash: str


class DownloadEntryDict(TypedDict):
    fileInfo: FileInfoDto | None
    externalUrl: str | None
    downloadUrl: str | None


class PluginDependencyDict(TypedDict):
    name: str
    projectId: int | None
    required: bool
    externalUrl: str | None
    platform: str


class VersionDict(TypedDict):
    createdAt: str
    id: int
    projectId: int
    name: str
    visibility: str
    description: str
    stats: VersionStatsDict
    author: str
    reviewState: str
    channel: ChannelDict
    pinnedStatus: str
    # Maps platform name (e.g., "PAPER") to its download info
    downloads: dict[str, DownloadEntryDict]
    # Maps platform name to a list of dependencies
    pluginDependencies: dict[str, list[PluginDependencyDict]]
    # Maps platform name to a list of supported versions (e.g., ["1.21"])
    platformDependencies: dict[str, list[str]]
    platformDependenciesFormatted: dict[str, list[str]]
    memberNames: list[str]


class HangarVersionResponse(TypedDict):
    pagination: PaginationDict
    result: list[VersionDict]
