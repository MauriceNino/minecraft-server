from __future__ import annotations

import asyncio
import dataclasses

import httpx
from rich.markup import escape

from orchestrator.cli import Config
from orchestrator.constants import SERVER_LOCK_FILENAME, PlatformType, PluginUpdateStrategy
from orchestrator.http import create_http_client
from orchestrator.lockfile import ServerLockfile
from orchestrator.logging import console, log_exception, log_phase
from orchestrator.plugins import PROVIDERS, PluginResolution, resolve_all_plugins
from orchestrator.providers import PROVIDERS as PLATFORM_PROVIDERS

_PENDING_NOTE_BY_STRATEGY = {
    PluginUpdateStrategy.MANUAL: "run [info]mc-orchestrator update[/info] to install",
    PluginUpdateStrategy.AUTO: "installed on next restart",
    PluginUpdateStrategy.FORCE: "installed on next restart",
}


@dataclasses.dataclass(frozen=True)
class PluginStatus:
    name: str
    lock_key: str
    detail: str


@dataclasses.dataclass
class UpdateGroups:
    updates: list[PluginStatus] = dataclasses.field(default_factory=list)
    pinned: list[PluginStatus] = dataclasses.field(default_factory=list)
    new: list[PluginStatus] = dataclasses.field(default_factory=list)
    errors: list[PluginStatus] = dataclasses.field(default_factory=list)
    up_to_date: list[PluginStatus] = dataclasses.field(default_factory=list)


async def _resolve_mc_version(config: Config, client: httpx.AsyncClient) -> str | None:
    try:
        resolved = await PLATFORM_PROVIDERS[config.platform].resolve_version(config.version, config.build, client)
    except Exception as e:
        log_exception(e, "Failed to resolve platform version")
        return None

    console.print(
        f"Platform: [platform]{config.platform.value}[/platform] "
        f"/ Version: [version.new]{resolved.version}[/version.new] "
        f"/ Strategy: [info]{config.plugins_update_strategy}[/info]"
    )
    return resolved.version


async def _resolve_latest_versions(
    resolutions: list[PluginResolution],
    platform_type: PlatformType,
    mc_version: str,
    client: httpx.AsyncClient,
) -> dict[str, str | None]:
    async def resolve_latest(res: PluginResolution) -> tuple[str, str | None]:
        if res.resolved is None:
            return res.lock_key, None
        latest_spec = dataclasses.replace(res.spec, version="latest")
        try:
            resolved = await PROVIDERS[res.spec.provider].resolve(latest_spec, platform_type, mc_version, client)
        except Exception:
            return res.lock_key, None
        return res.lock_key, resolved.version

    return dict(await asyncio.gather(*(resolve_latest(r) for r in resolutions)))


def classify_updates(
    resolutions: list[PluginResolution],
    latest_versions: dict[str, str | None],
) -> UpdateGroups:
    """Sort plugins into groups by what an update would do to them."""
    groups = UpdateGroups()

    for res in sorted(resolutions, key=lambda r: r.display_name.lower()):
        installed = res.lock_entry.version if res.lock_entry else None
        latest = latest_versions.get(res.lock_key)

        if res.resolved is None:
            groups.errors.append(PluginStatus(res.display_name, res.lock_key, f"Error: {res.error}"))
            continue

        resolving = res.resolved.version
        if installed is None:
            groups.new.append(PluginStatus(res.display_name, res.lock_key, f"→ {resolving}"))
        elif resolving != installed:
            groups.updates.append(PluginStatus(res.display_name, res.lock_key, f"{installed} → {resolving}"))
        elif latest and latest != installed:
            groups.pinned.append(PluginStatus(res.display_name, res.lock_key, f"{installed} (latest {latest})"))
        else:
            groups.up_to_date.append(PluginStatus(res.display_name, res.lock_key, installed))

    return groups


def _print_group(title: str, entries: list[PluginStatus], width: int, style: str) -> None:
    if not entries:
        return
    console.print()
    console.print(f"[bold]{title}[/bold] [dim]({len(entries)})[/dim]")
    for entry in entries:
        console.print(f"  [{style}]{escape(entry.name.ljust(width))}[/{style}]  {escape(entry.detail)}")
        console.print(f"    [dim]{escape(entry.lock_key)}[/dim]", soft_wrap=True)


def _print_update_groups(groups: UpdateGroups, strategy: PluginUpdateStrategy) -> None:
    listed = groups.updates + groups.pinned + groups.new + groups.errors
    width = max((len(e.name) for e in listed), default=0)
    pending_note = _PENDING_NOTE_BY_STRATEGY[strategy]

    _print_group(f"Updates available - {pending_note}", groups.updates, width, "green")
    _print_group("Pinned, newer version exists", groups.pinned, width, "yellow")
    _print_group(f"New, not installed yet - {pending_note}", groups.new, width, "green")
    _print_group("Errors", groups.errors, width, "red")

    if groups.up_to_date:
        console.print()
        names = ", ".join(escape(e.name) for e in groups.up_to_date)
        console.print(f"[bold]Up to date[/bold] [dim]({len(groups.up_to_date)})[/dim]: {names}")

    if strategy == PluginUpdateStrategy.MANUAL and (groups.updates or groups.new):
        console.print()
        console.print("Update all:  [info]mc-orchestrator update[/info]")
        console.print("Update one:  [info]mc-orchestrator update -p <key shown above>[/info]")

    if groups.errors:
        console.print(f"\n[red]Encountered {len(groups.errors)} error(s) during check.[/red]")


async def check_plugin_updates(config: Config) -> None:
    """Print the plugins grouped by available updates, with the lock key `update -p` takes."""
    log_phase("Checking for Plugin Updates")

    if not config.plugin_specs:
        console.print("[yellow]No plugins configured.[/yellow]")
        return

    lockfile = ServerLockfile.load(config.runtime_dir / SERVER_LOCK_FILENAME)

    async with create_http_client(tokens=config.api_tokens) as client:
        mc_version = await _resolve_mc_version(config, client)
        if mc_version is None:
            return

        console.print("Resolving plugins... (this might take a few seconds)")
        resolutions = await resolve_all_plugins(config.plugin_specs, config.platform, mc_version, lockfile, client)
        latest_versions = await _resolve_latest_versions(resolutions, config.platform, mc_version, client)

    _print_update_groups(classify_updates(resolutions, latest_versions), config.plugins_update_strategy)
