from __future__ import annotations

import os
import sys

from mcrcon import MCRcon, MCRconException
from rich.console import Console
from rich.prompt import Prompt
from rich.theme import Theme

_THEME = Theme(
    {
        "prompt": "bold cyan",
        "response": "white",
        "info": "dim cyan",
        "success": "bold green",
        "error": "bold red",
        "dim": "dim",
    }
)
_console = Console(theme=_THEME)
_err_console = Console(theme=_THEME, stderr=True)


def _print_info(msg: str) -> None:
    _console.print(f"[info]{msg}[/info]")


def _print_response(msg: str) -> None:
    if msg:
        _console.print(f"[response]{msg}[/response]")


def _print_error(msg: str) -> None:
    _err_console.print(f"[error]{msg}[/error]")


def _input(prompt: str) -> str:
    return Prompt.ask(f"[prompt]{prompt}[/prompt]")


def _get_config() -> tuple[str, int, str]:
    host = os.environ.get("RCON_HOST", "0.0.0.0")  # noqa: S104
    port = int(os.environ.get("RCON_PORT", "25575"))
    password = os.environ.get("RCON_PASSWORD", "")
    return host, port, password


def _run_command(mcr: MCRcon, command: str) -> str:
    return mcr.command(command)


def _interactive(mcr: MCRcon, host: str, port: int) -> None:
    _print_info(f"Connected to {host}:{port}  —  type 'exit' or Ctrl-D to quit")
    _print_info("")

    while True:
        try:
            line = _input("rcon> ")
        except (EOFError, KeyboardInterrupt):
            _print_info("\nBye!")
            break

        line = line.strip()
        if not line:
            continue
        if line.lower() in ("exit", "quit", "q"):
            _print_info("Bye!")
            break

        try:
            response = _run_command(mcr, line)
            _print_response(response)
        except MCRconException as exc:
            _print_error(f"RCON error: {exc}")


def main() -> None:
    host, port, password = _get_config()

    if not password:
        _print_error(
            "RCON_PASSWORD is not set.\n"
            "The password is set automatically by the orchestrator.\n"
            "Make sure you are running inside the same container."
        )
        sys.exit(1)

    # Remaining argv is treated as a one-shot command to run
    args = sys.argv[1:]
    command = " ".join(args).strip() if args else ""

    try:
        with MCRcon(host, password, port=port) as mcr:
            if command:
                response = _run_command(mcr, command)
                _print_response(response)
            else:
                _interactive(mcr, host, port)
    except ConnectionRefusedError:
        _print_error(
            f"Connection refused ({host}:{port}).\n"
            "Is the server running and RCON enabled?\n"
            "  • Backend servers: check RCON_ENABLED=true in your environment\n"
            "  • Velocity: ensure Velocircon plugin is loaded"
        )
        sys.exit(1)
    except MCRconException as exc:
        _print_error(f"RCON error: {exc}")
        sys.exit(1)
    except OSError as exc:
        _print_error(f"Network error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
