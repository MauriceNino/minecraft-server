from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import httpx

from orchestrator.constants import USER_AGENT, PlatformType, PluginUpdateStrategy
from orchestrator.lockfile import ServerLockfile, make_lock_key
from orchestrator.logging import console, log_change
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec
from orchestrator.plugins.curseforge import CurseForgeProvider
from orchestrator.plugins.github import GithubProvider
from orchestrator.plugins.hangar import HangarProvider
from orchestrator.plugins.modrinth import ModrinthProvider
from orchestrator.plugins.resolver import parse_plugin_lines
from orchestrator.plugins.spiget import SpigetProvider
from orchestrator.plugins.url import UrlProvider

__all__ = ["download_plugins"]


def _build_providers() -> dict[str, AbstractPluginProvider]:
    return {
        "modrinth": ModrinthProvider(),
        "hangar": HangarProvider(),
        "spiget": SpigetProvider(),
        "url": UrlProvider(),
        "github": GithubProvider(),
        "curseforge": CurseForgeProvider(),
    }


async def _resolve_and_download(
    spec: PluginSpec,
    provider: AbstractPluginProvider,
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    client: httpx.AsyncClient,
    strategy: PluginUpdateStrategy,
) -> None:
    lock_key = make_lock_key(spec.provider, spec.identifier)
    try:
        resolved = await provider.resolve(spec, platform_type, mc_version, client)

        old_entry = lockfile.get_plugin(lock_key)
        old_version = old_entry.version if old_entry else None

        if old_version == resolved.version:
            log_change("skipped", lock_key, f"[version.new]{resolved.version}[/version.new]")
            return

        update_reason = (
            f"[version.old]{old_version}[/version.old] [dim]→[/dim] "
            f"[version.new][not dim]{resolved.version}[/not dim][/version.new]"
        )
        if strategy == PluginUpdateStrategy.MANUAL and old_version:
            log_change("updatable", lock_key, update_reason)
            return

        # Download plugin to a temporary directory first to avoid corrupting the plugins directory
        with tempfile.TemporaryDirectory(dir=plugins_dir, prefix=".dl_") as tmp_dir:
            tmp_path = await provider.download(resolved, Path(tmp_dir), client)

            final_path = plugins_dir / resolved.filename
            os.replace(tmp_path, final_path)

            lockfile.update_plugin(lock_key, resolved, final_path)

        if old_version:
            log_change("updated", lock_key, update_reason)
        else:
            log_change("downloaded", lock_key, f"[version.new][not dim]{resolved.version}[/not dim][/version.new]")
    except Exception as e:
        if strategy == PluginUpdateStrategy.FORCE:
            raise
        log_change("errored", lock_key, f"[version.new][error]{e}[/error][/version.new]")


async def download_plugins(
    plugin_lines: list[str],
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    strategy: PluginUpdateStrategy,
    check_cache_seconds: int | None = None,
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
            log_change("deleted", key, f"[version.old][not dim]{entry.version}[/not dim][/version.old]")

    if not specs:
        console.print("  [info]🛈[/info] [label]No plugins to download[/label]")
        lockfile.save()
        return

    use_cache = check_cache_seconds is not None and lockfile.is_plugins_check_fresh(check_cache_seconds)
    providers = _build_providers()

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        tasks = []
        for spec in specs:
            provider = providers.get(spec.provider)
            lock_key = make_lock_key(spec.provider, spec.identifier)

            if provider is None:
                log_change("errored", lock_key, "unknown provider")
                continue

            already_installed = lockfile.get_plugin(lock_key)

            # When the cache is still fresh, skip existing plugins entirely
            if use_cache and already_installed is not None:
                current_version = already_installed.version
                log_change("skipped", lock_key, f"[version.new]{current_version}[/version.new] - check-cache valid")
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
                    strategy=strategy,
                )
            )

        await asyncio.gather(*tasks)

    # Record the timestamp only when we performed a full check (cache not used)
    if not use_cache:
        lockfile.record_plugins_checked()

    lockfile.save()
