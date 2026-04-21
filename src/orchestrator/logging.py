from __future__ import annotations

import logging
import sys
import traceback

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
        "url": "blue underline",
    }
)

console = Console(theme=THEME, width=150, force_terminal=True, highlight=False)

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
                highlighter=None,
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

        error_msg = f"[error]{prefix}:[/error] {message}\n"
        error_msg += f"  [error]{type(exc).__name__}:[/error] {exc}"

        last_path = ""
        for frame in stack:
            path = frame.filename

            if "/orchestrator/" in path:
                path = path.partition("/orchestrator/")[2]

            if path == last_path:
                error_msg += f"[dim] -> {frame.lineno}[/dim]"
            else:
                error_msg += f"\n  [dim]at {path}: {frame.lineno}[/dim]"
            last_path = path

        console.print()
        console.print(error_msg)
        console.print()


def log_change(action: str, rel_path: str, reason: str | None = None, indentation: int = 0) -> None:
    indentation += 1
    action_pad = 13 - (indentation * 2)
    indent = "  " * indentation
    match action:
        case "errored":
            action_icon = "[error]✗[/error]"
        case "created":
            action_icon = "[info]✓[/info]"
        case "deleted":
            action_icon = "[info]✓[/info]"
        case "merged":
            action_icon = "[info]✓[/info]"
        case "replaced":
            action_icon = "[info]⟳[/info]"
        case "skipped":
            action_icon = "[dim]⊘[/dim]"
        case _:
            action_icon = " "

    if reason:
        console.print(f"{indent}{action_icon} [dim]{action.ljust(action_pad)}[/dim]{rel_path} [dim]({reason})[/dim]")
    else:
        console.print(f"{indent}{action_icon} [dim]{action.ljust(action_pad)}[/dim]{rel_path}")


phase_console = Console(theme=THEME, width=65, force_terminal=True, highlight=False)


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
