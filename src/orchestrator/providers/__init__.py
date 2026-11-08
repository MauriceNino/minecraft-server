from __future__ import annotations

import os
import tempfile
from pathlib import Path

import httpx

from orchestrator.constants import PlatformType
from orchestrator.http import ApiTokens, create_http_client
from orchestrator.lockfile import ServerLockfile, file_matches
from orchestrator.logging import console
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion
from orchestrator.providers.paper import PaperProvider
from orchestrator.providers.pumpkin import PumpkinProvider
from orchestrator.providers.purpur import PurpurProvider
from orchestrator.providers.spigotmc import GetBukkitProvider
from orchestrator.providers.vanilla import VanillaProvider

__all__ = ["PROVIDERS", "download_platform", "prepare_platform", "resolve_platform"]

PROVIDERS: dict[PlatformType, AbstractPlatformProvider] = {
    PlatformType.PAPER: PaperProvider(project="paper"),
    PlatformType.FOLIA: PaperProvider(project="folia"),
    PlatformType.VELOCITY: PaperProvider(project="velocity"),
    PlatformType.WATERFALL: PaperProvider(project="waterfall"),
    PlatformType.VANILLA: VanillaProvider(),
    PlatformType.BUKKIT: GetBukkitProvider(project="craftbukkit"),
    PlatformType.SPIGOT: GetBukkitProvider(project="spigot"),
    PlatformType.PUMPKIN: PumpkinProvider(),
    PlatformType.PURPUR: PurpurProvider(),
}


async def resolve_platform(
    platform_type: PlatformType, version: str, build: str, tokens: ApiTokens | None = None
) -> ResolvedVersion:
    async with create_http_client(tokens=tokens) as client:
        resolved = await PROVIDERS[platform_type].resolve_version(version, build, client)

    console.print(f"  [success]✓[/success] Resolved [label]{resolved.version}[/label] (build {resolved.build})")
    return resolved


async def download_platform(
    runtime_dir: Path,
    platform_type: PlatformType,
    resolved: ResolvedVersion,
    lockfile: ServerLockfile,
    tokens: ApiTokens | None = None,
) -> Path:
    """Make sure the server executable for *resolved* is in *runtime_dir* and return its path."""
    runtime_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    jar_path = runtime_dir / resolved.filename

    up_to_date = not lockfile.needs_server_update(resolved.project, resolved.version, resolved.build)
    cached = up_to_date and lockfile.server is not None and file_matches(jar_path, lockfile.server.sha256)
    provider = PROVIDERS[platform_type]

    async with create_http_client(tokens=tokens) as client:
        if cached:
            console.print(
                f"  [cached]✓[/cached] [label]{resolved.filename}[/label]  "
                f"[dim]no changes[/dim] [cached]{resolved.version}[/cached]"
            )
        else:
            # Only touch the old executable once the new one has been downloaded and verified
            with tempfile.TemporaryDirectory(dir=runtime_dir, prefix=".dl_") as tmp_dir:
                downloaded = await provider.download(resolved, Path(tmp_dir), client)
                os.replace(downloaded, jar_path)

            if lockfile.server and lockfile.server.filename != resolved.filename:
                (runtime_dir / lockfile.server.filename).unlink(missing_ok=True)

            console.print(f"  [success]✓[/success] Downloaded [label]{resolved.filename}[/label]")
            lockfile.update_server(
                project=resolved.project,
                version=resolved.version,
                build=resolved.build,
                file_path=jar_path,
            )
            lockfile.save()

        await provider.install_extras(runtime_dir, client, lockfile)

    lockfile.save()
    return jar_path


def _installed_server(
    runtime_dir: Path, platform_type: PlatformType, version: str, build: str, lockfile: ServerLockfile
) -> tuple[Path, str] | None:
    """The locked server executable, if it is intact and satisfies the requested version and build."""
    server = lockfile.server
    if server is None or server.project != PROVIDERS[platform_type].project:
        return None
    if version not in ("latest", "experimental", server.version):
        return None
    if build not in ("latest", "experimental", server.build):
        return None
    jar_path = runtime_dir / server.filename
    if not file_matches(jar_path, server.sha256):
        return None
    return jar_path, server.version


async def prepare_platform(
    runtime_dir: Path,
    platform_type: PlatformType,
    version: str,
    build: str,
    lockfile: ServerLockfile,
    tokens: ApiTokens | None = None,
) -> tuple[Path, str, bool]:
    """Resolve and download the server executable.

    If that fails because an API or the network is unavailable, fall back to the installed executable.
    Returns the executable, the Minecraft version and whether the fallback was used.
    """
    try:
        resolved = await resolve_platform(platform_type, version, build, tokens)
        executable = await download_platform(runtime_dir, platform_type, resolved, lockfile, tokens)
    except (httpx.HTTPError, RuntimeError) as e:
        installed = _installed_server(runtime_dir, platform_type, version, build, lockfile)
        if installed is None:
            raise
        executable, mc_version = installed
        console.print(f"  [warning]⚠[/warning] Could not check for server updates: {e or type(e).__name__}")
        console.print(f"  [warning]⚠[/warning] Starting the installed [label]{executable.name}[/label] instead")
        return executable, mc_version, True
    return executable, resolved.version, False
