from __future__ import annotations

from typing import TypedDict, cast

import httpx

from orchestrator.constants import MODRINTH_PLATFORM_TAGS, PROXY_PLATFORMS, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

API_BASE = "https://api.modrinth.com/v2"


class ModrinthProvider(AbstractPluginProvider):
    async def _get_project(self, spec: PluginSpec, client: httpx.AsyncClient) -> ModrinthProject:
        resp = await client.get(f"{API_BASE}/project/{spec.identifier}")
        resp.raise_for_status()
        return cast(ModrinthProject, resp.json())

    async def _get_versions(self, spec: PluginSpec, client: httpx.AsyncClient) -> list[ModrinthVersion]:
        # Newest first
        resp = await client.get(f"{API_BASE}/project/{spec.identifier}/version")
        resp.raise_for_status()
        return cast(list[ModrinthVersion], resp.json())

    @staticmethod
    def _pick_by_platform_preference(candidates: list[ModrinthVersion], platforms: list[str]) -> ModrinthVersion | None:
        for platform in platforms:
            for version in candidates:
                if platform in version["loaders"]:
                    return version
        return None

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        custom_platform = spec.param("platform")
        platforms = [custom_platform.lower()] if custom_platform else MODRINTH_PLATFORM_TAGS.get(platform_type, [])

        project = await self._get_project(spec, client)
        if not spec.force and not any(p in project["loaders"] for p in platforms):
            raise self._platform_not_supported(spec, platforms)

        check_mc_version = not spec.force and platform_type not in PROXY_PLATFORMS
        versions = await self._get_versions(spec, client)

        if spec.version in ("latest", "experimental"):
            channels = ["release"] if spec.version == "latest" else ["beta", "alpha"]
            in_channel = [v for v in versions if v["version_type"] in channels]
            if not self._pick_by_platform_preference(in_channel, platforms):
                raise self._version_could_not_be_found_for_platform(spec, platforms)

            if check_mc_version:
                in_channel = [v for v in in_channel if mc_version in v["game_versions"]]
            version = self._pick_by_platform_preference(in_channel, platforms)
            if version is None:
                raise self._version_not_supported(spec, mc_version)
        else:
            matching = [v for v in versions if spec.version in (v["version_number"], v["id"])]
            version = self._pick_by_platform_preference(matching, platforms)
            if version is None:
                raise self._version_could_not_be_found_for_platform(spec, platforms)
            if check_mc_version and mc_version not in version["game_versions"]:
                raise self._version_not_supported(spec, mc_version)

        file = next((f for f in version["files"] if f["primary"]), version["files"][0])
        return ResolvedPlugin(
            display_name=project["title"],
            version=version["version_number"],
            download_url=file["url"],
            filename=file["filename"],
            sha512=file["hashes"].get("sha512"),
        )


class ModrinthLicense(TypedDict):
    id: str
    name: str
    url: str | None


class ModrinthDonationUrl(TypedDict):
    id: str
    platform: str
    url: str


class ModrinthGalleryEntry(TypedDict):
    url: str
    featured: bool
    title: str | None
    description: str | None
    created: str


class ModrinthProject(TypedDict):
    id: str
    slug: str
    project_type: str
    team: str
    organization: str | None
    title: str
    description: str
    body: str
    body_url: str | None
    published: str
    updated: str
    approved: str
    queued: str | None
    status: str
    requested_status: str | None
    moderator_message: str | None
    license: ModrinthLicense
    client_side: str
    server_side: str
    game_versions: list[str]
    downloads: int
    followers: int
    categories: list[str]
    additional_categories: list[str]
    loaders: list[str]
    versions: list[str]
    icon_url: str
    issues_url: str
    source_url: str
    wiki_url: str
    discord_url: str
    donation_urls: list[ModrinthDonationUrl]
    gallery: list[ModrinthGalleryEntry]
    color: int
    thread_id: str
    monetization_status: str


class ModrinthHashes(TypedDict):
    sha1: str
    sha512: str


class ModrinthFile(TypedDict):
    id: str
    hashes: ModrinthHashes
    url: str
    filename: str
    primary: bool
    size: int
    file_type: str | None


class ModrinthDependency(TypedDict):
    version_id: str | None
    project_id: str
    file_name: str | None
    dependency_type: str


class ModrinthVersion(TypedDict):
    id: str
    project_id: str
    author_id: str
    featured: bool
    name: str
    version_number: str
    changelog: str
    changelog_url: str | None
    date_published: str
    downloads: int
    version_type: str
    status: str
    requested_status: str | None
    files: list[ModrinthFile]
    dependencies: list[ModrinthDependency]
    game_versions: list[str]
    loaders: list[str]
