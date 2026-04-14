from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from orchestrator.constants import USER_AGENT, PlatformType
from orchestrator.lockfile import ServerLockfile, make_lock_key
from orchestrator.logging import console, log_version_change
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec
from orchestrator.plugins.hangar import HangarProvider
from orchestrator.plugins.modrinth import ModrinthProvider
from orchestrator.plugins.resolver import parse_plugin_lines
from orchestrator.plugins.spiget import SpigetProvider
from orchestrator.plugins.url import UrlProvider
from orchestrator.plugins.github import GithubProvider

__all__ = ["download_plugins"]


def _build_providers() -> dict[str, AbstractPluginProvider]:
    return {
        "modrinth": ModrinthProvider(),
        "hangar": HangarProvider(),
        "spiget": SpigetProvider(),
        "url": UrlProvider(),
        "github": GithubProvider(),
    }


async def _resolve_and_download(
    spec: PluginSpec,
    provider: AbstractPluginProvider,
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    client: httpx.AsyncClient,
) -> None:
    lock_key = make_lock_key(spec.provider, spec.identifier)
    resolved = await provider.resolve(spec, platform_type, mc_version, client)

    old_entry = lockfile.get_plugin(lock_key)
    old_version = old_entry.version if old_entry else None

    if not lockfile.needs_plugin_update(lock_key, resolved):
        console.print(
            f"  [cached]✓[/cached] [label]{spec.identifier}[/label]  "
            f"[dim]no changes[/dim] [cached]{resolved.version}[/cached]"
        )
        return

    log_version_change(spec.identifier, old_version, resolved.version)

    downloaded_path = await provider.download(resolved, plugins_dir, client)
    lockfile.update_plugin(lock_key, resolved, downloaded_path)


async def download_plugins(
    plugin_lines: list[str],
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
) -> None:
    specs = parse_plugin_lines(plugin_lines)

    plugins_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    requested_keys = {make_lock_key(spec.provider, spec.identifier) for spec in specs}

    for key, entry in list(lockfile.plugins.items()):
        if key not in requested_keys:
            plugin_path = plugins_dir / entry.filename
            if plugin_path.exists():
                plugin_path.unlink()
            del lockfile.plugins[key]

            console.print(
                f"  [removed]✗[/removed] [label]{key}[/label]  [dim]removed[/dim] [cached]{entry.version}[/cached]"
            )

    if not specs:
        console.print("  [info]🛈[/info] [label]No plugins to download[/label]")
        lockfile.save()
        return

    providers = _build_providers()

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        tasks = []
        for spec in specs:
            provider = providers.get(spec.provider)
            if provider is None:
                console.print(
                    f"  [warning]⚠[/warning] [label]{spec.identifier}[/label]  [dim]unknown provider -- skipping[/dim]"
                )
                continue
            tasks.append(
                _resolve_and_download(
                    spec=spec,
                    provider=provider,
                    platform_type=platform_type,
                    mc_version=mc_version,
                    plugins_dir=plugins_dir,
                    lockfile=lockfile,
                    client=client,
                )
            )

        await asyncio.gather(*tasks)

    lockfile.save()
