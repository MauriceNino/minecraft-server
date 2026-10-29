from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from orchestrator import __version__


class PlatformType(StrEnum):
    PAPER = "PAPER"
    FOLIA = "FOLIA"
    VELOCITY = "VELOCITY"
    WATERFALL = "WATERFALL"
    VANILLA = "VANILLA"
    BUKKIT = "BUKKIT"
    SPIGOT = "SPIGOT"
    PUMPKIN = "PUMPKIN"
    PURPUR = "PURPUR"


class PluginProviderType(StrEnum):
    MODRINTH = "modrinth"
    HANGAR = "hangar"
    SPIGET = "spiget"
    CURSEFORGE = "curseforge"
    GITHUB = "github"
    URL = "url"


class PluginUpdateStrategy(StrEnum):
    FORCE = "force"
    AUTO = "auto"
    MANUAL = "manual"


SERVER_PLATFORMS = frozenset(
    {
        PlatformType.PAPER,
        PlatformType.FOLIA,
        PlatformType.VANILLA,
        PlatformType.BUKKIT,
        PlatformType.SPIGOT,
        PlatformType.PUMPKIN,
        PlatformType.PURPUR,
    }
)

PROXY_PLATFORMS = frozenset(
    {
        PlatformType.VELOCITY,
        PlatformType.WATERFALL,
    }
)

BUKKIT_BASED_PLATFORMS = frozenset(
    {
        PlatformType.PAPER,
        PlatformType.FOLIA,
        PlatformType.SPIGOT,
        PlatformType.BUKKIT,
        PlatformType.PUMPKIN,
        PlatformType.PURPUR,
    }
)

PLUGIN_PLATFORMS = BUKKIT_BASED_PLATFORMS | PROXY_PLATFORMS

# Loader tags used by Modrinth to filter compatible versions, in order of preference
MODRINTH_PLATFORM_TAGS: dict[PlatformType, list[str]] = {
    PlatformType.PAPER: ["paper", "spigot", "bukkit"],
    PlatformType.FOLIA: ["folia"],
    PlatformType.VELOCITY: ["velocity"],
    PlatformType.WATERFALL: ["waterfall", "bungeecord"],
    PlatformType.SPIGOT: ["spigot", "bukkit"],
    PlatformType.BUKKIT: ["bukkit"],
    PlatformType.PUMPKIN: ["paper", "spigot", "bukkit"],
    PlatformType.PURPUR: ["purpur", "paper", "spigot", "bukkit"],
}

# Hangar only knows PAPER, VELOCITY and WATERFALL
HANGAR_PLATFORM_TAGS: dict[PlatformType, str] = {
    PlatformType.PAPER: "PAPER",
    PlatformType.FOLIA: "PAPER",
    PlatformType.PURPUR: "PAPER",
    PlatformType.VELOCITY: "VELOCITY",
    PlatformType.WATERFALL: "WATERFALL",
}

DEFAULT_DATA_DIR = Path("/data")
TEMPLATES_SUBDIR = "templates"
RUNTIME_SUBDIR = "runtime"

SERVER_LOCK_FILENAME = "server-lock.json"
# Written next to the server files so `mc-rcon` can connect when RCON_PASSWORD was auto-generated
RCON_PASSWORD_FILENAME = ".rcon-password"  # noqa: S105

USER_AGENT = f"MauriceNino/minecraft-server/{__version__} (https://github.com/MauriceNino/minecraft-server)"

# RCON bridge plugins for proxies
VELOCIRCON_URL = "https://github.com/code-lime/Velocircon/releases/download/1.0.7/Velocircon-1.0.7.jar"
BUNGEE_RCON_URL = "https://github.com/orblazer/bungee-rcon/releases/download/v1.0.0/bungee-rcon-1.0.0.jar"
