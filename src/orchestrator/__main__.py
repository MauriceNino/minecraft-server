from __future__ import annotations

import asyncio
import sys

import click

from orchestrator.cli import Config, load_config
from orchestrator.constants import SERVER_LOCK_FILENAME, PlatformType
from orchestrator.fs_orchestrator import orchestrate_templates
from orchestrator.logging import (
    console,
    get_logger,
    log_exception,
    log_header,
    log_phase,
    phase_console,
    setup_logging,
)
from orchestrator.merger import apply_config_overrides
from orchestrator.plugins import ServerLockfile, download_plugins
from orchestrator.plugins.check import check_plugin_updates
from orchestrator.providers import download_platform, resolve_platform
from orchestrator.rcon import inject_rcon
from orchestrator.runner import exec_java

log = get_logger(__name__)


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
            "  Read the EULA at: [link]https://aka.ms/MinecraftEULA[/link]\n"
            "\n"
            "  To accept, set the environment variable:\n"
            "    [bold]ACCEPT_EULA=true[/bold]"
        )
        console.print()
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

    log_phase("Platform JAR")
    resolved_version = await resolve_platform(
        platform_type=config.platform,
        version=config.version,
        build=config.build,
    )

    server_jar = await download_platform(
        cache_dir=config.cache_dir,
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

    if config.plugin_lines:
        log_phase("Plugins")
        await download_plugins(
            plugin_lines=config.plugin_lines,
            platform_type=config.platform,
            mc_version=resolved_version.version,
            plugins_dir=config.plugins_dir,
            lockfile=lockfile,
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

    if config.platform != PlatformType.VELOCITY:
        log_phase("Eula")
        _accept_eula(config)

    log_phase("Launching Java")
    exec_java(
        server_jar=server_jar,
        runtime_dir=config.runtime_dir,
        memory=config.memory,
        jvm_flags=config.jvm_flags,
        platform=config.platform,
    )


async def _async_reapply() -> None:
    config = load_config()
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


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        try:
            asyncio.run(_async_main())
        except KeyboardInterrupt:
            log.info("Interrupted — shutting down")
            sys.exit(130)
        except SystemExit:
            raise
        except Exception as e:
            log_exception(e, "Fatal error during orchestration")
            sys.exit(1)


@cli.command("reapply")
def reapply_cmd() -> None:
    try:
        asyncio.run(_async_reapply())
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        log_exception(e, "Fatal error during reapply")
        sys.exit(1)


@cli.command("check-updates")
def check_updates_cmd() -> None:
    try:
        asyncio.run(_async_check_updates())
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        log_exception(e, "Fatal error during check-updates")
        sys.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
