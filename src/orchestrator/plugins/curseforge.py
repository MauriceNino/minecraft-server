from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, TypedDict, cast

import httpx

from orchestrator.constants import PLATFORM_LOADER_TAGS, USER_AGENT, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

API_BASE = "https://api.curseforge.com/v1"


class CurseForgeProvider(AbstractPluginProvider):
    def _get_api_key(self) -> str:
        key = os.environ.get("CURSEFORGE_API_KEY")
        if not key:
            raise RuntimeError(
                "CurseForge API key is missing. Plugins from CurseForge require a valid API key. "
                "Please set the [info]CURSEFORGE_API_KEY[/info] environment variable. "
                "You can obtain one at [url]https://console.curseforge.com/[/url]"
            )
        return key

    async def _get_mod_info(self, spec: PluginSpec, client: httpx.AsyncClient) -> CurseForgeModData:
        # If it's a numeric ID, we can fetch it directly
        if spec.identifier.isdigit():
            resp = await client.get(
                f"{API_BASE}/mods/{spec.identifier}",
                headers={"x-api-key": self._get_api_key(), "User-Agent": USER_AGENT},
            )
        else:
            # Otherwise, search by slug
            resp = await client.get(
                f"{API_BASE}/mods/search",
                params={"gameId": 432, "slug": spec.identifier},
                headers={"x-api-key": self._get_api_key(), "User-Agent": USER_AGENT},
            )

        resp.raise_for_status()
        data = resp.json()

        if "data" in data and isinstance(data["data"], list):
            if len(data["data"]) == 0:
                raise RuntimeError(f"CurseForge project not found for slug: {spec.identifier}")
            return cast(CurseForgeModData, data["data"][0])

        return cast(CurseForgeModData, data["data"])

    async def _get_mod_files(self, mod_id: int, client: httpx.AsyncClient) -> list[CurseForgeFile]:
        resp = await client.get(
            f"{API_BASE}/mods/{mod_id}/files",
            headers={"x-api-key": self._get_api_key(), "User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(list[CurseForgeFile], resp.json()["data"])

    async def _get_mod_file(self, mod_id: int, file_id: str, client: httpx.AsyncClient) -> CurseForgeFile:
        resp = await client.get(
            f"{API_BASE}/mods/{mod_id}/files/{file_id}",
            headers={"x-api-key": self._get_api_key(), "User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return cast(CurseForgeFile, resp.json()["data"])

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        # Platform enforcement (Bukkit servers only)
        if not spec.force and "bukkit" not in PLATFORM_LOADER_TAGS.get(platform_type, []):
            self._raise_platform_not_supported(spec, platform_type)

        is_alias = spec.version in ("latest", "experimental")
        if not is_alias and not spec.version.isdigit():
            raise ValueError(
                f"Invalid CurseForge version '{spec.version}'. "
                "Specific versions must be numeric File IDs. "
                "Example: curseforge:chunky-pregenerator@408295"
            )

        mod_info = await self._get_mod_info(spec, client)

        # Resolve the target file
        target_file = None

        if not is_alias:
            target_file = await self._get_mod_file(mod_info["id"], spec.version, client)

            if not spec.force and mc_version not in target_file["gameVersions"]:
                self._raise_version_not_supported(spec, mc_version)
        else:
            files = await self._get_mod_files(mod_info["id"], client)

            # Release types: 1=Release, 2=Beta, 3=Alpha
            allowed_types = [1] if spec.version == "latest" else [1, 2, 3]

            for file in files:
                if not spec.force and mc_version not in file["gameVersions"]:
                    continue

                if file["releaseType"] not in allowed_types:
                    continue

                target_file = file
                break

        if not target_file:
            raise RuntimeError(
                f"No compatible CurseForge version found for {spec.identifier} "
                f"(version: {spec.version}, mc_version: {mc_version})"
            )

        sha1 = next((h["value"] for h in target_file["hashes"] if h["algo"] == 1), None)

        return ResolvedPlugin(
            spec=spec,
            display_name=mod_info["name"],
            version=target_file["displayName"],
            download_url=target_file["downloadUrl"],
            filename=target_file["fileName"],
            sha1=sha1,
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
            sha = hashlib.sha1()  # noqa: S324
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    sha.update(chunk)

        if resolved.sha1 and sha.hexdigest() != resolved.sha1:
            target.unlink()
            raise RuntimeError(f"SHA-1 mismatch for {resolved.filename}")

        return target


class CurseForgeLinks(TypedDict):
    websiteUrl: str
    wikiUrl: str
    issuesUrl: str
    sourceUrl: str


class CurseForgeCategory(TypedDict):
    id: int
    gameId: int
    name: str
    slug: str
    url: str
    iconUrl: str
    dateModified: str
    isClass: bool
    classId: int
    parentCategoryId: int


class CurseForgeAuthor(TypedDict):
    id: int
    name: str
    url: str
    avatarUrl: str


class CurseForgeLogo(TypedDict):
    id: int
    modId: int
    title: str
    description: str
    thumbnailUrl: str
    url: str


class CurseForgeFileHash(TypedDict):
    value: str
    algo: int


class CurseForgeSortableGameVersion(TypedDict):
    gameVersionName: str
    gameVersionPadded: str
    gameVersion: str
    gameVersionReleaseDate: str
    gameVersionTypeId: int


class CurseForgeFileModule(TypedDict):
    name: str
    fingerprint: int


class CurseForgeFile(TypedDict):
    id: int
    gameId: int
    modId: int
    isAvailable: bool
    displayName: str
    fileName: str
    releaseType: int
    fileStatus: int
    hashes: list[CurseForgeFileHash]
    fileDate: str
    fileLength: int
    downloadCount: int
    fileSizeOnDisk: int
    downloadUrl: str
    gameVersions: list[str]
    sortableGameVersions: list[CurseForgeSortableGameVersion]
    dependencies: list[Any]
    alternateFileId: int
    isServerPack: bool
    fileFingerprint: int
    modules: list[CurseForgeFileModule]


class CurseForgeFileIndex(TypedDict):
    gameVersion: str
    fileId: int
    filename: str
    releaseType: int
    gameVersionTypeId: int


class CurseForgeModData(TypedDict):
    id: int
    gameId: int
    name: str
    slug: str
    links: CurseForgeLinks
    summary: str
    status: int
    downloadCount: int
    isFeatured: bool
    primaryCategoryId: int
    categories: list[CurseForgeCategory]
    classId: int
