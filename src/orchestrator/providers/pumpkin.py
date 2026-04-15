from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import TypedDict

import httpx

from orchestrator.logging import console
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PUMPKIN_RELEASE_URL = "https://api.github.com/repos/Pumpkin-MC/Pumpkin/releases/tags/nightly"
PATCHBUKKIT_RELEASE_URL = "https://api.github.com/repos/Pumpkin-MC/PatchBukkit/releases/tags/nightly"


class PumpkinProvider(AbstractPlatformProvider):
    def _get_asset_names(self) -> tuple[str, str]:
        arch = platform.machine().lower()
        sys_plat = sys.platform.lower()

        if "amd64" in arch or "x86_64" in arch:
            arch_str = "X64"
        elif "arm64" in arch or "aarch64" in arch:
            arch_str = "ARM64"
        else:
            raise ValueError(f"Unsupported architecture for PumpkinMC: {arch}")

        if "linux" in sys_plat:
            os_str = "Linux"
            pumpkin_ext = ""
            patchbukkit_prefix = "lib"
            patchbukkit_ext = ".so"
        elif "darwin" in sys_plat:
            os_str = "macOS"
            pumpkin_ext = ""
            patchbukkit_prefix = "lib"
            patchbukkit_ext = ".dylib"
        elif "win32" in sys_plat:
            os_str = "Windows"
            pumpkin_ext = ".exe"
            patchbukkit_prefix = ""
            patchbukkit_ext = ".dll"
        else:
            raise ValueError(f"Unsupported OS for PumpkinMC: {sys_plat}")

        pumpkin_asset = f"pumpkin-{arch_str}-{os_str}{pumpkin_ext}"
        patchbukkit_asset = f"{patchbukkit_prefix}patchbukkit-{arch_str}-{os_str}{patchbukkit_ext}"
        return pumpkin_asset, patchbukkit_asset

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        if version.lower() != "experimental":
            raise ValueError(
                "PumpkinMC is currently only available in pre-release. You must set VERSION=experimental to use it."
            )

        pumpkin_asset, _ = self._get_asset_names()

        manifest_resp = await client.get(MANIFEST_URL)
        manifest_resp.raise_for_status()
        manifest: MinecraftVersionManifest = manifest_resp.json()

        release_resp = await client.get(PUMPKIN_RELEASE_URL)
        release_resp.raise_for_status()
        release: GitHubRelease = release_resp.json()

        download_url = None
        for asset in release.get("assets", []):
            if asset.get("name") == pumpkin_asset:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            raise RuntimeError(f"Could not find asset '{pumpkin_asset}' in Pumpkin nightly release.")

        commit_sha = release.get("target_commitish", "nightly")

        return ResolvedVersion(
            project="pumpkin",
            version=manifest.get("latest").get("release"),  # Pumpkin mimics the latest minecraft vanilla release
            build=commit_sha,
            download_url=download_url,
            filename=pumpkin_asset,
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        _, patchbukkit_asset = self._get_asset_names()
        jar_path = dest / resolved.filename

        async with client.stream("GET", resolved.download_url) as stream:
            stream.raise_for_status()
            with jar_path.open("wb") as f:
                async for chunk in stream.aiter_bytes():
                    f.write(chunk)

        jar_path.chmod(0o755)

        plugins_dir = dest / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)

        response = await client.get(PATCHBUKKIT_RELEASE_URL)
        response.raise_for_status()
        data: GitHubRelease = response.json()

        pb_download_url = None
        for asset in data.get("assets", []):
            if asset.get("name") == patchbukkit_asset:
                pb_download_url = asset.get("browser_download_url")
                break

        if pb_download_url:
            pb_path = plugins_dir / patchbukkit_asset
            async with client.stream("GET", pb_download_url) as stream:
                stream.raise_for_status()
                with pb_path.open("wb") as f:
                    async for chunk in stream.aiter_bytes():
                        f.write(chunk)

            pb_path.chmod(0o755)

            console.print(f"  [success]✓[/success] Downloaded PatchBukkit: [label]{patchbukkit_asset}[/label]")
        else:
            console.print(f"  [yellow]⚠ Could not find PatchBukkit asset {patchbukkit_asset}[/yellow]")

        return jar_path


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


class GitHubUser(TypedDict):
    login: str
    id: int
    node_id: str
    avatar_url: str
    gravatar_id: str
    url: str
    html_url: str
    followers_url: str
    following_url: str
    gists_url: str
    starred_url: str
    subscriptions_url: str
    organizations_url: str
    repos_url: str
    events_url: str
    received_events_url: str
    type: str
    user_view_type: str
    site_admin: bool


class GitHubReleaseAsset(TypedDict):
    url: str
    id: int
    node_id: str
    name: str
    label: str | None
    uploader: GitHubUser
    content_type: str
    state: str
    size: int
    digest: str | None
    download_count: int
    created_at: str
    updated_at: str
    browser_download_url: str


class GitHubRelease(TypedDict):
    url: str
    assets_url: str
    upload_url: str
    html_url: str
    id: int
    author: GitHubUser
    node_id: str
    tag_name: str
    target_commitish: str
    name: str
    draft: bool
    immutable: bool
    prerelease: bool
    created_at: str
    updated_at: str
    published_at: str
    assets: list[GitHubReleaseAsset]
    tarball_url: str
    zipball_url: str
    body: str
