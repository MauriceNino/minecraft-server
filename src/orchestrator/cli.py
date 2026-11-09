from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from orchestrator.constants import (
    BUNGEE_PLATFORMS,
    BUNGEE_RCON_URL,
    DEFAULT_DATA_DIR,
    PROXY_PLATFORMS,
    RUNTIME_SUBDIR,
    SERVER_PLATFORMS,
    TEMPLATES_SUBDIR,
    VELOCIRCON_URL,
    PlatformType,
    PluginProviderType,
    PluginUpdateStrategy,
)
from orchestrator.http import ApiTokens
from orchestrator.plugins.base import PluginSpec
from orchestrator.server_properties import collect_server_properties
from orchestrator.sigils import DirSigil, parse_dir_sigil

# Aikar's flags (https://docs.papermc.io/paper/aikars-flags)
_DEFAULT_SERVER_JVM_FLAGS = [
    "--add-modules=jdk.incubator.vector",
    "-XX:+UseG1GC",
    "-XX:+ParallelRefProcEnabled",
    "-XX:MaxGCPauseMillis=200",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:+DisableExplicitGC",
    "-XX:+AlwaysPreTouch",
    "-XX:G1HeapWastePercent=5",
    "-XX:G1MixedGCCountTarget=4",
    "-XX:InitiatingHeapOccupancyPercent=15",
    "-XX:G1MixedGCLiveThresholdPercent=90",
    "-XX:G1RSetUpdatingPauseTimePercent=5",
    "-XX:SurvivorRatio=32",
    "-XX:+PerfDisableSharedMem",
    "-XX:MaxTenuringThreshold=1",
    "-Dusing.aikars.flags=https://mcflags.emc.gs",
    "-Daikars.new.flags=true",
    "-XX:G1NewSizePercent=30",
    "-XX:G1MaxNewSizePercent=40",
    "-XX:G1HeapRegionSize=8M",
    "-XX:G1ReservePercent=20",
]

# Aikar's values for heaps of 12G and more, replacing the flags with the same name above
_LARGE_HEAP_BYTES = 12 * 1024**3
_LARGE_HEAP_SERVER_JVM_FLAGS = {
    "-XX:G1NewSizePercent": "40",
    "-XX:G1MaxNewSizePercent": "50",
    "-XX:G1HeapRegionSize": "16M",
    "-XX:G1ReservePercent": "15",
    "-XX:InitiatingHeapOccupancyPercent": "20",
}

# Recommended by Velocity (https://docs.papermc.io/velocity/tuning)
_DEFAULT_PROXY_JVM_FLAGS = [
    "-XX:+UseG1GC",
    "-XX:G1HeapRegionSize=4M",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:+ParallelRefProcEnabled",
    "-XX:+AlwaysPreTouch",
    "-XX:MaxInlineLevel=15",
]


@dataclass(frozen=True, slots=True)
class Config:
    platform: PlatformType
    version: str
    build: str
    data_dir: Path
    templates_dir: Path
    runtime_dir: Path
    plugins_dir: Path

    plugin_specs: list[PluginSpec]
    # (sigil, path relative to the runtime dir, raw content)
    config_overrides: list[tuple[DirSigil, str, str]]
    applied_templates: list[str]
    # Set by the shortcut variables, e.g. MOTD -> motd
    server_properties: dict[str, str]

    rcon_enabled: bool
    rcon_password: str
    rcon_port: int

    memory: str
    jvm_flags: list[str]

    verbose: bool
    accept_eula: bool
    plugins_update_strategy: PluginUpdateStrategy
    plugins_check_cache_seconds: int
    api_tokens: ApiTokens


_MEMORY_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def _memory_bytes(memory: str) -> int:
    """Convert a validated `MEMORY` value like `2G` or `1536M` into bytes, as the JVM reads `-Xmx`."""
    unit = memory[-1].lower() if memory[-1].isalpha() else ""
    return int(memory.rstrip("KkMmGgTt")) * _MEMORY_UNITS[unit]


def _default_jvm_flags(platform: PlatformType, memory: str) -> list[str]:
    if platform in PROXY_PLATFORMS:
        return list(_DEFAULT_PROXY_JVM_FLAGS)
    if platform not in SERVER_PLATFORMS:
        return []
    if _memory_bytes(memory) < _LARGE_HEAP_BYTES:
        return list(_DEFAULT_SERVER_JVM_FLAGS)
    flags: list[str] = []
    for flag in _DEFAULT_SERVER_JVM_FLAGS:
        name = flag.partition("=")[0]
        flags.append(f"{name}={_LARGE_HEAP_SERVER_JVM_FLAGS[name]}" if name in _LARGE_HEAP_SERVER_JVM_FLAGS else flag)
    return flags


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def _parse_multiline(value: str) -> list[str]:
    """Split a newline-separated env var into non-empty stripped lines."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def _collect_config_overrides(
    environ: dict[str, str],
) -> list[tuple[DirSigil, str, str]]:
    """Parse `CONFIG_PATHS` + `CONFIG_<key>` env vars into override entries.

    `CONFIG_PATHS` holds one `[<sigil>]<key> -> <relative/path>` mapping per line, e.g.:

        CONFIG_PATHS: |
          !force:server_properties -> server.properties
          luckperms -> plugins/luckperms/config.yml

    The content for each line is read from `CONFIG_<key>`. Lines without content are skipped,
    except for `!delete:` lines, which don't need any. Malformed lines are skipped as well.
    """
    result: list[tuple[DirSigil, str, str]] = []

    for line in _parse_multiline(environ.get("CONFIG_PATHS", "")):
        lhs, arrow, rhs = (part.strip() for part in line.partition("->"))
        if not arrow or not lhs or not rhs:
            continue

        sigil, key = parse_dir_sigil(lhs)
        if sigil == DirSigil.DELETE:
            result.append((sigil, rhs, ""))
            continue

        raw_content = environ.get(f"CONFIG_{key}", "")
        if raw_content.strip():
            result.append((sigil, rhs, raw_content))

    return result


_DURATION_MULTIPLIERS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}


def _parse_duration(value: str) -> int:
    """Parse a duration like `30s`, `2m`, `3h` or `1d` into seconds."""
    value = value.strip().lower()
    if not value:
        raise ValueError("empty duration string")
    suffix = value[-1]
    if suffix not in _DURATION_MULTIPLIERS:
        raise ValueError(f"unsupported duration unit {suffix!r}. Use one of: s, m, h, d")
    try:
        amount = int(value[:-1])
    except ValueError:
        raise ValueError(f"invalid duration {value!r}: numeric part must be an integer") from None
    if amount < 0:
        raise ValueError(f"duration must be non-negative, got {value!r}")
    return amount * _DURATION_MULTIPLIERS[suffix]


def _normalize_version_spec(raw: str) -> str:
    """Map the `stable` and `beta` aliases to `latest` and `experimental`, leave anything else as-is."""
    lower = raw.strip().lower()
    if lower in ("latest", "stable"):
        return "latest"
    if lower in ("experimental", "beta"):
        return "experimental"
    return raw.strip()


# Params run up to the last `]`, so values like regexes may contain brackets themselves
_SPEC_RE = re.compile(
    r"^(?P<provider>[a-z]+):(?P<id>[^\[@]+?)(?:\[(?P<params>.*)\])?(?:@(?P<version>[^!@\]]+?)(?P<force>!)?)?$"
)
# Only split on commas that start a new `key=` pair, so values may contain commas
_PARAM_SEPARATOR_RE = re.compile(r",(?=\s*\w+\s*=)")


def _parse_params(raw_params: str | None) -> dict[str, str]:
    if not raw_params:
        return {}
    result: dict[str, str] = {}
    for part in _PARAM_SEPARATOR_RE.split(raw_params):
        key, sep, value = part.partition("=")
        if sep:
            result[key.strip()] = value.strip()
    return result


def _parse_plugin_spec(raw: str) -> PluginSpec:
    raw = raw.strip()
    if not raw:
        msg = "Empty plugin spec"
        raise ValueError(msg)

    match = _SPEC_RE.match(raw)
    if not match:
        msg = f"Invalid plugin spec: {raw!r}. Expected format: provider:id[params]@version"
        raise ValueError(msg)

    try:
        provider = PluginProviderType(match.group("provider"))
    except ValueError:
        valid = ", ".join(p.value for p in PluginProviderType)
        raise ValueError(f"Unknown plugin provider in {raw!r}. Valid providers: {valid}") from None

    raw_version = match.group("version") or "latest"
    return PluginSpec(
        provider=provider,
        identifier=match.group("id").strip(),
        version=_normalize_version_spec(raw_version),
        force=match.group("force") is not None,
        params=_parse_params(match.group("params")),
    )


def _parse_plugin_lines(raw: str) -> list[PluginSpec]:
    """Parse multiple plugin spec lines, skipping blanks and comments."""
    return [_parse_plugin_spec(line) for line in _parse_multiline(raw) if not line.startswith("#")]


def load_config(environ: dict[str, str] | None = None) -> Config:
    env = environ if environ is not None else dict(os.environ)

    platform_raw = env.get("TYPE", "PAPER").upper()
    try:
        platform = PlatformType(platform_raw)
    except ValueError:
        valid = ", ".join(t.value for t in PlatformType)
        msg = f"Unknown platform TYPE={platform_raw!r}. Valid options: {valid}"
        raise SystemExit(msg) from None

    version = _normalize_version_spec(env.get("VERSION", "latest"))
    build = _normalize_version_spec(env.get("BUILD", "latest"))
    if platform == PlatformType.CUSTOM:
        # The custom JAR's source is its build: it is downloaded again when it changes
        build = env.get("CUSTOM_JAR", "").strip()
        if not build:
            raise SystemExit("TYPE=CUSTOM needs CUSTOM_JAR: a URL or a path to the server JAR in the container")
    data_dir = Path(env.get("DATA_DIR", str(DEFAULT_DATA_DIR)))

    templates_dir = data_dir / TEMPLATES_SUBDIR
    runtime_dir = data_dir / RUNTIME_SUBDIR
    if platform == PlatformType.PUMPKIN:
        plugins_dir = runtime_dir / "patchbukkit" / "patchbukkit-plugins"
    else:
        plugins_dir = runtime_dir / "plugins"

    try:
        plugin_specs = _parse_plugin_lines(env.get("PLUGINS", ""))
    except ValueError as e:
        raise SystemExit(f"Invalid PLUGINS entry: {e}") from None
    applied_templates = _parse_multiline(env.get("APPLIED_TEMPLATES", ""))
    config_overrides = _collect_config_overrides(env)
    try:
        server_properties = collect_server_properties(env, platform)
    except ValueError as e:
        raise SystemExit(str(e)) from None

    rcon_enabled = _parse_bool(env.get("RCON_ENABLED", "true"))
    rcon_password = env.get("RCON_PASSWORD") or str(uuid.uuid4())
    rcon_port_raw = env.get("RCON_PORT", "25575")
    if not rcon_port_raw.strip().isdigit() or not 0 < int(rcon_port_raw) < 65536:
        raise SystemExit(f"Invalid RCON_PORT={rcon_port_raw!r}: must be a port number between 1 and 65535")
    rcon_port = int(rcon_port_raw)

    # Proxies have no built-in RCON, so a bridge plugin is installed for them
    if rcon_enabled:
        if platform == PlatformType.VELOCITY:
            plugin_specs.append(PluginSpec(PluginProviderType.URL, VELOCIRCON_URL, "latest", False, {}))
        elif platform in BUNGEE_PLATFORMS:
            plugin_specs.append(PluginSpec(PluginProviderType.URL, BUNGEE_RCON_URL, "latest", False, {}))

    memory = env.get("MEMORY", "1G").strip()
    if not re.fullmatch(r"\d+[KkMmGgTt]?", memory):
        raise SystemExit(f"Invalid MEMORY={memory!r}: use a size like 1536M or 2G")
    jvm_flags = env.get("JVM_FLAGS", "").split() or _default_jvm_flags(platform, memory)
    jvm_flags += env.get("JVM_EXTRA_FLAGS", "").split()

    verbose = _parse_bool(env.get("VERBOSE", "false"))
    accept_eula = _parse_bool(env.get("ACCEPT_EULA", "false"))

    strategy_raw = env.get("PLUGINS_UPDATE_STRATEGY", "auto").lower()
    try:
        plugins_update_strategy = PluginUpdateStrategy(strategy_raw)
    except ValueError:
        valid = ", ".join(t.value for t in PluginUpdateStrategy)
        msg = f"Unknown PLUGINS_UPDATE_STRATEGY={strategy_raw!r}. Valid options: {valid}"
        raise SystemExit(msg) from None

    plugins_check_cache_raw = env.get("PLUGINS_CHECK_CACHE", "5m").strip()
    try:
        plugins_check_cache_seconds = _parse_duration(plugins_check_cache_raw)
    except ValueError as e:
        raise SystemExit(f"Invalid PLUGINS_CHECK_CACHE={plugins_check_cache_raw!r}: {e}") from None

    api_tokens = ApiTokens(
        github=env.get("GITHUB_TOKEN", "").strip() or None,
        curseforge=env.get("CURSEFORGE_API_KEY", "").strip() or None,
    )

    return Config(
        platform=platform,
        version=version,
        build=build,
        data_dir=data_dir,
        templates_dir=templates_dir,
        runtime_dir=runtime_dir,
        plugins_dir=plugins_dir,
        plugin_specs=plugin_specs,
        config_overrides=config_overrides,
        applied_templates=applied_templates,
        server_properties=server_properties,
        rcon_enabled=rcon_enabled,
        rcon_password=rcon_password,
        rcon_port=rcon_port,
        memory=memory,
        jvm_flags=jvm_flags,
        verbose=verbose,
        accept_eula=accept_eula,
        plugins_update_strategy=plugins_update_strategy,
        plugins_check_cache_seconds=plugins_check_cache_seconds,
        api_tokens=api_tokens,
    )
