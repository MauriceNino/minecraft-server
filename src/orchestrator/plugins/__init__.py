from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from orchestrator.constants import PlatformType, PluginProviderType, PluginUpdateStrategy
from orchestrator.http import create_http_client
from orchestrator.lockfile import PluginLockEntry, ServerLockfile, make_lock_key
from orchestrator.logging import console, log_change
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin
from orchestrator.plugins.curseforge import CurseForgeProvider
from orchestrator.plugins.github import GithubProvider
from orchestrator.plugins.hangar import HangarProvider
from orchestrator.plugins.modrinth import ModrinthProvider
from orchestrator.plugins.spiget import SpigetProvider
from orchestrator.plugins.url import UrlProvider

__all__ = ["PROVIDERS", "PluginResolution", "download_plugins", "resolve_all_plugins"]


PROVIDERS: dict[PluginProviderType, AbstractPluginProvider] = {
    PluginProviderType.MODRINTH: ModrinthProvider(),
    PluginProviderType.HANGAR: HangarProvider(),
    PluginProviderType.SPIGET: SpigetProvider(),
    PluginProviderType.URL: UrlProvider(),
    PluginProviderType.GITHUB: GithubProvider(),
    PluginProviderType.CURSEFORGE: CurseForgeProvider(),
}


@dataclass(frozen=True, slots=True)
class PluginResolution:
    spec: PluginSpec
    lock_key: str
    lock_entry: PluginLockEntry | None
    resolved: ResolvedPlugin | None  # None when resolution failed
    error: str | None  # set when resolution failed

    @property
    def display_name(self) -> str:
        return self.resolved.display_name if self.resolved else self.spec.identifier


async def _resolve_one_plugin(
    spec: PluginSpec, platform_type: PlatformType, mc_version: str, lockfile: ServerLockfile, client: httpx.AsyncClient
) -> PluginResolution:
    lock_key = make_lock_key(spec.provider, spec.identifier)
    lock_entry = lockfile.get_plugin(lock_key)
    try:
        resolved = await PROVIDERS[spec.provider].resolve(spec, platform_type, mc_version, client)
    except Exception as e:
        return PluginResolution(spec, lock_key, lock_entry, resolved=None, error=str(e) or type(e).__name__)
    return PluginResolution(spec, lock_key, lock_entry, resolved=resolved, error=None)


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


def _cleanup_removed_plugins(specs: list[PluginSpec], plugins_dir: Path, lockfile: ServerLockfile) -> None:
    requested_keys = {make_lock_key(s.provider, s.identifier) for s in specs}
    for key, entry in list(lockfile.plugins.items()):
        if key in requested_keys:
            continue
        (plugins_dir / entry.filename).unlink(missing_ok=True)
        del lockfile.plugins[key]
        log_change("deleted", key, f"[version.old][not dim]{entry.version}[/not dim][/version.old]")


def _is_installed(entry: PluginLockEntry | None, plugins_dir: Path) -> bool:
    return entry is not None and bool(entry.filename) and (plugins_dir / entry.filename).is_file()


async def _install(
    resolution: PluginResolution,
    resolved: ResolvedPlugin,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    client: httpx.AsyncClient,
    strategy: PluginUpdateStrategy,
) -> None:
    spec = resolution.spec
    old_entry = resolution.lock_entry
    installed = _is_installed(old_entry, plugins_dir)

    if installed and old_entry is not None and old_entry.version == resolved.version:
        if old_entry.target_version != spec.version:
            lockfile.update_plugin(resolution.lock_key, resolved, plugins_dir / old_entry.filename, spec.version)
        log_change("skipped", resolution.lock_key, f"[version.new]{resolved.version}[/version.new]")
        return

    update_reason = (
        f"[version.old]{old_entry.version if old_entry else 'unknown'}[/version.old] [dim]→[/dim] "
        f"[version.new][not dim]{resolved.version}[/not dim][/version.new]"
    )
    if installed and strategy == PluginUpdateStrategy.MANUAL:
        log_change("updatable", resolution.lock_key, update_reason)
        return

    # Download next to the plugins so the final move is an atomic rename on the same filesystem
    with tempfile.TemporaryDirectory(dir=plugins_dir, prefix=".dl_") as tmp_dir:
        tmp_path = await PROVIDERS[spec.provider].download(resolved, Path(tmp_dir), client)
        final_path = plugins_dir / tmp_path.name
        os.replace(tmp_path, final_path)

    if installed and old_entry is not None and old_entry.filename != final_path.name:
        (plugins_dir / old_entry.filename).unlink(missing_ok=True)

    lockfile.update_plugin(resolution.lock_key, resolved, final_path, spec.version)

    if installed:
        log_change("updated", resolution.lock_key, update_reason)
    else:
        log_change(
            "downloaded", resolution.lock_key, f"[version.new][not dim]{resolved.version}[/not dim][/version.new]"
        )


async def _resolve_and_install(
    spec: PluginSpec,
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    client: httpx.AsyncClient,
    strategy: PluginUpdateStrategy,
) -> str | None:
    """Returns an error message on failure."""
    resolution = await _resolve_one_plugin(spec, platform_type, mc_version, lockfile, client)
    try:
        if resolution.resolved is None:
            raise RuntimeError(resolution.error)
        await _install(resolution, resolution.resolved, plugins_dir, lockfile, client, strategy)
    except Exception as e:
        error = str(e) or type(e).__name__
        log_change("errored", resolution.lock_key, f"[error]{error}[/error]")
        return f"{resolution.lock_key}: {error}"
    return None


async def download_plugins(
    plugin_specs: list[PluginSpec],
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    strategy: PluginUpdateStrategy,
    check_cache_seconds: int,
    target_plugin: str | None = None,
) -> list[str]:
    """Install, update and remove plugins so the plugins directory matches *plugin_specs*.

    Returns the failures. With the FORCE strategy any failure raises a RuntimeError instead.
    """
    plugins_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    _cleanup_removed_plugins(plugin_specs, plugins_dir, lockfile)

    if not plugin_specs:
        console.print("  [info]🛈[/info] [label]No plugins to download[/label]")
        lockfile.save()
        return []

    use_cache = check_cache_seconds > 0 and lockfile.is_plugins_check_fresh(check_cache_seconds)
    pending: list[PluginSpec] = []

    for spec in plugin_specs:
        lock_key = make_lock_key(spec.provider, spec.identifier)
        if target_plugin is not None and lock_key != target_plugin:
            continue

        entry = lockfile.get_plugin(lock_key)
        if (
            use_cache
            and entry is not None
            and entry.target_version == spec.version
            and _is_installed(entry, plugins_dir)
        ):
            log_change("skipped", lock_key, f"[version.new]{entry.version}[/version.new] - cached")
            continue

        pending.append(spec)

    async with create_http_client() as client:
        errors = await asyncio.gather(
            *(
                _resolve_and_install(spec, platform_type, mc_version, plugins_dir, lockfile, client, strategy)
                for spec in pending
            )
        )
    failures = [e for e in errors if e is not None]

    if not use_cache and target_plugin is None and not failures:
        lockfile.record_plugins_checked()
    lockfile.save()

    if failures and strategy == PluginUpdateStrategy.FORCE:
        raise RuntimeError("Plugin installation failed (PLUGINS_UPDATE_STRATEGY=force):\n" + "\n".join(failures))
    return failures
