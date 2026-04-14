from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from orchestrator.constants import DEFAULT_DATA_DIR, PROXY_PLATFORMS, SERVER_PLATFORMS, PlatformType
from orchestrator.fs_orchestrator.sigils import DirSigil, parse_dir_sigil


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable configuration resolved from environment variables."""

    # Core
    platform: PlatformType
    version: str
    build: str
    data_dir: Path

    # Derived paths
    templates_dir: Path
    runtime_dir: Path
    plugins_dir: Path

    # Plugin specs (raw lines)
    plugin_lines: list[str]

    # Inline config overrides: list of (sigil, relative_path, raw_content)
    config_overrides: list[tuple[DirSigil, str, str]]

    # Template names to apply
    applied_templates: list[str]

    # RCON
    rcon_enabled: bool
    rcon_password: str
    rcon_port: int

    # JVM
    memory: str
    jvm_flags: list[str]

    # Verbose logging
    verbose: bool

    # EULA acceptance
    accept_eula: bool


def _parse_multiline(value: str) -> list[str]:
    """Split a newline-separated env var into non-empty stripped lines."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def _collect_config_overrides(
    environ: dict[str, str],
) -> list[tuple[DirSigil, str, str]]:
    """Parse `CONFIG_PATHS` + `CONFIG_<key>` env vars into override entries.

    `CONFIG_PATHS` is a multiline key-to-path mapping:

        CONFIG_PATHS: |
          !force:server_properties -> server.properties
          luckperms -> plugins/luckperms/config.yml

    Each non-empty line must have the form::

        [<sigil>:]<key> -> <relative/path>

    Recognised sigils (same as directory sigils):

    - `!force:`   — create even if absent, merge if present.
    - `!replace:` — always overwrite (create or replace).
    - `!delete:`  — delete the target file (no content needed).

    The *key* is used to look up `CONFIG_<KEY>` in the environment.
    Lines whose `CONFIG_<KEY>` env var is not set (or empty) are silently
    skipped, **except** for `!delete:` entries which need no content.
    """
    paths_raw = environ.get("CONFIG_PATHS", "")
    if not paths_raw.strip():
        return []

    result: list[tuple[DirSigil, str, str]] = []

    for line in paths_raw.splitlines():
        line = line.strip()
        if not line:
            continue

        if "->" not in line:
            # Malformed line — ignore
            continue

        lhs, _, rhs = line.partition("->")
        lhs = lhs.strip()
        rhs = rhs.strip()

        if not lhs or not rhs:
            continue

        # Parse optional sigil from the lhs
        sigil, key = parse_dir_sigil(lhs)

        # Look up the content env var
        env_key = f"CONFIG_{key}"
        raw_content = environ.get(env_key, "")

        # !delete entries need no content
        if sigil == DirSigil.DELETE:
            result.append((DirSigil.DELETE, rhs, ""))
            continue

        if not raw_content.strip():
            # No content defined — skip
            continue

        result.append((sigil, rhs, raw_content))

    return result


# Aliases that map to the canonical "latest" sentinel
_STABLE_ALIASES: frozenset[str] = frozenset({"latest", "stable"})
# Aliases that map to the canonical "experimental" sentinel
_EXPERIMENTAL_ALIASES: frozenset[str] = frozenset({"experimental", "beta"})


def _normalize_version_spec(raw: str) -> str:
    """Normalise a VERSION or BUILD value to a canonical sentinel or leave it as-is.

    - `latest` / `stable` -> `latest`
    - `experimental` / `beta` -> `experimental`
    - anything else (e.g. `1.21.4`, `123`) -> unchanged
    """
    lower = raw.strip().lower()
    if lower in _STABLE_ALIASES:
        return "latest"
    if lower in _EXPERIMENTAL_ALIASES:
        return "experimental"
    return raw.strip()


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
    data_dir = Path(env.get("DATA_DIR", str(DEFAULT_DATA_DIR)))

    templates_dir = data_dir / "templates"
    runtime_dir = data_dir / "runtime"
    plugins_dir = runtime_dir / "plugins"

    plugin_lines = _parse_multiline(env.get("PLUGINS", ""))
    applied_templates = _parse_multiline(env.get("APPLIED_TEMPLATES", ""))
    config_overrides = _collect_config_overrides(env)

    rcon_enabled = env.get("RCON_ENABLED", "true").lower() in ("true", "1", "yes")
    rcon_password = env.get("RCON_PASSWORD", str(uuid.uuid4()))
    rcon_port = int(env.get("RCON_PORT", "25575"))

    memory = env.get("MEMORY", "1G")
    jvm_flags_raw = env.get("JVM_FLAGS", "")
    jvm_flags = jvm_flags_raw.split() if jvm_flags_raw.strip() else []

    # Adding default JVM flags if not specified (https://flags.sh/)
    if not jvm_flags:
        if platform in SERVER_PLATFORMS:
            jvm_flags = [
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
        elif platform in PROXY_PLATFORMS:
            jvm_flags = [
                "-XX:+UseG1GC",
                "-XX:G1HeapRegionSize=4M",
                "-XX:+UnlockExperimentalVMOptions",
                "-XX:+ParallelRefProcEnabled",
                "-XX:+AlwaysPreTouch",
                "-XX:MaxInlineLevel=15",
            ]

    verbose = env.get("VERBOSE", "false").lower() in ("true", "1", "yes")
    accept_eula = env.get("ACCEPT_EULA", "false").lower() in ("true", "1", "yes")

    return Config(
        platform=platform,
        version=version,
        build=build,
        data_dir=data_dir,
        templates_dir=templates_dir,
        runtime_dir=runtime_dir,
        plugins_dir=plugins_dir,
        plugin_lines=plugin_lines,
        config_overrides=config_overrides,
        applied_templates=applied_templates,
        rcon_enabled=rcon_enabled,
        rcon_password=rcon_password,
        rcon_port=rcon_port,
        memory=memory,
        jvm_flags=jvm_flags,
        verbose=verbose,
        accept_eula=accept_eula,
    )
