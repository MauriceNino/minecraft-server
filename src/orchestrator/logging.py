from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

THEME = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "phase": "bold magenta",
        "platform": "bold cyan",
        "version.old": "dim red strike",
        "version.new": "bold green",
        "download": "bold blue",
        "cached": "dim green",
        "label": "bold white",
        "dim": "dim",
    }
)

console = Console(theme=THEME, width=150, force_terminal=True)

_LOG_FORMAT = "%(message)s"


def setup_logging(*, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False,
                markup=True,
            )
        ],
    )

    # Suppress noisy HTTP request logs from httpx / httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


phase_console = Console(theme=THEME, width=65, force_terminal=True)


def log_header(title: str) -> None:
    phase_console.rule(f"[bold cyan]{title}[/bold cyan]", style="dim cyan")


def log_phase(title: str) -> None:
    phase_console.rule(f"[phase]{title}[/phase]", style="dim magenta")


def log_version_change(name: str, old: str | None, new: str) -> None:
    if old and old != new:
        console.print(
            f"  [success]↻[/success] [label]{name}[/label]  "
            f"[dim]updated[/dim] [version.old]{old}[/version.old] → [version.new]{new}[/version.new]"
        )
    else:
        console.print(
            f"  [success]📥[/success] [label]{name}[/label]  [dim]downloaded[/dim] [version.new]{new}[/version.new]"
        )
