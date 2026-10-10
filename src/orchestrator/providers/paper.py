from __future__ import annotations

from typing import TypedDict, cast

import httpx

from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

API_BASE = "https://fill.papermc.io/v3/projects"


class PaperProvider(AbstractPlatformProvider):
    """Paper, Folia, Velocity and Waterfall, all served by the PaperMC Fill API."""

    def __init__(self, project: str) -> None:
        self._project = project

    async def _resolve_latest_version(self, client: httpx.AsyncClient, allow_snapshots: bool) -> str:
        resp = await client.get(f"{API_BASE}/{self._project}")
        resp.raise_for_status()
        data = cast(PaperProject, resp.json())
        # Grouped by major version, newest first: {"1.21": ["1.21.4", "1.21.3", ...], ...}
        versions = [v for group in data["versions"].values() for v in group]

        for version in versions:
            if allow_snapshots or not version.endswith("-SNAPSHOT"):
                return version
        raise RuntimeError(f"No stable {self._project} versions found")

    async def _resolve_latest_build(
        self, client: httpx.AsyncClient, version: str, allowed_channels: list[str]
    ) -> PaperBuild:
        resp = await client.get(f"{API_BASE}/{self._project}/versions/{version}/builds")
        resp.raise_for_status()

        for build in cast(list[PaperBuild], resp.json()):
            if build["channel"] in allowed_channels:
                return build
        raise RuntimeError(f"No builds found for {self._project} {version} in channels {allowed_channels}")

    async def _load_build(self, client: httpx.AsyncClient, version: str, build: str) -> PaperBuild:
        resp = await client.get(f"{API_BASE}/{self._project}/versions/{version}/builds/{build}")
        resp.raise_for_status()
        return cast(PaperBuild, resp.json())

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        if version in ("latest", "experimental"):
            version = await self._resolve_latest_version(client, allow_snapshots=version == "experimental")

        if build in ("latest", "experimental"):
            channels = ["STABLE"] if build == "latest" else ["STABLE", "BETA", "ALPHA"]
            build_data = await self._resolve_latest_build(client, version, channels)
        else:
            build_data = await self._load_build(client, version, build)

        download = build_data["downloads"]["server:default"]
        return ResolvedVersion(
            project=self._project,
            version=version,
            build=str(build_data["id"]),
            download_url=download["url"],
            filename=download["name"],
            sha256=download["checksums"]["sha256"],
        )


class PaperProjectInfo(TypedDict):
    id: str
    name: str


class PaperProject(TypedDict):
    project: PaperProjectInfo
    versions: dict[str, list[str]]


class PaperCommit(TypedDict):
    sha: str
    time: str
    message: str


class PaperDownload(TypedDict):
    name: str
    checksums: dict[str, str]
    size: int
    url: str


class PaperBuild(TypedDict):
    id: int
    time: str
    channel: str
    commits: list[PaperCommit]
    downloads: dict[str, PaperDownload]
