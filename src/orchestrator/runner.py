from __future__ import annotations

import os
from pathlib import Path

from orchestrator.constants import SERVER_PLATFORMS, PlatformType
from orchestrator.logging import console


def build_java_command(
    server_jar: Path,
    memory: str,
    jvm_flags: list[str],
    platform: PlatformType,
) -> list[str]:
    args: list[str] = [
        "java",
        f"-Xmx{memory}",
        f"-Xms{memory}",
    ]

    # Add user-supplied JVM flags
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
) -> None:
    """Build the server command and replace this process with it.

    After this call, the Python process ceases to exist — the
    server becomes PID 1 (in Docker) for proper signal handling.
    """
    if platform == PlatformType.PUMPKIN:
        args = [str(server_executable)]
        executable = str(server_executable)
    else:
        args = build_java_command(server_executable, memory, jvm_flags, platform)
        executable = "java"

    console.print(f"  🚀 [dim]Executing  →[/dim]  {' '.join(args)}")
    console.print()

    os.chdir(runtime_dir)
    os.execvp(executable, args)  # noqa: S606
