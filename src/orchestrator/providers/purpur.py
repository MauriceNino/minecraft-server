from __future__ import annotations

from typing import TypedDict, cast

import httpx

from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

API_BASE = "https://api.purpurmc.org/v2/purpur"


class PurpurProvider(AbstractPlatformProvider):
    project = "purpur"

    async def _get(self, client: httpx.AsyncClient, path: str = "") -> object:
        resp = await client.get(f"{API_BASE}{path}")
        resp.raise_for_status()
        return resp.json()

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        # Purpur has no release channels, so "experimental" is the same as "latest"
        if version in ("latest", "experimental"):
            version = cast(PurpurProject, await self._get(client))["metadata"]["current"]

        if build in ("latest", "experimental"):
            build = cast(PurpurVersion, await self._get(client, f"/{version}"))["builds"]["latest"]

        build_data = cast(PurpurBuild, await self._get(client, f"/{version}/{build}"))

        return ResolvedVersion(
            project=self.project,
            version=version,
            build=build,
            download_url=f"{API_BASE}/{version}/{build}/download",
            filename=f"purpur-{version}-{build}.jar",
            md5=build_data.get("md5"),
        )


class PurpurMetadata(TypedDict):
    current: str


class PurpurProject(TypedDict):
    project: str
    metadata: PurpurMetadata
    versions: list[str]


class PurpurBuilds(TypedDict):
    latest: str
    all: list[str]


class PurpurVersion(TypedDict):
    project: str
    version: str
    builds: PurpurBuilds


class PurpurBuild(TypedDict):
    project: str
    version: str
    build: str
    md5: str
