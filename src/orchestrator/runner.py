from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from orchestrator.constants import SERVER_PLATFORMS, PlatformType
from orchestrator.logging import console

# (first Minecraft version, minimum Java version), newest first
_MIN_JAVA_BY_MC_VERSION = [
    ((26, 1), 25),
    ((1, 20, 5), 21),
    ((1, 18), 17),
    ((1, 17), 16),
]
# Versions before 1.17 commonly break on newer Java releases
_MAX_JAVA_BEFORE_1_17 = 17


def _parse_mc_version(version: str) -> tuple[int, ...] | None:
    match = re.match(r"^(\d+(?:\.\d+)*)", version)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _java_major_version() -> int | None:
    try:
        result = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=30, check=False)  # noqa: S607
    except (OSError, subprocess.TimeoutExpired):
        return None
    # e.g. `openjdk version "21.0.5" 2024-10-15` or `java version "1.8.0_392"`
    match = re.search(r'version "(\d+)(?:\.(\d+))?', result.stderr + result.stdout)
    if not match:
        return None
    major = int(match.group(1))
    return int(match.group(2) or 0) if major == 1 else major


def java_compatibility_warning(mc_version: str, java_version: int) -> str | None:
    parsed = _parse_mc_version(mc_version)
    if parsed is None or "w" in mc_version:  # snapshots like 25w14a
        return None

    min_java = next((java for first, java in _MIN_JAVA_BY_MC_VERSION if parsed >= first), 8)
    if java_version < min_java:
        return (
            f"Minecraft {mc_version} requires Java {min_java} or newer, but this image has Java {java_version}. "
            "Use a newer image, e.g. the java25-temurin tag."
        )
    if min_java == 8 and java_version > _MAX_JAVA_BEFORE_1_17:
        return (
            f"Minecraft {mc_version} often doesn't run on Java newer than {_MAX_JAVA_BEFORE_1_17}, "
            f"but this image has Java {java_version}. If the server fails to start, use an older image: "
            "java8-temurin for 1.12 and older, java11-temurin or java17-temurin for 1.13 - 1.16."
        )
    return None


# Only exists since Java 16, older JVMs refuse to start with it
_VECTOR_MODULE_FLAG = "--add-modules=jdk.incubator.vector"


def build_java_command(
    server_jar: Path,
    memory: str,
    jvm_flags: list[str],
    platform: PlatformType,
    java_version: int | None = None,
) -> list[str]:
    args: list[str] = [
        "java",
        f"-Xmx{memory}",
        f"-Xms{memory}",
    ]

    if java_version is not None and java_version < 16:
        jvm_flags = [flag for flag in jvm_flags if flag != _VECTOR_MODULE_FLAG]
    args.extend(jvm_flags)
    args.extend(["-jar", str(server_jar)])

    # Only backend servers support --nogui; proxies don't
    if platform in SERVER_PLATFORMS:
        args.append("--nogui")

    return args


def exec_server(
    server_executable: Path,
    runtime_dir: Path,
    memory: str,
    jvm_flags: list[str],
    platform: PlatformType,
    mc_version: str,
) -> None:
    """Build the server command and replace this process with it.

    After this call, the Python process ceases to exist — the
    server becomes PID 1 (in Docker) for proper signal handling.
    """
    if platform == PlatformType.PUMPKIN:
        args = [str(server_executable)]
        executable = str(server_executable)
    else:
        java_version = _java_major_version()
        args = build_java_command(server_executable, memory, jvm_flags, platform, java_version)
        executable = "java"
        if (
            platform in SERVER_PLATFORMS
            and java_version is not None
            and (warning := java_compatibility_warning(mc_version, java_version))
        ):
            console.print(f"  [warning]⚠[/warning] {warning}")

    console.print(f"  🚀 [dim]Executing  →[/dim]  {' '.join(args)}")
    console.print()

    os.chdir(runtime_dir)
    os.execvp(executable, args)  # noqa: S606
