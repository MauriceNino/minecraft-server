from __future__ import annotations

import asyncio
import sys
import tempfile
from collections.abc import Callable, Coroutine
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
from orchestrator.lockfile import ServerLockfile
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
from orchestrator.providers import download_platform, resolve_platform
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
    """Verify that the orchestrator has write access to the data directory."""
    try:
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
            f"    sudo chown -R 1000:1000 /path/to/your/data"
        )
        console.print()
        sys.exit(1)


def _run_async(coro_factory: Callable[[], Coroutine[Any, Any, None]], error_context: str) -> None:
    """Run an async entry-point with standardised error handling."""
    try:
        asyncio.run(coro_factory())
    except KeyboardInterrupt:
        console.print("  [error]✗ Interrupted — shutting down[/error]")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        log_exception(e, f"Fatal error during {error_context}")
        sys.exit(1)


async def _async_main() -> None:
    config = load_config()
    lockfile = ServerLockfile.load(config.runtime_dir / SERVER_LOCK_FILENAME)
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

    log_phase("Platform JAR")
    resolved_version = await resolve_platform(
        platform_type=config.platform,
        version=config.version,
        build=config.build,
    )

    server_executable = await download_platform(
        runtime_dir=config.runtime_dir,
        platform_type=config.platform,
        resolved_version=resolved_version,
        lockfile=lockfile,
    )

    if config.applied_templates or config.config_overrides:
        log_phase("Templates & Configs")
        if config.applied_templates:
            orchestrate_templates(
                templates_dir=config.templates_dir,
                runtime_dir=config.runtime_dir,
                applied_templates=config.applied_templates,
            )
        if config.config_overrides:
            apply_config_overrides(config.config_overrides, config.runtime_dir)

    if (len(config.plugin_specs) > 0 or len(lockfile.plugins.keys()) > 0) and config.platform in PLUGIN_PLATFORMS:
        log_phase("Plugins")
        await download_plugins(
            plugin_specs=config.plugin_specs,
            platform_type=config.platform,
            mc_version=resolved_version.version,
            plugins_dir=config.plugins_dir,
            lockfile=lockfile,
            strategy=config.plugins_update_strategy,
            check_cache_seconds=config.plugins_check_cache_seconds,
        )

    if config.rcon_enabled:
        log_phase("RCON")
        await inject_rcon(
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
    _check_permissions(config)
    setup_logging(verbose=config.verbose)

    if not config.applied_templates and not config.config_overrides:
        console.print("[yellow]No templates or config overrides configured.[/yellow]")
        return

    log_phase("Reapplying Templates & Configs")
    if config.applied_templates:
        orchestrate_templates(
            templates_dir=config.templates_dir,
            runtime_dir=config.runtime_dir,
            applied_templates=config.applied_templates,
        )
    if config.config_overrides:
        apply_config_overrides(config.config_overrides, config.runtime_dir)

    console.print()
    console.print("  [success]✓[/success] Successfully reapplied templates and configs!")


async def _async_check_updates() -> None:
    config = load_config()
    setup_logging(verbose=config.verbose)
    await check_plugin_updates(config)


async def _async_update() -> None:
    config = load_config()
    lockfile = ServerLockfile.load(config.runtime_dir / SERVER_LOCK_FILENAME)
    setup_logging(verbose=config.verbose)

    log_header("⚡ Updating Plugins")
    console.print()

    # We need the platform version for compatibility checks
    log_phase("Platform JAR")
    resolved_version = await resolve_platform(
        platform_type=config.platform,
        version=config.version,
        build=config.build,
    )

    if config.platform in PLUGIN_PLATFORMS:
        log_phase("Plugins")
        await download_plugins(
            plugin_specs=config.plugin_specs,
            platform_type=config.platform,
            mc_version=resolved_version.version,
            plugins_dir=config.plugins_dir,
            lockfile=lockfile,
            # Ignoring errors during update command
            strategy=PluginUpdateStrategy.AUTO,
            check_cache_seconds=0,
        )

    console.print()
    console.print("  [success]✓[/success] Successfully updated plugins!")


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        _run_async(_async_main, "orchestration")


@cli.command("reapply")
def reapply_cmd() -> None:
    _run_async(_async_reapply, "reapply")


@cli.command("check-updates")
def check_updates_cmd() -> None:
    _run_async(_async_check_updates, "check-updates")


@cli.command("update")
def update_cmd() -> None:
    _run_async(_async_update, "update")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
