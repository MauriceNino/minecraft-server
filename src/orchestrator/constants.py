from __future__ import annotations

from enum import StrEnum
from pathlib import Path


# Platform types
class PlatformType(StrEnum):
    """Supported Minecraft server / proxy platform types."""

    PAPER = "PAPER"
    FOLIA = "FOLIA"
    VELOCITY = "VELOCITY"
    WATERFALL = "WATERFALL"
    VANILLA = "VANILLA"
    BUKKIT = "BUKKIT"
    SPIGOT = "SPIGOT"
    PUMPKIN = "PUMPKIN"
    PURPUR = "PURPUR"


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

PLUGIN_PLATFORMS = frozenset(
    {
        PlatformType.PAPER,
        PlatformType.FOLIA,
        PlatformType.VELOCITY,
        PlatformType.WATERFALL,
        PlatformType.SPIGOT,
        PlatformType.BUKKIT,
        PlatformType.PUMPKIN,
        PlatformType.PURPUR,
    }
)

# Loader tags used by Modrinth to filter compatible versions
MODRINTH_PLATFORM_TAGS: dict[PlatformType, list[str]] = {
    PlatformType.PAPER: ["paper", "spigot", "bukkit"],
    PlatformType.FOLIA: ["folia", "paper"],
    PlatformType.VELOCITY: ["velocity"],
    PlatformType.WATERFALL: ["waterfall", "bungeecord"],
    PlatformType.SPIGOT: ["spigot", "bukkit"],
    PlatformType.BUKKIT: ["bukkit"],
    PlatformType.PUMPKIN: ["paper", "spigot", "bukkit"],
    PlatformType.PURPUR: ["purpur", "paper", "spigot", "bukkit"],
}

# Hangar uses its own platform enum
HANGAR_PLATFORM_TAGS: dict[PlatformType, str] = {
    PlatformType.PAPER: "PAPER",
    PlatformType.FOLIA: "PAPER",
    PlatformType.VELOCITY: "VELOCITY",
    PlatformType.WATERFALL: "WATERFALL",
}


# Directory layout (inside the container / working directory)
DEFAULT_DATA_DIR = Path("/data")

TEMPLATES_SUBDIR = "templates"
RUNTIME_SUBDIR = "runtime"
PLUGINS_SUBDIR = "plugins"
CACHE_SUBDIR = ".cache"

SERVER_LOCK_FILENAME = "server-lock.json"

# Config file extensions that can be deep-merged
MERGEABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".yml",
        ".yaml",
        ".json",
        ".toml",
        ".properties",
        ".conf",
    }
)

# User-Agent for HTTP requests
USER_AGENT = "MauriceNino/minecraft-server/1.0 (https://github.com/MauriceNino/minecraft-server)"


# RCON Bridge Plugins for Proxies
VELOCIRCON_URL = "https://github.com/code-lime/Velocircon/releases/download/1.0.6/Velocircon-1.0.6.jar"
BUNGEE_RCON_URL = "https://github.com/orblazer/bungee-rcon/releases/download/v1.0.0/bungee-rcon-1.0.0.jar"
