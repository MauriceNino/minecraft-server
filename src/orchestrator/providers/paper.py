from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypedDict, cast

import httpx

from orchestrator.logging import get_logger
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

log = get_logger(__name__)

API_BASE = "https://fill.papermc.io/v3/projects"


class PaperProvider(AbstractPlatformProvider):
    def __init__(self, project: str = "paper") -> None:
        self._project = project

    async def _resolve_latest_version(self, client: httpx.AsyncClient, allow_snapshots: bool) -> str:
        resp = await client.get(f"{API_BASE}/{self._project}")
        resp.raise_for_status()
        data = cast(PaperProject, resp.json())
        versions = [v for sublist in data["versions"].values() for v in sublist]

        if allow_snapshots:
            return versions[0]
        else:
            for version in versions:
                if not version.endswith("-SNAPSHOT"):
                    return version
            raise RuntimeError(f"No stable {self._project} versions found")

    async def _resolve_latest_build(
        self, client: httpx.AsyncClient, version: str, allowed_channels: list[str]
    ) -> PaperBuildVersion:
        resp = await client.get(f"{API_BASE}/{self._project}/versions/{version}/builds")
        resp.raise_for_status()
        data = cast(PaperBuildVersionList, resp.json())

        for build in data:
            if build.get("channel") in allowed_channels:
                return build

        raise RuntimeError(f"No builds found for {self._project} {version} in channels {allowed_channels}")

    async def _load_build_data(self, client: httpx.AsyncClient, version: str, build: str) -> PaperBuildVersion:
        resp = await client.get(f"{API_BASE}/{self._project}/versions/{version}/builds/{build}")
        resp.raise_for_status()
        return cast(PaperBuildVersion, resp.json())

    async def resolve_version(
        self,
        version: str,
        build: str,
        client: httpx.AsyncClient,
    ) -> ResolvedVersion:
        # Resolve version
        vel_version = version
        if vel_version in ("latest", "experimental"):
            vel_version = await self._resolve_latest_version(client, version == "experimental")

        # Resolve build
        if build in ("latest", "experimental"):
            channels = ["STABLE"] if build == "latest" else ["STABLE", "BETA", "ALPHA"]
            vel_build = await self._resolve_latest_build(client, vel_version, channels)
        else:
            vel_build = await self._load_build_data(client, vel_version, build)

        download = vel_build["downloads"]["server:default"]

        return ResolvedVersion(
            project=self._project,
            version=vel_version,
            build=str(vel_build["id"]),
            download_url=download["url"],
            filename=download["name"],
            sha256=download["checksums"]["sha256"],
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
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
            msg = f"SHA-256 mismatch for {resolved.filename}"
            raise RuntimeError(msg)

        return target


class Project(TypedDict):
    id: str
    name: str


class PaperProject(TypedDict):
    project: Project
    versions: dict[str, list[str]]


class Commit(TypedDict):
    sha: str
    time: str
    message: str


class DownloadInfo(TypedDict):
    name: str
    checksums: dict[str, str]
    size: int
    url: str


class PaperBuildVersion(TypedDict):
    id: int
    time: str
    channel: str
    commits: list[Commit]
    downloads: dict[str, DownloadInfo]


PaperBuildVersionList = list[PaperBuildVersion]
