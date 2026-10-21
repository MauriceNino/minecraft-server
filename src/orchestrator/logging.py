from __future__ import annotations

import logging
import os
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

# Docker logs are usually not a TTY, so colours are forced unless NO_COLOR is set (https://no-color.org)
_FORCE_COLOR = not os.environ.get("NO_COLOR")

console = Console(theme=THEME, width=200, force_terminal=_FORCE_COLOR, highlight=False)

phase_console = Console(theme=THEME, width=65, force_terminal=_FORCE_COLOR, highlight=False)

_VERBOSE_ENABLED = True


def setup_logging(*, verbose: bool = True) -> None:
    global _VERBOSE_ENABLED
    _VERBOSE_ENABLED = verbose

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
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


def log_exception(exc: Exception, message: str) -> None:
    """Log the exception with a full traceback in verbose mode, or with a condensed stack otherwise."""
    if _VERBOSE_ENABLED:
        logging.getLogger("orchestrator").exception(message)
    else:
        stack = traceback.extract_tb(exc.__traceback__)

        error_msg = f"[error]Error:[/error] {message}\n"
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


_ACTION_ICONS = {
    "errored": "[red]✗[/red]",
    "created": "[cyan]✓[/cyan]",
    "deleted": "[cyan]✓[/cyan]",
    "merged": "[cyan]✓[/cyan]",
    "updated": "[success]⟳[/success]",
    "replaced": "[cyan]⟳[/cyan]",
    "updatable": "[yellow]⚠[/yellow]",
    "downloaded": "[success]✓[/success]",
    "skipped": "[dim]⊘[/dim]",
}


def log_change(action: str, item: str, reason: str | None = None, indentation: int = 0) -> None:
    indentation += 1
    action_pad = 14 - (indentation * 2)
    icon = _ACTION_ICONS.get(action, " ")
    suffix = f" [dim]({reason})[/dim]" if reason else ""
    console.print(f"{'  ' * indentation}{icon} [dim]{action.ljust(action_pad)}[/dim]{item}{suffix}")


def log_header(title: str) -> None:
    phase_console.rule(f"[bold cyan]{title}[/bold cyan]", style="dim cyan")


def log_phase(title: str) -> None:
    phase_console.rule(f"[phase]{title}[/phase]", style="dim magenta")
