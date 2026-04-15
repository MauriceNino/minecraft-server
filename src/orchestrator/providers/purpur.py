from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypedDict, cast

import httpx

from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

API_BASE = "https://api.purpurmc.org/v2/purpur"


class PurpurProvider(AbstractPlatformProvider):
    async def _resolve_latest_version(self, client: httpx.AsyncClient) -> str:
        resp = await client.get(API_BASE)
        resp.raise_for_status()
        data = cast(PurpurProject, resp.json())
        return data["metadata"]["current"]

    async def _resolve_latest_build(self, client: httpx.AsyncClient, version: str) -> str:
        resp = await client.get(f"{API_BASE}/{version}")
        resp.raise_for_status()
        data = cast(PurpurVersion, resp.json())
        return data["builds"]["latest"]

    async def _load_build_data(self, client: httpx.AsyncClient, version: str, build: str) -> PurpurBuild:
        resp = await client.get(f"{API_BASE}/{version}/{build}")
        resp.raise_for_status()
        return cast(PurpurBuild, resp.json())

    async def resolve_version(
        self,
        version: str,
        build: str,
        client: httpx.AsyncClient,
    ) -> ResolvedVersion:
        purpur_version = version
        if purpur_version in ("latest", "experimental"):
            purpur_version = await self._resolve_latest_version(client)

        purpur_build = build
        if purpur_build in ("latest", "experimental"):
            purpur_build = await self._resolve_latest_build(client, purpur_version)

        build_data = await self._load_build_data(client, purpur_version, purpur_build)

        filename = f"purpur-{purpur_version}-{purpur_build}.jar"
        download_url = f"{API_BASE}/{purpur_version}/{purpur_build}/download"

        return ResolvedVersion(
            project="purpur",
            version=purpur_version,
            build=purpur_build,
            download_url=download_url,
            filename=filename,
            md5=build_data.get("md5"),
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        target = dest / resolved.filename
        async with client.stream("GET", resolved.download_url) as resp:
            resp.raise_for_status()
            hasher = hashlib.md5()  # noqa: S324
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    hasher.update(chunk)

        if resolved.md5 and hasher.hexdigest() != resolved.md5:
            target.unlink()
            raise RuntimeError(f"MD5 mismatch for {resolved.filename}")

        return target


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
