from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypedDict

import httpx

from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"


class VanillaProvider(AbstractPlatformProvider):
    async def resolve_version(
        self,
        version: str,
        build: str,
        client: httpx.AsyncClient,
    ) -> ResolvedVersion:
        resp = await client.get(MANIFEST_URL)
        resp.raise_for_status()
        manifest: MinecraftVersionManifest = resp.json()

        latest_release = manifest["latest"]["release"]
        latest_snapshot = manifest["latest"]["snapshot"]

        target_version = version
        if target_version == "latest":
            target_version = latest_release
        elif target_version == "experimental":
            target_version = latest_snapshot

        # Find version info
        version_entry = next((v for v in manifest["versions"] if v["id"] == target_version), None)
        if not version_entry:
            raise RuntimeError(f"Vanilla version {target_version} not found")

        # Fetch version-specific metadata
        v_resp = await client.get(version_entry["url"])
        v_resp.raise_for_status()
        data: MinecraftVersionProfile = v_resp.json()

        server_download = data["downloads"].get("server")
        if not server_download:
            raise RuntimeError(f"No server download found for Vanilla {target_version}")

        return ResolvedVersion(
            project="vanilla",
            version=target_version,
            build="1",  # Vanilla doesn't have builds
            download_url=server_download["url"],
            filename=f"vanilla-{target_version}.jar",
            sha1=server_download["sha1"],
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        target = dest / resolved.filename
        async with client.stream("GET", resolved.download_url) as resp:
            resp.raise_for_status()
            sha = hashlib.sha1()  # noqa: S324
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    sha.update(chunk)

        if resolved.sha1 and sha.hexdigest() != resolved.sha1:
            target.unlink()
            msg = f"SHA-1 mismatch for {resolved.filename}"
            raise RuntimeError(msg)

        return target


class MinecraftLatest(TypedDict):
    release: str
    snapshot: str


class MinecraftVersion(TypedDict):
    id: str
    type: str
    url: str
    time: str
    releaseTime: str
    sha1: str
    complianceLevel: int


class MinecraftVersionManifest(TypedDict):
    latest: MinecraftLatest
    versions: list[MinecraftVersion]


class MinecraftJavaVersion(TypedDict):
    component: str
    majorVersion: int


class DownloadInfo(TypedDict):
    sha1: str
    size: int
    url: str


class MinecraftRootDownloads(TypedDict):
    client: DownloadInfo
    server: DownloadInfo


class MinecraftVersionProfile(TypedDict):
    assets: str
    complianceLevel: int
    downloads: MinecraftRootDownloads
    id: str
    javaVersion: MinecraftJavaVersion
    mainClass: str
    minimumLauncherVersion: int
    releaseTime: str
    time: str
    type: str
