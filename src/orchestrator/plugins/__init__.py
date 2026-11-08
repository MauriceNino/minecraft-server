from __future__ import annotations

import asyncio
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from orchestrator.constants import PlatformType, PluginProviderType, PluginUpdateStrategy
from orchestrator.http import ApiTokens, create_http_client
from orchestrator.lockfile import PluginLockEntry, ServerLockfile, file_matches, make_lock_key
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
    """Whether the locked JAR is on disk and unmodified."""
    return entry is not None and bool(entry.filename) and file_matches(plugins_dir / entry.filename, entry.sha256)


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

    # Also when the old JAR was modified, otherwise the server would load both copies
    if old_entry is not None and old_entry.filename and old_entry.filename != final_path.name:
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
) -> PluginResolution:
    """The resolution has an error set if resolving or installing failed."""
    resolution = await _resolve_one_plugin(spec, platform_type, mc_version, lockfile, client)
    try:
        if resolution.resolved is None:
            raise RuntimeError(resolution.error)
        await _install(resolution, resolution.resolved, plugins_dir, lockfile, client, strategy)
    except Exception as e:
        error = str(e) or type(e).__name__
        log_change("errored", resolution.lock_key, f"[error]{error}[/error]")
        return replace(resolution, error=error)
    return resolution


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _warn_missing_dependencies(
    resolutions: list[PluginResolution], plugin_specs: list[PluginSpec], lockfile: ServerLockfile
) -> None:
    """Warn about required dependencies that don't match any configured or installed plugin by name."""
    available = {_normalize_name(e.display_name) for e in lockfile.plugins.values()}
    for spec in plugin_specs:
        # GitHub specs are owner/repo, the repository is usually named after the plugin
        available.update(_normalize_name(name) for name in (spec.identifier, spec.identifier.rsplit("/", 1)[-1]))
    available.update(_normalize_name(r.resolved.display_name) for r in resolutions if r.resolved)

    for resolution in resolutions:
        if resolution.resolved is None:
            continue
        missing = [
            dep.name
            for dep in resolution.resolved.dependencies
            if not any(_normalize_name(name) in available for name in (dep.name, *dep.aliases))
        ]
        if missing:
            console.print(
                f"  [warning]⚠[/warning] [label]{resolution.lock_key}[/label] requires "
                f"{', '.join(f'[label]{name}[/label]' for name in missing)}, which is not in PLUGINS"
            )


async def download_plugins(
    plugin_specs: list[PluginSpec],
    platform_type: PlatformType,
    mc_version: str,
    plugins_dir: Path,
    lockfile: ServerLockfile,
    strategy: PluginUpdateStrategy,
    check_cache_seconds: int,
    target_plugin: str | None = None,
    offline: bool = False,
    tokens: ApiTokens | None = None,
) -> list[str]:
    """Install, update and remove plugins so the plugins directory matches *plugin_specs*.

    In *offline* mode no APIs are contacted and installed plugins are kept as they are.
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
    failures: list[str] = []

    for spec in plugin_specs:
        lock_key = make_lock_key(spec.provider, spec.identifier)
        if target_plugin is not None and lock_key != target_plugin:
            continue

        entry = lockfile.get_plugin(lock_key)
        if offline:
            if _is_installed(entry, plugins_dir) and entry is not None:
                log_change("skipped", lock_key, f"[version.new]{entry.version}[/version.new] - offline")
            else:
                log_change("errored", lock_key, "[error]not installed and the APIs are unreachable[/error]")
                failures.append(f"{lock_key}: not installed and the APIs are unreachable")
            continue

        if (
            use_cache
            and entry is not None
            and entry.target_version == spec.version
            and _is_installed(entry, plugins_dir)
        ):
            log_change("skipped", lock_key, f"[version.new]{entry.version}[/version.new] - cached")
            continue

        pending.append(spec)

    if pending:
        async with create_http_client(tokens=tokens) as client:
            resolutions = await asyncio.gather(
                *(
                    _resolve_and_install(spec, platform_type, mc_version, plugins_dir, lockfile, client, strategy)
                    for spec in pending
                )
            )
        failures.extend(f"{r.lock_key}: {r.error}" for r in resolutions if r.error is not None)
        _warn_missing_dependencies(resolutions, plugin_specs, lockfile)

    if not use_cache and not offline and target_plugin is None and not failures:
        lockfile.record_plugins_checked()
    lockfile.save()

    if failures and strategy == PluginUpdateStrategy.FORCE:
        raise RuntimeError("Plugin installation failed (PLUGINS_UPDATE_STRATEGY=force):\n" + "\n".join(failures))
    return failures
