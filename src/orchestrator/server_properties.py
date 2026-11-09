"""Environment variable shortcuts for the most common `server.properties` settings."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from orchestrator.constants import SERVER_PLATFORMS, PlatformType
from orchestrator.logging import log_change
from orchestrator.merger.properties_merger import escape_properties_value, merge_properties

SERVER_PROPERTIES_FILENAME = "server.properties"

# Environment variable -> property. Everything else goes through CONFIG_PATHS or templates.
SHORTCUTS: dict[str, str] = {
    "MOTD": "motd",
    "DIFFICULTY": "difficulty",
    "GAMEMODE": "gamemode",
    "MAX_PLAYERS": "max-players",
    "VIEW_DISTANCE": "view-distance",
    "SIMULATION_DISTANCE": "simulation-distance",
    "ONLINE_MODE": "online-mode",
    "PVP": "pvp",
    "LEVEL_NAME": "level-name",
    "SEED": "level-seed",
    "SERVER_PORT": "server-port",
}

_BOOLEANS = frozenset({"ONLINE_MODE", "PVP"})
_INTEGERS = frozenset({"MAX_PLAYERS", "VIEW_DISTANCE", "SIMULATION_DISTANCE", "SERVER_PORT"})
_LOWERCASE = frozenset({"DIFFICULTY", "GAMEMODE"})


def supports_server_properties(platform: PlatformType) -> bool:
    """Java servers read `server.properties`, proxies and Pumpkin have their own config files."""
    return platform in SERVER_PLATFORMS and platform != PlatformType.PUMPKIN


def collect_server_properties(env: Mapping[str, str], platform: PlatformType) -> dict[str, str]:
    """The properties set by shortcut variables, raising ValueError for invalid values."""
    if not supports_server_properties(platform):
        return {}

    result: dict[str, str] = {}
    for var, prop in SHORTCUTS.items():
        raw = env.get(var)
        if raw is None or not raw.strip():
            continue
        value = raw.strip()
        if var in _BOOLEANS:
            if value.lower() not in ("true", "false"):
                raise ValueError(f"Invalid {var}={raw!r}: use true or false")
            value = value.lower()
        elif var in _INTEGERS:
            if not value.isdigit():
                raise ValueError(f"Invalid {var}={raw!r}: must be a whole number")
        elif var in _LOWERCASE:
            value = value.lower()
        result[prop] = value
    return result


def apply_server_properties(properties: dict[str, str], runtime_dir: Path) -> None:
    """Merge *properties* into `server.properties`, creating it on the first start."""
    content = "".join(f"{key}={escape_properties_value(value)}\n" for key, value in properties.items())
    merge_properties(runtime_dir / SERVER_PROPERTIES_FILENAME, content)
    log_change("merged", SERVER_PROPERTIES_FILENAME, reason=", ".join(properties))
