from __future__ import annotations

from pathlib import Path

from orchestrator.constants import PlatformType
from orchestrator.logging import console
from orchestrator.merger.properties_merger import merge_properties
from orchestrator.merger.yaml_merger import merge_yaml

# Velocircon release URL (Velocity RCON bridge plugin)
VELOCIRCON_URL = "https://github.com/code-lime/Velocircon/releases/download/1.0.6/Velocircon-1.0.6.jar"


async def inject_rcon(
    platform: PlatformType,
    runtime_dir: Path,
    plugins_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Detect platform and inject RCON configuration.

    Strategy per platform:

    - **Paper / Folia**: Enable via `server.properties`.
    - **Velocity**: Download Velocircon plugin and generate its config.
    """
    if platform in (PlatformType.PAPER, PlatformType.FOLIA):
        await _inject_server_properties_rcon(runtime_dir, rcon_port, rcon_password)
    elif platform == PlatformType.VELOCITY:
        await _inject_velocity_rcon(plugins_dir, rcon_port, rcon_password)


async def _inject_server_properties_rcon(
    runtime_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Enable RCON in `server.properties`."""
    rcon_config = f"enable-rcon=true\nrcon.port={rcon_port}\nrcon.password={rcon_password}\n"
    server_props = runtime_dir / "server.properties"
    console.print(f"  [success]✓[/success] Enabled & Reachable  [label][dim]0.0.0.0:[/dim]{rcon_port}[/label]")
    merge_properties(server_props, rcon_config)


async def _inject_velocity_rcon(
    plugins_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Download Velocircon and write its config."""
    import httpx

    from orchestrator.constants import USER_AGENT

    # Download Velocircon plugin
    velocircon_jar = plugins_dir / "Velocircon.jar"
    if not velocircon_jar.exists():
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(VELOCIRCON_URL)
            resp.raise_for_status()
            plugins_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
            velocircon_jar.write_bytes(resp.content)
            console.print("  [success]✓[/success] Downloaded [label]Velocircon[/label]")
    else:
        console.print("  [cached]✓[/cached] Cached [label]Velocircon[/label]")

    # Write Velocircon config
    config_dir = plugins_dir / "velocircon"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "rcon.yml"

    config_content = f"enable: true\nhost: 0.0.0.0\nport: {rcon_port}\npassword: {rcon_password}\ncolors: false\n"
    console.print(f"  [success]✓[/success] Enabled & Reachable  [label][dim]0.0.0.0:[/dim]{rcon_port}[/label]")
    merge_yaml(config_file, config_content)
