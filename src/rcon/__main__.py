"""Interactive / one-shot RCON client, meant to be run inside the server container via `docker exec`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcrcon import MCRcon, MCRconException
from rich.console import Console
from rich.prompt import Prompt
from rich.theme import Theme

from orchestrator.constants import DEFAULT_DATA_DIR, RCON_PASSWORD_FILENAME, RUNTIME_SUBDIR

_THEME = Theme(
    {
        "prompt": "bold cyan",
        "info": "dim cyan",
        "error": "bold red",
    }
)
_console = Console(theme=_THEME, highlight=False)
_err_console = Console(theme=_THEME, stderr=True, highlight=False)


def _print_error(msg: str) -> None:
    _err_console.print(f"[error]{msg}[/error]")


def _read_password() -> str:
    if password := os.environ.get("RCON_PASSWORD"):
        return password

    # Auto-generated passwords only exist in the orchestrator process, so it leaves a copy on disk
    data_dir = Path(os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIR)))
    try:
        return (data_dir / RUNTIME_SUBDIR / RCON_PASSWORD_FILENAME).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _interactive(mcr: MCRcon, host: str, port: int) -> None:
    _console.print(f"[info]Connected to {host}:{port}  —  type 'exit' or Ctrl-D to quit[/info]\n")

    while True:
        try:
            line = Prompt.ask("[prompt]rcon> [/prompt]").strip()
        except (EOFError, KeyboardInterrupt):
            _console.print("\n[info]Bye![/info]")
            return

        if not line:
            continue
        if line.lower() in ("exit", "quit", "q"):
            _console.print("[info]Bye![/info]")
            return

        try:
            if response := mcr.command(line):
                _console.print(response, markup=False)
        except MCRconException as exc:
            _print_error(f"RCON error: {exc}")


def main() -> None:
    host = os.environ.get("RCON_HOST", "127.0.0.1")
    port = int(os.environ.get("RCON_PORT", "25575"))
    password = _read_password()

    if not password:
        _print_error(
            "No RCON password found.\n"
            "Set RCON_PASSWORD, or run mc-rcon inside the server container after the server has started."
        )
        sys.exit(1)

    # Arguments are sent as a single command, without arguments an interactive session starts
    command = " ".join(sys.argv[1:]).strip()

    try:
        with MCRcon(host, password, port=port) as mcr:
            if command:
                if response := mcr.command(command):
                    _console.print(response, markup=False)
            else:
                _interactive(mcr, host, port)
    except ConnectionRefusedError:
        _print_error(
            f"Connection refused ({host}:{port}).\n"
            "Is the server running and RCON enabled?\n"
            "  • Backend servers: check RCON_ENABLED=true in your environment\n"
            "  • Velocity / Waterfall: make sure the RCON bridge plugin is loaded"
        )
        sys.exit(1)
    except (MCRconException, OSError) as exc:
        _print_error(f"RCON error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
