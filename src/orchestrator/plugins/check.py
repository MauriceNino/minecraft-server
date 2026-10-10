from __future__ import annotations

import asyncio
import dataclasses

import httpx
from rich.table import Table

from orchestrator.cli import Config
from orchestrator.constants import SERVER_LOCK_FILENAME, PlatformType, PluginUpdateStrategy
from orchestrator.http import create_http_client
from orchestrator.lockfile import ServerLockfile
from orchestrator.logging import console, log_exception, log_phase
from orchestrator.plugins import PROVIDERS, PluginResolution, resolve_all_plugins
from orchestrator.providers import PROVIDERS as PLATFORM_PROVIDERS

_ACTION_BY_STRATEGY = {
    PluginUpdateStrategy.MANUAL: "[yellow]None (manual mode)[/yellow]",
    PluginUpdateStrategy.AUTO: "[green]Auto-Update[/green]",
    PluginUpdateStrategy.FORCE: "[green]Auto-Update (forced)[/green]",
}


async def _resolve_mc_version(config: Config, client: httpx.AsyncClient) -> str | None:
    try:
        resolved = await PLATFORM_PROVIDERS[config.platform].resolve_version(config.version, config.build, client)
    except Exception as e:
        log_exception(e, "Failed to resolve platform version")
        return None

    console.print(
        f"Platform: [platform]{config.platform.value}[/platform] "
        f"/ Version: [version.new]{resolved.version}[/version.new]"
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


def _print_update_table(
    resolutions: list[PluginResolution],
    latest_versions: dict[str, str | None],
    strategy: PluginUpdateStrategy,
) -> None:
    table = Table(title="Plugin Update Status", show_header=True, header_style="bold magenta")
    table.add_column("Plugin Name")
    table.add_column("Installed")
    table.add_column("Latest")
    table.add_column("Pinned Target")
    table.add_column("Update Status")
    table.add_column(f"Action on next restart? [dim](strategy: {strategy})[/dim]")

    error_count = 0

    for res in sorted(resolutions, key=lambda r: r.display_name.lower()):
        pinned = res.spec.version
        target_str = f"[blue]{pinned}[/blue]" if pinned == "latest" else f"[dim]{pinned}[/dim]"
        installed = res.lock_entry.version if res.lock_entry else None
        latest = latest_versions.get(res.lock_key)

        if res.resolved is None:
            error_count += 1
            table.add_row(
                res.display_name,
                f"[dim]{installed or '-'}[/dim]",
                latest or "[dim]-[/dim]",
                target_str,
                f"[red]Error: {res.error}[/red]",
                "[dim]-[/dim]",
            )
            continue

        resolving = res.resolved.version
        if installed is None:
            status_str = "[green]New Plugin[/green]"
            action_str = "[green]Install[/green]"
        elif resolving != installed:
            status_str = f"[green]Update available ({resolving})[/green]"
            action_str = _ACTION_BY_STRATEGY[strategy]
        elif latest and latest != installed:
            status_str = f"[yellow]Update available ({latest})[/yellow]"
            action_str = "[dim]None (version pinned)[/dim]"
        else:
            status_str = "[dim]Up to date[/dim]"
            action_str = "[dim]None (up to date)[/dim]"

        table.add_row(
            res.display_name,
            f"[dim]{installed}[/dim]" if installed else "[yellow]Not installed[/yellow]",
            latest or "[yellow]Unknown[/yellow]",
            target_str,
            status_str,
            action_str,
        )

    console.print()
    console.print(table)

    if error_count:
        console.print(f"\n[red]Encountered {error_count} error(s) during check.[/red]")


async def check_plugin_updates(config: Config) -> None:
    """Print a table comparing installed, resolvable and latest plugin versions."""
    log_phase("Checking for Plugin Updates")

    if not config.plugin_specs:
        console.print("[yellow]No plugins configured.[/yellow]")
        return

    lockfile = ServerLockfile.load(config.runtime_dir / SERVER_LOCK_FILENAME)

    async with create_http_client() as client:
        mc_version = await _resolve_mc_version(config, client)
        if mc_version is None:
            return

        console.print("Resolving plugins... (this might take a few seconds)")
        resolutions = await resolve_all_plugins(config.plugin_specs, config.platform, mc_version, lockfile, client)
        latest_versions = await _resolve_latest_versions(resolutions, config.platform, mc_version, client)

    _print_update_table(resolutions, latest_versions, config.plugins_update_strategy)
