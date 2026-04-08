from __future__ import annotations

from pathlib import Path

import httpx

from orchestrator.constants import USER_AGENT, PlatformType
from orchestrator.lockfile import ServerLockfile
from orchestrator.logging import console
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion
from orchestrator.providers.paper import PaperProvider

__all__ = ["download_platform", "get_platform_provider", "resolve_platform"]

_PROVIDERS: dict[PlatformType, AbstractPlatformProvider] = {
    PlatformType.PAPER: PaperProvider(project="paper"),
    PlatformType.FOLIA: PaperProvider(project="folia"),
    PlatformType.VELOCITY: PaperProvider(project="velocity"),
}


def get_platform_provider(platform: PlatformType) -> AbstractPlatformProvider:
    """Return the concrete provider for *platform*."""
    try:
        return _PROVIDERS[platform]
    except KeyError:
        msg = f"No provider registered for platform {platform.value!r}"
        raise ValueError(msg) from None


async def resolve_platform(platform_type: PlatformType, version: str, build: str) -> ResolvedVersion:
    provider = get_platform_provider(platform_type)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(120.0, connect=15.0),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        resolved_version = await provider.resolve_version(version, build, client)
        console.print(
            f"  [success]✓[/success] Resolved [label]{resolved_version.version}[/label] "
            f"(build {resolved_version.build})"
        )
        return resolved_version


async def download_platform(
    cache_dir: Path,
    runtime_dir: Path,
    platform_type: PlatformType,
    resolved_version: ResolvedVersion,
    lockfile: ServerLockfile,
) -> Path:
    provider = get_platform_provider(platform_type)
    cache_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    runtime_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    jar_path = runtime_dir / resolved_version.filename

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(120.0, connect=15.0),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        if lockfile.needs_server_update(resolved_version.version, str(resolved_version.build)):
            if lockfile.server:
                old_jar = runtime_dir / lockfile.server.filename
                if old_jar.exists():
                    old_jar.unlink()

            await provider.download(resolved_version, runtime_dir, client)
            console.print(f"  [success]✓[/success] Downloaded [label]{resolved_version.filename}[/label]")

            lockfile.update_server(
                project=resolved_version.project,
                version=resolved_version.version,
                build=str(resolved_version.build),
                filename=resolved_version.filename,
                file_path=jar_path,
            )
            lockfile.save()
        else:
            console.print(
                f"  [cached]✓[/cached] [label]{resolved_version.filename}[/label]  "
                f"[dim]no changes[/dim] [cached]{resolved_version.version}[/cached]"
            )

    return jar_path
