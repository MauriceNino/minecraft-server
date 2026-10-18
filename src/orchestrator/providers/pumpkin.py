from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import cast

import httpx

from orchestrator.http import download_file
from orchestrator.logging import console
from orchestrator.plugins.github import GitHubAsset, GitHubRelease, raise_for_github_status
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion
from orchestrator.providers.vanilla import fetch_version_manifest

PUMPKIN_RELEASE_URL = "https://api.github.com/repos/Pumpkin-MC/Pumpkin/releases/tags/nightly"
PATCHBUKKIT_RELEASE_URL = "https://api.github.com/repos/Pumpkin-MC/PatchBukkit/releases/tags/nightly"


def _asset_names() -> tuple[str, str]:
    """Return the (pumpkin, patchbukkit) release asset names for this machine."""
    arch = platform.machine().lower()
    if arch in ("amd64", "x86_64"):
        arch_str = "X64"
    elif arch in ("arm64", "aarch64"):
        arch_str = "ARM64"
    else:
        raise ValueError(f"Unsupported architecture for PumpkinMC: {arch}")

    if sys.platform.startswith("linux"):
        return f"pumpkin-{arch_str}-Linux", f"libpatchbukkit-{arch_str}-Linux.so"
    if sys.platform == "darwin":
        return f"pumpkin-{arch_str}-macOS", f"libpatchbukkit-{arch_str}-macOS.dylib"
    if sys.platform == "win32":
        return f"pumpkin-{arch_str}-Windows.exe", f"patchbukkit-{arch_str}-Windows.dll"
    raise ValueError(f"Unsupported OS for PumpkinMC: {sys.platform}")


async def _find_asset(client: httpx.AsyncClient, release_url: str, name: str) -> GitHubAsset | None:
    headers = {"Authorization": f"Bearer {token}"} if (token := os.environ.get("GITHUB_TOKEN")) else {}
    resp = await client.get(release_url, headers=headers)
    raise_for_github_status(resp)
    release = cast(GitHubRelease, resp.json())
    return next((a for a in release["assets"] if a["name"] == name), None)


def _sha256_from_digest(asset: GitHubAsset) -> str | None:
    digest = asset.get("digest") or ""
    return digest.removeprefix("sha256:") if digest.startswith("sha256:") else None


class PumpkinProvider(AbstractPlatformProvider):
    project = "pumpkin"

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        if version != "experimental":
            raise ValueError(
                "PumpkinMC is currently only available in pre-release. You must set VERSION=experimental to use it."
            )

        pumpkin_asset, _ = _asset_names()
        asset = await _find_asset(client, PUMPKIN_RELEASE_URL, pumpkin_asset)
        if asset is None:
            raise RuntimeError(f"Could not find asset '{pumpkin_asset}' in Pumpkin nightly release.")

        sha256 = _sha256_from_digest(asset)
        manifest = await fetch_version_manifest(client)

        return ResolvedVersion(
            project=self.project,
            # Pumpkin targets the latest vanilla release
            version=manifest["latest"]["release"],
            # The nightly tag is re-published in place, so the asset checksum is what identifies a build
            build=sha256[:12] if sha256 else asset["browser_download_url"],
            download_url=asset["browser_download_url"],
            filename=pumpkin_asset,
            sha256=sha256,
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        target = await super().download(resolved, dest, client)
        target.chmod(0o755)
        return target

    async def install_extras(self, runtime_dir: Path, client: httpx.AsyncClient) -> None:
        _, patchbukkit_asset = _asset_names()
        asset = await _find_asset(client, PATCHBUKKIT_RELEASE_URL, patchbukkit_asset)
        if asset is None:
            console.print(f"  [warning]⚠[/warning] Could not find PatchBukkit asset {patchbukkit_asset}")
            return

        plugins_dir = runtime_dir / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        await download_file(
            client,
            asset["browser_download_url"],
            plugins_dir / patchbukkit_asset,
            {"sha256": _sha256_from_digest(asset)},
        )
        console.print(f"  [success]✓[/success] Downloaded PatchBukkit: [label]{patchbukkit_asset}[/label]")
