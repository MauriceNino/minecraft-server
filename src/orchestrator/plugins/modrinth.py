from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypedDict, cast

import httpx

from orchestrator.constants import MODRINTH_PLATFORM_TAGS, PROXY_PLATFORMS, USER_AGENT, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

API_BASE = "https://api.modrinth.com/v2"


class ModrinthProvider(AbstractPluginProvider):
    async def _get_plugin_info(self, spec: PluginSpec, client: httpx.AsyncClient) -> ModrinthProjectDict:
        resp = await client.get(
            f"{API_BASE}/project/{spec.identifier}",
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(ModrinthProjectDict, resp.json())

    async def _get_plugin_versions(self, spec: PluginSpec, client: httpx.AsyncClient) -> ModrinthVersionList:
        resp = await client.get(
            f"{API_BASE}/project/{spec.identifier}/version",
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(ModrinthVersionList, resp.json())

    async def _get_plugin_version(
        self, spec: PluginSpec, client: httpx.AsyncClient, version: str, loaders: list[str]
    ) -> ModrinthVersionDict:
        # We need to find the version that matches the spec.version and the loaders so
        # we cant simply use the direct /version/{version} endpoint
        versions = await self._get_plugin_versions(spec, client)
        possible_matches = [
            v
            for v in versions
            if v.get("version_number") == version and any(loader in v.get("loaders", []) for loader in loaders)
        ]

        if len(possible_matches) == 0:
            raise RuntimeError(f"No '{spec.version}' Modrinth versions found for {spec.identifier}")

        for loader in loaders:
            for p_match in possible_matches:
                if loader in p_match.get("loaders", []):
                    return p_match

        raise RuntimeError(f"No '{spec.version}' Modrinth versions found for {spec.identifier}")

    async def _get_first_plugin_version_by_channel(
        self,
        spec: PluginSpec,
        client: httpx.AsyncClient,
        loaders: list[str],
        channel_names: list[str],
    ) -> ModrinthVersionDict:
        versions = await self._get_plugin_versions(spec, client)

        version_data = None
        for loader in loaders:
            version_data = next(
                (v for v in versions if v.get("version_type") in channel_names and loader in v.get("loaders", [])),
                None,
            )
            if version_data:
                break

        if not version_data:
            raise RuntimeError(f"No '{spec.version}' Modrinth versions found for {spec.identifier}")

        return version_data

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        loaders = MODRINTH_PLATFORM_TAGS.get(platform_type, [])
        project_info = await self._get_plugin_info(spec, client)

        # Make sure platform is supported
        if not spec.force and not any(loader in project_info.get("loaders", []) for loader in loaders):
            self._raise_platform_not_supported(spec, platform_type)

        # Iterate through versions to find one that matches the spec
        if spec.version in ("latest", "experimental"):
            channel_names = ["release"] if spec.version == "latest" else ["beta", "alpha"]
            version_data = await self._get_first_plugin_version_by_channel(spec, client, loaders, channel_names)

            if not version_data:
                raise RuntimeError(f"No {spec.version} Modrinth versions found for {spec.identifier}")

        # Just load the specific version
        else:
            version_data = await self._get_plugin_version(spec, client, spec.version, loaders)

        if (
            not spec.force
            and platform_type not in PROXY_PLATFORMS
            and mc_version not in version_data.get("game_versions", [])
        ):
            self._raise_version_not_supported(spec, mc_version)

        version_file = version_data["files"][0]

        return ResolvedPlugin(
            spec=spec,
            display_name=project_info["title"],
            version=version_data["version_number"],
            download_url=version_file["url"],
            filename=version_file["filename"],
            sha512=version_file["hashes"]["sha512"],
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
            sha = hashlib.sha512()
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    sha.update(chunk)

        if resolved.sha512 and sha.hexdigest() != resolved.sha512:
            target.unlink()
            raise RuntimeError(f"SHA-512 mismatch for {resolved.filename}")

        return target


class LicenseDict(TypedDict):
    id: str
    name: str
    url: str | None


class DonationUrlDict(TypedDict):
    id: str
    platform: str
    url: str


class GalleryEntryDict(TypedDict):
    url: str
    featured: bool
    title: str | None
    description: str | None
    created: str


class ModrinthProjectDict(TypedDict):
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
    license: LicenseDict
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
    donation_urls: list[DonationUrlDict]
    gallery: list[GalleryEntryDict]
    color: int
    thread_id: str
    monetization_status: str


class HashesDict(TypedDict):
    sha1: str
    sha512: str


class FileDict(TypedDict):
    id: str
    hashes: HashesDict
    url: str
    filename: str
    primary: bool
    size: int
    file_type: str | None


class DependencyDict(TypedDict):
    version_id: str | None
    project_id: str
    file_name: str | None
    dependency_type: str


class ModrinthVersionDict(TypedDict):
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
    files: list[FileDict]
    dependencies: list[DependencyDict]
    game_versions: list[str]
    loaders: list[str]


ModrinthVersionList = list[ModrinthVersionDict]
