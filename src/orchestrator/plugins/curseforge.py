from __future__ import annotations

import os
from typing import Any, TypedDict, cast

import httpx

from orchestrator.constants import BUKKIT_BASED_PLATFORMS, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

API_BASE = "https://api.curseforge.com/v1"
MINECRAFT_GAME_ID = 432
RELEASE_TYPE_RELEASE = 1  # 2 = beta, 3 = alpha
HASH_ALGO_SHA1 = 1
PAGE_SIZE = 50  # maximum allowed by the API
MAX_PAGES = 20


class CurseForgeProvider(AbstractPluginProvider):
    @staticmethod
    def _headers() -> dict[str, str]:
        key = os.environ.get("CURSEFORGE_API_KEY")
        if not key:
            raise RuntimeError(
                "CurseForge API key is missing. Plugins from CurseForge require a valid API key. "
                "Please set the [info]CURSEFORGE_API_KEY[/info] environment variable. "
                "You can obtain one at [url]https://console.curseforge.com/[/url]"
            )
        return {"x-api-key": key}

    async def _get_json(self, client: httpx.AsyncClient, path: str, **params: str | int) -> dict:
        resp = await client.get(f"{API_BASE}{path}", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _get(self, client: httpx.AsyncClient, path: str, **params: str | int) -> object:
        return (await self._get_json(client, path, **params))["data"]

    async def _get_files(self, client: httpx.AsyncClient, mod_id: int, mc_version: str | None) -> list[CurseForgeFile]:
        """All files of a mod, optionally only those for *mc_version*."""
        params: dict[str, str | int] = {"pageSize": PAGE_SIZE}
        if mc_version:
            params["gameVersion"] = mc_version

        files: list[CurseForgeFile] = []
        for page in range(MAX_PAGES):
            body = await self._get_json(client, f"/mods/{mod_id}/files", index=page * PAGE_SIZE, **params)
            files.extend(body["data"])
            if len(files) >= body["pagination"]["totalCount"] or not body["data"]:
                break
        return files

    async def _get_mod(self, spec: PluginSpec, client: httpx.AsyncClient) -> CurseForgeMod:
        if spec.identifier.isdigit():
            return cast(CurseForgeMod, await self._get(client, f"/mods/{spec.identifier}"))

        results = cast(
            list[CurseForgeMod],
            await self._get(client, "/mods/search", gameId=MINECRAFT_GAME_ID, slug=spec.identifier),
        )
        if not results:
            raise RuntimeError(f"CurseForge project not found for slug: {spec.identifier}")
        return results[0]

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        if not spec.force and platform_type not in BUKKIT_BASED_PLATFORMS:
            raise self._platform_not_supported(spec, [platform_type])

        is_alias = spec.version in ("latest", "experimental")
        if not is_alias and not spec.version.isdigit():
            raise ValueError(
                f"Invalid CurseForge version '{spec.version}'. "
                "Specific versions must be numeric File IDs. "
                "Example: curseforge:chunky-pregenerator@408295"
            )

        mod = await self._get_mod(spec, client)

        if is_alias:
            files = await self._get_files(client, mod["id"], None if spec.force else mc_version)
            candidates = [
                f
                for f in files
                if (spec.force or mc_version in f["gameVersions"])
                and (spec.version == "experimental" or f["releaseType"] == RELEASE_TYPE_RELEASE)
            ]
            # The API doesn't guarantee an order, ISO-8601 dates sort chronologically
            target_file = max(candidates, key=lambda f: f["fileDate"], default=None)
            if target_file is None:
                raise RuntimeError(
                    f"No compatible CurseForge version found for {spec.identifier} "
                    f"(version: {spec.version}, mc_version: {mc_version})"
                )
        else:
            target_file = cast(CurseForgeFile, await self._get(client, f"/mods/{mod['id']}/files/{spec.version}"))
            if not spec.force and mc_version not in target_file["gameVersions"]:
                raise self._version_not_supported(spec, mc_version)

        if not target_file["downloadUrl"]:
            raise RuntimeError(
                f"The author of {mod['name']} has disabled third-party downloads on CurseForge. "
                "Download the JAR manually or use a different provider."
            )

        return ResolvedPlugin(
            display_name=mod["name"],
            version=target_file["displayName"],
            download_url=target_file["downloadUrl"],
            filename=target_file["fileName"],
            sha1=next((h["value"] for h in target_file["hashes"] if h["algo"] == HASH_ALGO_SHA1), None),
        )


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
    downloadUrl: str | None
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


class CurseForgeMod(TypedDict):
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
