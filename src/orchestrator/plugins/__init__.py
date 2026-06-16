from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from orchestrator.constants import PlatformType, PluginProviderType, PluginUpdateStrategy, create_http_client
from orchestrator.lockfile import PluginLockEntry, ServerLockfile, make_lock_key
from orchestrator.logging import console, log_change
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin
from orchestrator.plugins.curseforge import CurseForgeProvider
from orchestrator.plugins.github import GithubProvider
from orchestrator.plugins.hangar import HangarProvider
from orchestrator.plugins.modrinth import ModrinthProvider
from orchestrator.plugins.spiget import SpigetProvider
from orchestrator.plugins.url import UrlProvider

__all__ = ["_PROVIDERS", "download_plugins", "resolve_all_plugins"]


_PROVIDERS: dict[PluginProviderType, AbstractPluginProvider] = {
    PluginProviderType.MODRINTH: ModrinthProvider(),
    PluginProviderType.HANGAR: HangarProvider(),
    PluginProviderType.SPIGET: SpigetProvider(),
    PluginProviderType.URL: UrlProvider(),
    PluginProviderType.GITHUB: GithubProvider(),
    PluginProviderType.CURSEFORGE: CurseForgeProvider(),
}


@dataclass(frozen=True, slots=True)
class PluginResolution:
    """Result of resolving a single plugin spec that holds all information about the plugin."""

    spec: PluginSpec
    lock_key: str
    lock_entry: PluginLockEntry | None
    resolved: ResolvedPlugin | None  # None when resolution failed
    error: str | None  # Non-None when resolution failed

    @property
    def display_name(self) -> str:
        if self.resolved:
            return self.resolved.display_name
        return self.spec.identifier


async def _resolve_one_plugin(
    spec: PluginSpec, platform_type: PlatformType, mc_version: str, lockfile: ServerLockfile, client: httpx.AsyncClient
) -> PluginResolution:
    lock_key = make_lock_key(spec.provider, spec.identifier)
    lock_entry = lockfile.get_plugin(lock_key)
    provider = _PROVIDERS.get(spec.provider)

    if provider is None:
        return PluginResolution(
            spec=spec,
            lock_key=lock_key,
            lock_entry=lock_entry,
            resolved=None,
            error=f"Unknown provider '{spec.provider}'",
        )

    try:
        resolved = await provider.resolve(spec, platform_type, mc_version, client)
    except Exception as e:
        return PluginResolution(
            spec=spec,
            lock_key=lock_key,
            lock_entry=lock_entry,
            resolved=None,
            error=str(e),
        )

    return PluginResolution(
        spec=spec,
        lock_key=lock_key,
        lock_entry=lock_entry,
        resolved=resolved,
        error=None,
    )


async def resolve_all_plugins(
    specs: list[PluginSpec],
    platform_type: PlatformType,
    mc_version: str,
    lockfile: ServerLockfile,
    client: httpx.AsyncClient,
) -> list[PluginResolution]:
    return list(
        await asyncio.gather(
            *(_resolve_one_plugin(spec, platform_type, mc_version, lockfile, client) for spec in specs)
        )
    )


def _cleanup_removed_plugins(
    specs: list[PluginSpec],
    plugins_dir: Path,
    lockfile: ServerLockfile,
) -> None:
    requested_keys = {make_lock_key(s.provider, s.identifier) for s in specs}
    for key, entry in list(lockfile.plugins.items()):
        if key not in requested_keys:
            plugin_path = plugins_dir / entry.filename
            if plugin_path.exists():
                plugin_path.unlink()
            del lockfile.plugins[key]
            log_change("deleted", key, f"[version.old][not dim]{entry.version}[/not dim][/version.old]")


async def _download_resolved(
    resolution: PluginResolution,
    provider: AbstractPluginProvider,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    client: httpx.AsyncClient,
    strategy: PluginUpdateStrategy,
) -> None:
    resolved = resolution.resolved

    if not resolved:
        log_change("unresolved", resolution.lock_key, "[error]plugin could not be resolved[/error]")
        return

    if not lockfile.needs_plugin_update(resolution.lock_key, resolved):
        # If the target version changed, but the plugin is already up to date
        # we need to update the lockfile to the new target version
        if resolution.lock_entry and resolution.spec.version != resolution.lock_entry.target_version:
            plugin_path = plugins_dir / resolution.lock_entry.filename
            lockfile.update_plugin(resolution.lock_key, resolved, plugin_path, resolution.spec.version)
        log_change(
            "skipped",
            resolution.lock_key,
            f"[version.new]{resolved.version}[/version.new]",
        )
        return

    old_entry = resolution.lock_entry
    update_reason = (
        f"[version.old]{old_entry.version if old_entry else 'unknown'}[/version.old] [dim]→[/dim] "
        f"[version.new][not dim]{resolved.version}[/not dim][/version.new]"
    )

    if strategy == PluginUpdateStrategy.MANUAL and old_entry:
        log_change("updatable", resolution.lock_key, update_reason)
        return

    # Download to a temporary directory first to avoid corrupting the plugins directory
    with tempfile.TemporaryDirectory(dir=plugins_dir, prefix=".dl_") as tmp_dir:
        tmp_path = await provider.download(resolved, Path(tmp_dir), client)
        final_path = plugins_dir / resolved.filename
        old_backup: Path | None = None

        # 1. If plugin exists, back it up first
        # 2. Try to replace the plugin
        # 3. If something goes wrong, restore the old plugin
        # 4. If everything goes right, remove the old plugin
        if old_entry:
            old_path = plugins_dir / old_entry.filename

            if not old_path.exists():
                raise RuntimeError(
                    "Cannot backup old plugin file, because it does not exist - either remove "
                    "the entry from the lockfile or place the old plugin file in the plugins directory."
                )

            old_backup = old_path.with_name(old_path.name + ".old")
            os.replace(old_path, old_backup)

            try:
                os.replace(tmp_path, final_path)

                if not final_path.exists():
                    raise RuntimeError("Plugin not found after download")
            except Exception:
                if old_backup and old_backup.exists():
                    os.replace(old_backup, old_path)
                raise

            if old_backup.exists():
                old_backup.unlink()
        else:
            os.replace(tmp_path, final_path)

        lockfile.update_plugin(resolution.lock_key, resolved, final_path, resolution.spec.version)

    if old_entry:
        log_change("updated", resolution.lock_key, update_reason)
    else:
        log_change(
            "downloaded",
            resolution.lock_key,
            f"[version.new][not dim]{resolved.version}[/not dim][/version.new]",
        )


async def _resolve_and_download(
    spec: PluginSpec,
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    client: httpx.AsyncClient,
    strategy: PluginUpdateStrategy,
) -> None:
    try:
        resolved = await _resolve_one_plugin(spec, platform_type, mc_version, lockfile, client)
        if resolved.error is not None:
            raise RuntimeError(resolved.error)

        provider = _PROVIDERS[spec.provider]
        await _download_resolved(resolved, provider, plugins_dir, lockfile, client, strategy)
    except Exception as e:
        if strategy == PluginUpdateStrategy.FORCE:
            lock_key = make_lock_key(spec.provider, spec.identifier)
            raise RuntimeError(f"Plugin resolution failed for {lock_key}: {e}") from e
        log_change("errored", spec.identifier, f"[error]{e}[/error]")


async def download_plugins(
    plugin_specs: list[PluginSpec],
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    strategy: PluginUpdateStrategy,
    check_cache_seconds: int,
    target_plugin: str | None = None,
) -> None:
    plugins_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    _cleanup_removed_plugins(plugin_specs, plugins_dir, lockfile)

    if not plugin_specs:
        console.print("  [info]🛈[/info] [label]No plugins to download[/label]")
        lockfile.save()
        return

    use_cache = check_cache_seconds > 0 and lockfile.is_plugins_check_fresh(check_cache_seconds)

    async with create_http_client() as client:
        tasks = []

        for spec in plugin_specs:
            lock_key = make_lock_key(spec.provider, spec.identifier)

            if target_plugin is not None and lock_key != target_plugin:
                continue

            already_installed = lockfile.get_plugin(lock_key)

            if spec.provider is None:
                log_change("errored", lock_key, "unknown provider")
                continue

            target_version_changed = already_installed is not None and already_installed.target_version != spec.version
            if use_cache and already_installed is not None and not target_version_changed:
                log_change("skipped", lock_key, f"[version.new]{already_installed.version}[/version.new] - cached")
                continue

            tasks.append(
                _resolve_and_download(
                    spec=spec,
                    platform_type=platform_type,
                    mc_version=mc_version,
                    plugins_dir=plugins_dir,
                    lockfile=lockfile,
                    client=client,
                    strategy=strategy,
                )
            )

        await asyncio.gather(*tasks)

    if not use_cache and target_plugin is None:
        lockfile.record_plugins_checked()

    lockfile.save()
