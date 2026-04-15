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


# Plugin provider identifiers
class PluginProviderType(StrEnum):
    """Supported plugin download providers."""

    MODRINTH = "modrinth"
    HANGAR = "hangar"
    SPIGET = "spiget"
    URL = "url"
    GITHUB = "github"
    CURSEFORGE = "curseforge"


# Loader tags used by Modrinth / Hangar / CurseForge to filter compatible versions
PLATFORM_LOADER_TAGS: dict[PlatformType, list[str]] = {
    PlatformType.PAPER: ["paper", "spigot", "bukkit"],
    PlatformType.FOLIA: ["folia", "paper"],
    PlatformType.VELOCITY: ["velocity"],
    PlatformType.WATERFALL: ["waterfall", "bungeecord"],
    PlatformType.VANILLA: ["vanilla"],
    PlatformType.SPIGOT: ["spigot", "bukkit"],
    PlatformType.BUKKIT: ["bukkit"],
    PlatformType.PUMPKIN: ["paper", "spigot", "bukkit"],
    PlatformType.PURPUR: ["purpur", "paper", "spigot", "bukkit"],
}

# Hangar uses its own platform enum
PLATFORM_HANGAR_TAGS: dict[PlatformType, str] = {
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
