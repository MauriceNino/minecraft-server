from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path
from typing import cast

import httpx

from orchestrator.elf import read_u32_symbol
from orchestrator.http import download_file
from orchestrator.lockfile import ServerLockfile, file_matches
from orchestrator.logging import console
from orchestrator.plugins.github import GitHubAsset, GitHubRelease, raise_for_github_status
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion
from orchestrator.providers.vanilla import fetch_version_manifest

PUMPKIN_RELEASES = "https://api.github.com/repos/Pumpkin-MC/Pumpkin/releases"
PUMPKIN_STABLE_URL = f"{PUMPKIN_RELEASES}/latest"
PUMPKIN_NIGHTLY_URL = f"{PUMPKIN_RELEASES}/tags/nightly"
PATCHBUKKIT_RELEASES = "https://api.github.com/repos/Pumpkin-MC/PatchBukkit/releases"
PATCHBUKKIT_STABLE_URL = f"{PATCHBUKKIT_RELEASES}/latest"
PATCHBUKKIT_NIGHTLY_URL = f"{PATCHBUKKIT_RELEASES}/tags/nightly"
PATCHBUKKIT_LOCK_KEY = "patchbukkit"
# Assets of the nightly tag are downloaded from here, stable ones from their version tag
NIGHTLY_DOWNLOAD_PATH = "/releases/download/nightly/"

PUMPKIN_PLUGIN_API_SOURCE = (
    "https://raw.githubusercontent.com/Pumpkin-MC/Pumpkin/{ref}/crates/pumpkin-core/src/plugin/mod.rs"
)
_PLUGIN_API_RE = re.compile(r"PLUGIN_API_VERSION\s*:\s*u32\s*=\s*(\d+)")
# Exported by native Pumpkin plugins, Pumpkin refuses to load a plugin when it differs from its own version
PATCHBUKKIT_API_SYMBOL = "PUMPKIN_API_VERSION"
DISABLED_SUFFIX = ".disabled"

# Stable tags are `<pumpkin version>+<java version>-<bedrock version>`, e.g. `0.2.2+26.3-26.60`
_STABLE_TAG_RE = re.compile(r"^(?P<pumpkin>[^+]+)\+(?P<java>[^-]+)-")


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


async def _fetch_release(client: httpx.AsyncClient, release_url: str) -> GitHubRelease:
    resp = await client.get(release_url)
    raise_for_github_status(resp)
    return cast(GitHubRelease, resp.json())


def _find_asset(release: GitHubRelease, name: str) -> GitHubAsset | None:
    return next((a for a in release["assets"] if a["name"] == name), None)


async def _pumpkin_plugin_api(client: httpx.AsyncClient, resolved: ResolvedVersion) -> int | None:
    """The plugin API version of a Pumpkin build, read from its source at the release tag.

    The binary doesn't export it. Every release tag, including `nightly`, points at the commit it was built from.
    None when it can't be determined, then PatchBukkit is installed without the check.
    """
    _, sep, rest = resolved.download_url.partition("/releases/download/")
    tag = rest.partition("/")[0]
    if not sep or not tag:
        return None
    try:
        resp = await client.get(PUMPKIN_PLUGIN_API_SOURCE.format(ref=tag))
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    match = _PLUGIN_API_RE.search(resp.text)
    return int(match[1]) if match else None


def _sha256_from_digest(asset: GitHubAsset) -> str | None:
    digest = asset.get("digest") or ""
    return digest.removeprefix("sha256:") if digest.startswith("sha256:") else None


class PumpkinProvider(AbstractPlatformProvider):
    project = "pumpkin"

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        if version not in ("latest", "experimental"):
            raise ValueError(
                f"Unsupported Pumpkin VERSION={version!r}. Use VERSION=latest for the stable release"
                " or VERSION=experimental for the nightly build."
            )
        nightly = version == "experimental"
        channel = "nightly" if nightly else "stable"

        pumpkin_asset, _ = _asset_names()
        release = await _fetch_release(client, PUMPKIN_NIGHTLY_URL if nightly else PUMPKIN_STABLE_URL)
        asset = _find_asset(release, pumpkin_asset)
        if asset is None:
            raise RuntimeError(f"Could not find asset '{pumpkin_asset}' in the Pumpkin {channel} release.")
        sha256 = _sha256_from_digest(asset)

        tag = _STABLE_TAG_RE.match(release["tag_name"]) if not nightly else None
        if tag is not None:
            mc_version = tag["java"]
            resolved_build = tag["pumpkin"]
        else:
            # Pumpkin targets the latest vanilla release
            mc_version = (await fetch_version_manifest(client))["latest"]["release"]
            # The nightly tag is re-published in place, so the asset checksum is what identifies a build
            resolved_build = sha256[:12] if sha256 else asset["browser_download_url"]

        return ResolvedVersion(
            project=self.project,
            version=mc_version,
            build=resolved_build,
            download_url=asset["browser_download_url"],
            filename=pumpkin_asset,
            sha256=sha256,
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        target = await super().download(resolved, dest, client)
        target.chmod(0o755)
        return target

    async def install_extras(
        self, resolved: ResolvedVersion, runtime_dir: Path, client: httpx.AsyncClient, lockfile: ServerLockfile
    ) -> None:
        _, patchbukkit_asset = _asset_names()
        target = runtime_dir / "plugins" / patchbukkit_asset
        # Pumpkin only loads plugins with a library extension, so a build that doesn't fit is kept here
        disabled = target.with_name(f"{patchbukkit_asset}{DISABLED_SUFFIX}")
        entry = lockfile.extras.get(PATCHBUKKIT_LOCK_KEY)
        current = runtime_dir / entry.path if entry is not None else None
        installed = current in (target, disabled) and entry is not None and file_matches(current, entry.sha256)
        # PatchBukkit follows the channel of the Pumpkin build
        nightly = NIGHTLY_DOWNLOAD_PATH in resolved.download_url

        try:
            release = await _fetch_release(client, PATCHBUKKIT_NIGHTLY_URL if nightly else PATCHBUKKIT_STABLE_URL)
            asset = _find_asset(release, patchbukkit_asset)
        except (httpx.HTTPError, RuntimeError) as e:
            if not installed:
                raise
            console.print(f"  [warning]⚠[/warning] Could not check for PatchBukkit updates: {e or type(e).__name__}")
            return
        if asset is None:
            console.print(f"  [warning]⚠[/warning] Could not find PatchBukkit asset {patchbukkit_asset}")
            return

        sha256 = _sha256_from_digest(asset)
        build = sha256[:12] if sha256 else asset["browser_download_url"]
        pumpkin_api = await _pumpkin_plugin_api(client, resolved)

        if installed and current is not None and entry is not None and entry.build == build:
            downloaded = False
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Keep the installed file until the new one has been downloaded and verified
            current = target.with_name(f".{patchbukkit_asset}.tmp")
            await download_file(client, asset["browser_download_url"], current, {"sha256": sha256})
            downloaded = True

        patchbukkit_api = read_u32_symbol(current, PATCHBUKKIT_API_SYMBOL)
        fits = pumpkin_api is None or patchbukkit_api is None or pumpkin_api == patchbukkit_api
        destination = target if fits else disabled
        if current != destination:
            os.replace(current, destination)
        previous = runtime_dir / entry.path if entry is not None else None
        for stale in (target, disabled, previous):
            if stale is not None and stale != destination:
                stale.unlink(missing_ok=True)
        if downloaded or entry is None or runtime_dir / entry.path != destination:
            lockfile.update_extra(PATCHBUKKIT_LOCK_KEY, runtime_dir, destination, build)

        if not fits:
            console.print(
                f"  [warning]⚠[/warning] Skipping PatchBukkit: it was built for plugin API {patchbukkit_api}, this"
                f" Pumpkin build has {pumpkin_api}. Bukkit plugins won't load until PatchBukkit is updated."
            )
        elif downloaded:
            console.print(f"  [success]✓[/success] Downloaded PatchBukkit: [label]{patchbukkit_asset}[/label]")
        else:
            console.print(f"  [cached]✓[/cached] [label]{patchbukkit_asset}[/label]  [dim]no changes[/dim]")
