from __future__ import annotations

import asyncio

import httpx
from rich.table import Table

from orchestrator.cli import Config
from orchestrator.constants import SERVER_LOCK_FILENAME, PlatformType, PluginUpdateStrategy, create_http_client
from orchestrator.lockfile import ServerLockfile
from orchestrator.logging import console, log_exception, log_phase
from orchestrator.plugins import _PROVIDERS, PluginResolution, resolve_all_plugins
from orchestrator.plugins.base import PluginSpec
from orchestrator.providers import get_platform_provider


async def _resolve_mc_version(config: Config) -> str | None:
    platform_provider = get_platform_provider(config.platform)
    async with create_http_client() as client:
        try:
            platform_resolved = await platform_provider.resolve_version(config.version, config.build, client)
            console.print(
                f"Platform: [platform]{config.platform.value}[/platform] "
                f"/ Version: [version.new]{platform_resolved.version}[/version.new]"
            )
            return platform_resolved.version
        except Exception as e:
            log_exception(e, "Failed to resolve platform version")
            return None


async def _resolve_latest_versions(
    resolutions: list[PluginResolution],
    platform_type: PlatformType,
    mc_version: str,
    client: httpx.AsyncClient,
) -> dict[str, str | None]:
    async def _resolve_latest(res: PluginResolution) -> tuple[str, str | None]:
        if res.resolved is None:
            return res.lock_key, None
        provider = _PROVIDERS.get(res.spec.provider)
        if provider is None:
            return res.lock_key, None
        latest_spec = PluginSpec(
            provider=res.spec.provider,
            identifier=res.spec.identifier,
            version="latest",
            force=res.spec.force,
        )
        try:
            resolved_latest = await provider.resolve(latest_spec, platform_type, mc_version, client)
            return res.lock_key, resolved_latest.version
        except Exception:
            return res.lock_key, None

    pairs = await asyncio.gather(*(_resolve_latest(r) for r in resolutions))
    return dict(pairs)


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

    warnings_shown = 0

    for res in sorted(resolutions, key=lambda r: r.display_name.lower()):
        pinned = res.spec.version
        target_str = f"[dim]{pinned}[/dim]" if pinned != "latest" else f"[blue]{pinned}[/blue]"

        if res.error is not None:
            table.add_row(
                res.display_name,
                f"[dim]{res.lock_entry.version or '-' if res.lock_entry else '-'}[/dim]",
                f"{latest_versions.get(res.lock_key) or '[dim]-[/dim]'}",
                target_str,
                f"[red]Error: {res.error}[/red]",
                "[dim]-[/dim]",
            )
            warnings_shown += 1
            continue

        installed = res.lock_entry.version if res.lock_entry else None
        latest = latest_versions.get(res.lock_key)
        resolving = res.resolved.version if res.resolved else None

        installed_str = f"[dim]{installed}[/dim]" if installed else "[yellow]Not installed[/yellow]"
        latest_str = latest if latest else "[yellow]Unknown[/yellow]"

        if installed is None:
            auto_update_str = "[green]Install[/green]"
            status_str = "[green]New Plugin[/green]"
        elif resolving != installed:
            match strategy:
                case PluginUpdateStrategy.MANUAL:
                    auto_update_str = "[yellow]None (manual mode)[/yellow]"
                case PluginUpdateStrategy.AUTO:
                    auto_update_str = "[green]Auto-Update[/green]"
                case PluginUpdateStrategy.FORCE:
                    auto_update_str = "[green]Auto-Update (forced)[/green]"

            status_str = f"[green]Update available ({resolving})[/green]"
        else:
            if latest and latest != installed:
                status_str = f"[yellow]Update available ({latest})[/yellow]"
                auto_update_str = "[dim]None (version pinned)[/dim]"
            else:
                status_str = "[dim]Up to date[/dim]"
                auto_update_str = "[dim]None (up to date)[/dim]"

        table.add_row(res.display_name, installed_str, latest_str, target_str, status_str, auto_update_str)

    console.print()
    console.print(table)

    if warnings_shown > 0:
        console.print(f"\n[red]Encountered {warnings_shown} error(s) during check.[/red]")


async def check_plugin_updates(config: Config) -> None:
    """Check for plugin updates and print a visual summary."""
    log_phase("Checking for Plugin Updates")

    if not config.plugin_specs:
        console.print("[yellow]No plugins configured.[/yellow]")
        return

    mc_version = await _resolve_mc_version(config)
    if mc_version is None:
        return

    lock_path = config.plugins_dir.parent / SERVER_LOCK_FILENAME
    lockfile = ServerLockfile.load(lock_path)

    console.print("Resolving plugins... (this might take a few seconds)")

    async with create_http_client() as client:
        resolutions = await resolve_all_plugins(config.plugin_specs, config.platform, mc_version, lockfile, client)
        latest_versions = await _resolve_latest_versions(resolutions, config.platform, mc_version, client)

    _print_update_table(resolutions, latest_versions, config.plugins_update_strategy)
