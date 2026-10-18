from __future__ import annotations

from typing import TypedDict, cast

import httpx

from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


async def fetch_version_manifest(client: httpx.AsyncClient) -> VersionManifest:
    resp = await client.get(MANIFEST_URL)
    resp.raise_for_status()
    return cast(VersionManifest, resp.json())


class VanillaProvider(AbstractPlatformProvider):
    project = "vanilla"

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        manifest = await fetch_version_manifest(client)

        if version == "latest":
            version = manifest["latest"]["release"]
        elif version == "experimental":
            version = manifest["latest"]["snapshot"]

        entry = next((v for v in manifest["versions"] if v["id"] == version), None)
        if entry is None:
            raise RuntimeError(f"Vanilla version {version} not found")

        resp = await client.get(entry["url"])
        resp.raise_for_status()
        server_download = cast(VersionProfile, resp.json())["downloads"].get("server")
        if not server_download:
            raise RuntimeError(f"No server download found for Vanilla {version}")

        return ResolvedVersion(
            project=self.project,
            version=version,
            build="1",  # Vanilla has no builds
            download_url=server_download["url"],
            filename=f"vanilla-{version}.jar",
            sha1=server_download["sha1"],
        )


class LatestVersions(TypedDict):
    release: str
    snapshot: str


class ManifestEntry(TypedDict):
    id: str
    type: str
    url: str
    time: str
    releaseTime: str
    sha1: str
    complianceLevel: int


class VersionManifest(TypedDict):
    latest: LatestVersions
    versions: list[ManifestEntry]


class JavaVersion(TypedDict):
    component: str
    majorVersion: int


class ProfileDownload(TypedDict):
    sha1: str
    size: int
    url: str


class ProfileDownloads(TypedDict):
    client: ProfileDownload
    server: ProfileDownload


class VersionProfile(TypedDict):
    assets: str
    complianceLevel: int
    downloads: ProfileDownloads
    id: str
    javaVersion: JavaVersion
    mainClass: str
    minimumLauncherVersion: int
    releaseTime: str
    time: str
    type: str
