from __future__ import annotations

import asyncio

import httpx
from rich.table import Table

from orchestrator.cli import Config
from orchestrator.constants import SERVER_LOCK_FILENAME, USER_AGENT, PluginUpdateStrategy
from orchestrator.lockfile import ServerLockfile, make_lock_key
from orchestrator.logging import console, log_exception, log_phase
from orchestrator.plugins import _build_providers
from orchestrator.plugins.base import PluginSpec
from orchestrator.plugins.resolver import parse_plugin_lines
from orchestrator.providers import get_platform_provider


async def check_plugin_updates(config: Config) -> None:
    """Check for plugin updates and print a visual summary."""
    log_phase("Checking for Plugin Updates")
    if not config.plugin_lines:
        console.print("[yellow]No plugins configured in PLUGINS line.[/yellow]")
        return

    # First, we need to resolve the platform version, as plugin compatibility depends on it.
    platform_provider = get_platform_provider(config.platform)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            platform_resolved = await platform_provider.resolve_version(config.version, config.build, client)
            mc_version = platform_resolved.version
            console.print(
                f"Platform: [platform]{config.platform.value}[/platform] "
                f"/ Version: [version.new]{mc_version}[/version.new]"
            )
        except Exception as e:
            log_exception(e, "Failed to resolve platform version")
            return

        specs = parse_plugin_lines(config.plugin_lines)
        plugins_dir = config.plugins_dir
        lock_path = plugins_dir.parent / SERVER_LOCK_FILENAME
        lockfile = ServerLockfile.load(lock_path)

        providers = _build_providers()

        # Build tasks to resolve versions concurrently
        async def check_spec(spec: PluginSpec):  # noqa: ANN202
            provider = providers.get(spec.provider)
            if not provider:
                return {"spec": spec, "error": f"Unknown provider {spec.provider}"}

            lock_key = make_lock_key(spec.provider, spec.identifier)
            lock_entry = lockfile.plugins.get(lock_key)
            installed_version = lock_entry.version if lock_entry else None

            # Resolve the spec as requested by the user
            try:
                resolved_current = await provider.resolve(spec, config.platform, mc_version, client)
                actual_installing_version = resolved_current.version
                display_name = resolved_current.display_name
            except Exception as e:
                # Fallback if we cannot resolve what the user actually wants
                actual_installing_version = None
                display_name = spec.identifier
                error = str(e)
                return {"spec": spec, "error": error, "installed": installed_version, "display_name": display_name}

            # Now, resolve dummy spec to find "latest" version
            latest_spec = PluginSpec(
                provider=spec.provider, identifier=spec.identifier, version="latest", force=spec.force
            )
            try:
                resolved_latest = await provider.resolve(latest_spec, config.platform, mc_version, client)
                latest_version = resolved_latest.version
            except Exception:
                latest_version = None

            return {
                "spec": spec,
                "display_name": display_name,
                "installed": installed_version,
                "actual_resolving": actual_installing_version,
                "latest": latest_version,
            }

        console.print("Resolving plugins... (this might take a few seconds)")
        results = await asyncio.gather(*(check_spec(spec) for spec in specs))

    # Build the Rich table
    table = Table(title="Plugin Update Status", show_header=True, header_style="bold magenta")
    table.add_column("Plugin Name")
    table.add_column("Installed")
    table.add_column("Latest")
    table.add_column("Pinned Target")
    table.add_column("Update Status")
    table.add_column(f"Action on next restart? [dim](strategy: {config.plugins_update_strategy})[/dim]")

    warnings_shown = 0

    for res in sorted(results, key=lambda x: x.get("display_name", x["spec"].identifier).lower()):
        display_name = res.get("display_name", res["spec"].identifier)
        if "error" in res:
            table.add_row(display_name, "-", "-", res["spec"].version, f"[red]Error: {res['error']}[/red]", "-")
            warnings_shown += 1
            continue

        installed = res["installed"]
        latest = res["latest"]
        resolving = res["actual_resolving"]
        pinned = res["spec"].version

        installed_str = f"[dim]{installed}[/dim]" if installed else "[yellow]Not installed[/yellow]"
        latest_str = latest if latest else "[yellow]Unknown[/yellow]"

        if installed is None:
            auto_update_str = "[cyan]Yes (Will Install)[/cyan]"
            status_str = "[cyan]New Plugin[/cyan]"
        else:
            if resolving != installed:
                match config.plugins_update_strategy:
                    case PluginUpdateStrategy.MANUAL:
                        auto_update_str = "[yellow]No (manual mode)[/yellow]"
                    case PluginUpdateStrategy.AUTO:
                        auto_update_str = "[green]Yes[/green]"
                    case PluginUpdateStrategy.FORCE:
                        auto_update_str = "[bold green]Yes (force)[/bold green]"

                status_str = f"[green]Update available[/green] -> {resolving}"
            else:
                auto_update_str = "[dim]No (up to date)[/dim]"
                if latest and latest != installed:
                    # User requested something pinned maybe?
                    if pinned.lower() == "latest":
                        status_str = "[yellow]Update available, but not compatible?[/yellow]"
                    else:
                        status_str = f"[yellow]Newer version available ({latest})[/yellow]"
                else:
                    status_str = "[dim]Up to date[/dim]"

        # Highlight if user pinned to something old
        target_str = f"[dim]{pinned}[/dim]" if pinned != "latest" else f"[blue]{pinned}[/blue]"

        table.add_row(display_name, installed_str, latest_str, target_str, status_str, auto_update_str)

    console.print()
    console.print(table)

    if warnings_shown > 0:
        console.print(f"\n[red]Encountered {warnings_shown} error(s) during check.[/red]")
