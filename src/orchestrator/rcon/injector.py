from __future__ import annotations

from pathlib import Path

from orchestrator.constants import SERVER_PLATFORMS, PlatformType
from orchestrator.logging import console
from orchestrator.merger.properties_merger import merge_properties
from orchestrator.merger.toml_merger import merge_toml
from orchestrator.merger.yaml_merger import merge_yaml


async def inject_rcon(
    platform: PlatformType,
    runtime_dir: Path,
    plugins_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Inject RCON configuration for the given platform."""
    if platform == PlatformType.PUMPKIN:
        await _inject_pumpkin_rcon(runtime_dir, rcon_port, rcon_password)
    elif platform in SERVER_PLATFORMS:
        await _inject_server_properties_rcon(runtime_dir, rcon_port, rcon_password)
    elif platform == PlatformType.VELOCITY:
        await _inject_velocity_rcon(plugins_dir, rcon_port, rcon_password)
    elif platform == PlatformType.WATERFALL:
        await _inject_waterfall_rcon(plugins_dir, rcon_port, rcon_password)

    console.print(f"  [success]✓[/success] Enabled & Reachable  [label][dim]0.0.0.0:[/dim]{rcon_port}[/label]")


async def _inject_pumpkin_rcon(
    runtime_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Enable RCON in `config/features.toml` for PumpkinMC."""
    config_dir = runtime_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "features.toml"

    config_content = (
        f"[networking.rcon]\nenabled = true\naddress = '0.0.0.0:{rcon_port}'\npassword = '{rcon_password}'\n"
    )
    merge_toml(config_file, config_content)


async def _inject_server_properties_rcon(
    runtime_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Enable RCON in `server.properties`."""
    rcon_config = f"enable-rcon=true\nrcon.port={rcon_port}\nrcon.password={rcon_password}\n"
    server_props = runtime_dir / "server.properties"
    merge_properties(server_props, rcon_config)


async def _inject_velocity_rcon(
    plugins_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Write Velocircon config,"""
    config_dir = plugins_dir / "velocircon"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "rcon.yml"

    config_content = f"enable: true\nhost: 0.0.0.0\nport: {rcon_port}\npassword: {rcon_password}\ncolors: false\n"
    merge_yaml(config_file, config_content)


async def _inject_waterfall_rcon(
    plugins_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Write bungee-rcon config,"""
    config_dir = plugins_dir / "bungee-rcon"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yml"

    config_content = f"port: {rcon_port}\npassword: {rcon_password}\ncolored: false\n"
    merge_yaml(config_file, config_content)
