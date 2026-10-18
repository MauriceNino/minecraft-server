from __future__ import annotations

import asyncio
import sys
import tempfile
from collections.abc import Coroutine
from typing import Any

import click

from orchestrator.cli import Config, load_config
from orchestrator.constants import (
    PLUGIN_PLATFORMS,
    SERVER_LOCK_FILENAME,
    SERVER_PLATFORMS,
    PlatformType,
    PluginUpdateStrategy,
)
from orchestrator.fs_orchestrator import orchestrate_templates
from orchestrator.lockfile import ServerLockfile, make_lock_key
from orchestrator.logging import (
    console,
    log_exception,
    log_header,
    log_phase,
    phase_console,
    setup_logging,
)
from orchestrator.merger import apply_config_overrides
from orchestrator.plugins import download_plugins
from orchestrator.plugins.check import check_plugin_updates
from orchestrator.providers import prepare_platform, resolve_platform
from orchestrator.rcon import inject_rcon
from orchestrator.runner import exec_server


def _accept_eula(config: Config) -> None:
    eula_path = config.runtime_dir / "eula.txt"
    if config.accept_eula:
        eula_path.write_text("# Auto-accepted by MauriceNino/minecraft-server\neula=true\n")
        console.print("  [success]✓[/success] [label]eula.txt[/label]  [dim]accepted[/dim]")
    else:
        console.print()
        console.print("  [error]✗ EULA not accepted![/error]")
        console.print()
        console.print(
            "  Minecraft requires you to accept the EULA before the server can start.\n"
            "  Read the EULA at: [url]https://aka.ms/MinecraftEULA[/url]\n"
            "\n"
            "  To accept, set the environment variable:\n"
            "    [bold]ACCEPT_EULA=true[/bold]"
        )
        console.print()
        sys.exit(1)


def _check_permissions(config: Config) -> None:
    try:
        config.runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=config.runtime_dir, prefix=".perm_test_"):
            pass
    except OSError:
        console.print()
        console.print("  [error]✗ Permission Denied: Runtime Directory[/error]")
        console.print()
        console.print(
            f"  The orchestrator cannot write to the data directory: [path]{config.runtime_dir}[/path]\n"
            "  This usually occurs when Docker bind mounts create directories owned by root.\n"
            "\n"
            "  [bold]To fix this, run the following command on your host:[/bold]\n"
            "    sudo chown -R 1000:1000 /path/to/your/data"
        )
        console.print()
        sys.exit(1)


def _run_async(coro: Coroutine[Any, Any, None], error_context: str) -> None:
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("  [error]✗ Interrupted — shutting down[/error]")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        log_exception(e, f"Fatal error during {error_context}")
        sys.exit(1)


def _apply_templates_and_overrides(config: Config) -> None:
    if config.applied_templates:
        orchestrate_templates(
            templates_dir=config.templates_dir,
            runtime_dir=config.runtime_dir,
            applied_templates=config.applied_templates,
        )
    if config.config_overrides:
        apply_config_overrides(config.config_overrides, config.runtime_dir)


async def _async_main() -> None:
    config = load_config()
    setup_logging(verbose=config.verbose)

    console.print()
    log_header("⚡ Orchestrating")
    console.print()
    phase_console.print(
        f"[dim]Platform:[/dim] [platform]{config.platform.value}[/platform]  "
        f"[dim]|[/dim]  [dim]Version:[/dim] {config.version}  "
        f"[dim]|[/dim]  [dim]Build:[/dim] {config.build}",
        justify="center",
    )
    console.print()
    _check_permissions(config)
    lockfile = ServerLockfile.load(config.runtime_dir / SERVER_LOCK_FILENAME)

    log_phase("Platform JAR")
    server_executable, mc_version, offline = await prepare_platform(
        runtime_dir=config.runtime_dir,
        platform_type=config.platform,
        version=config.version,
        build=config.build,
        lockfile=lockfile,
    )

    if config.applied_templates or config.config_overrides:
        log_phase("Templates & Configs")
        _apply_templates_and_overrides(config)

    if (config.plugin_specs or lockfile.plugins) and config.platform in PLUGIN_PLATFORMS:
        log_phase("Plugins")
        await download_plugins(
            plugin_specs=config.plugin_specs,
            platform_type=config.platform,
            mc_version=mc_version,
            plugins_dir=config.plugins_dir,
            lockfile=lockfile,
            strategy=config.plugins_update_strategy,
            check_cache_seconds=config.plugins_check_cache_seconds,
            offline=offline,
        )

    if config.rcon_enabled:
        log_phase("RCON")
        inject_rcon(
            platform=config.platform,
            runtime_dir=config.runtime_dir,
            plugins_dir=config.plugins_dir,
            rcon_port=config.rcon_port,
            rcon_password=config.rcon_password,
        )

    if config.platform in SERVER_PLATFORMS and config.platform != PlatformType.PUMPKIN:
        log_phase("Eula")
        _accept_eula(config)

    log_phase("Launching Server")
    exec_server(
        server_executable=server_executable,
        runtime_dir=config.runtime_dir,
        memory=config.memory,
        jvm_flags=config.jvm_flags,
        platform=config.platform,
    )


async def _async_reapply() -> None:
    config = load_config()
    setup_logging(verbose=config.verbose)
    _check_permissions(config)

    if not config.applied_templates and not config.config_overrides:
        console.print("[yellow]No templates or config overrides configured.[/yellow]")
        return

    log_phase("Reapplying Templates & Configs")
    _apply_templates_and_overrides(config)

    console.print()
    console.print("  [success]✓[/success] Successfully reapplied templates and configs!")


async def _async_check_updates() -> None:
    config = load_config()
    setup_logging(verbose=config.verbose)
    await check_plugin_updates(config)


async def _async_update(target_plugin: str | None = None) -> None:
    config = load_config()
    setup_logging(verbose=config.verbose)

    if config.platform not in PLUGIN_PLATFORMS:
        console.print(f"[yellow]{config.platform.value} does not support plugins.[/yellow]")
        return

    if target_plugin and not any(make_lock_key(s.provider, s.identifier) == target_plugin for s in config.plugin_specs):
        console.print(
            f"  [error]✗ Plugin '{target_plugin}' not found in configuration."
            f" Use a valid lock-key (e.g. [info]modrinth:luckperms[/info])[/error]"
        )
        sys.exit(1)

    _check_permissions(config)
    lockfile = ServerLockfile.load(config.runtime_dir / SERVER_LOCK_FILENAME)

    log_header("⚡ Updating Plugins")
    console.print()

    # The Minecraft version is needed for compatibility checks
    log_phase("Platform JAR")
    resolved_version = await resolve_platform(
        platform_type=config.platform,
        version=config.version,
        build=config.build,
    )

    log_phase("Plugins")
    failures = await download_plugins(
        plugin_specs=config.plugin_specs,
        platform_type=config.platform,
        mc_version=resolved_version.version,
        plugins_dir=config.plugins_dir,
        lockfile=lockfile,
        # Update every plugin that can be updated, even if others fail
        strategy=PluginUpdateStrategy.AUTO,
        check_cache_seconds=0,
        target_plugin=target_plugin,
    )

    console.print()
    if failures:
        console.print(f"  [error]✗ {len(failures)} plugin(s) could not be updated[/error]")
        sys.exit(1)
    console.print("  [success]✓[/success] Successfully updated plugins!")


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Prepare the server and start it. Subcommands are meant to be run inside a running container."""
    if ctx.invoked_subcommand is None:
        _run_async(_async_main(), "orchestration")


@cli.command("reapply")
def reapply_cmd() -> None:
    """Re-apply templates and CONFIG_* overrides to the runtime directory."""
    _run_async(_async_reapply(), "reapply")


@cli.command("check-updates")
def check_updates_cmd() -> None:
    """Show which plugins have updates available."""
    _run_async(_async_check_updates(), "check-updates")


@cli.command("update")
@click.option("--plugin", "-p", help="Update a single plugin by its lockfile entry (e.g. modrinth:luckperms)")
def update_cmd(plugin: str | None) -> None:
    """Download plugin updates. Restart the server afterwards to load them."""
    _run_async(_async_update(plugin), "update")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
