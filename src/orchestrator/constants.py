from __future__ import annotations

from enum import StrEnum
from pathlib import Path


# Platform types
class PlatformType(StrEnum):
    """Supported Minecraft server / proxy platform types."""

    PAPER = "PAPER"
    FOLIA = "FOLIA"
    VELOCITY = "VELOCITY"


# Plugin provider identifiers
class PluginProviderType(StrEnum):
    """Supported plugin download providers."""

    MODRINTH = "modrinth"
    HANGAR = "hangar"
    SPIGET = "spiget"
    URL = "url"


# Loader tags used by Modrinth / Hangar to filter compatible versions
PLATFORM_LOADER_TAGS: dict[PlatformType, list[str]] = {
    PlatformType.PAPER: ["paper", "spigot", "bukkit"],
    PlatformType.FOLIA: ["folia", "paper"],
    PlatformType.VELOCITY: ["velocity"],
}

# Hangar uses its own platform enum
PLATFORM_HANGAR_TAGS: dict[PlatformType, str] = {
    PlatformType.PAPER: "PAPER",
    PlatformType.FOLIA: "PAPER",
    PlatformType.VELOCITY: "VELOCITY",
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
    }
)

# User-Agent for HTTP requests
USER_AGENT = "MauriceNino/minecraft-server/1.0 (https://github.com/MauriceNino/minecraft-server)"
