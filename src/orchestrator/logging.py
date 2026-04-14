from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

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
_VERBOSE_ENABLED = True


def setup_logging(*, verbose: bool = True) -> None:
    global _VERBOSE_ENABLED
    _VERBOSE_ENABLED = verbose

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=verbose,
                show_path=False,
                markup=True,
            )
        ],
    )

    # Suppress noisy HTTP request logs from httpx / httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def log_exception(exc: Exception, message: str, *, prefix: str = "Error") -> None:
    """Log an exception concisely in production or with full traceback in verbose mode."""
    if _VERBOSE_ENABLED:
        logging.getLogger("orchestrator").exception(message)
    else:
        _, _, tb = sys.exc_info()
        stack = traceback.extract_tb(tb)
        last_frame = stack[-1] if stack else None

        error_msg = f"[error]{prefix}:[/error] {message}\n"
        error_msg += f"  [bold red]{type(exc).__name__}:[/bold red] {exc}"
        if last_frame:
            # Shorten absolute path to relative or filename for cleaner output
            path = last_frame.filename
            cwd = str(Path.cwd())
            if path.startswith(cwd):
                path = path[len(cwd) :].lstrip("/")
            elif "/src/" in path:
                path = path.partition("/src/")[2]
            error_msg += f"\n  [dim]at {path}:{last_frame.lineno}[/dim]"

        console.print()
        console.print(error_msg)
        console.print()


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
