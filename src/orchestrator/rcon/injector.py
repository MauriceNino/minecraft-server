from __future__ import annotations

import json
import os
from pathlib import Path

from orchestrator.constants import BUNGEE_PLATFORMS, RCON_PASSWORD_FILENAME, SERVER_PLATFORMS, PlatformType
from orchestrator.logging import console
from orchestrator.merger import merge_file_content
from orchestrator.merger.properties_merger import escape_properties_value


def inject_rcon(
    platform: PlatformType,
    runtime_dir: Path,
    plugins_dir: Path,
    rcon_port: int,
    rcon_password: str,
) -> None:
    """Enable RCON in the platform's config files."""
    # JSON strings are valid YAML and TOML strings, which keeps passwords with special characters intact
    password = json.dumps(rcon_password)

    if platform == PlatformType.PUMPKIN:
        merge_file_content(
            runtime_dir / "config" / "features.toml",
            f'[networking.rcon]\nenabled = true\naddress = "0.0.0.0:{rcon_port}"\npassword = {password}\n',
        )
    elif platform in SERVER_PLATFORMS:
        merge_file_content(
            runtime_dir / "server.properties",
            f"enable-rcon=true\nrcon.port={rcon_port}\nrcon.password={escape_properties_value(rcon_password)}\n",
        )
    elif platform == PlatformType.VELOCITY:
        merge_file_content(
            plugins_dir / "velocircon" / "rcon.yml",
            f"enable: true\nhost: 0.0.0.0\nport: {rcon_port}\npassword: {password}\ncolors: true\n",
        )
    elif platform in BUNGEE_PLATFORMS:
        merge_file_content(
            plugins_dir / "bungee-rcon" / "config.yml",
            f"port: {rcon_port}\npassword: {password}\ncolored: true\n",
        )

    _write_password_file(runtime_dir / RCON_PASSWORD_FILENAME, rcon_password)
    console.print(f"  [success]✓[/success] Enabled on port [label]{rcon_port}[/label]")


def _write_password_file(path: Path, password: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(password)
