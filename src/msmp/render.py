"""Readable output for results and notifications."""

from __future__ import annotations

from typing import Any

from rich.console import Console, RenderableType
from rich.table import Table
from rich.text import Text


def short(value: Any) -> str:
    """One-line form of a value: players by name, messages by text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, dict):
        if "name" in value and set(value) <= {"name", "id"}:
            return str(value["name"] or value.get("id", ""))
        if "id" in value and set(value) == {"id"}:
            return str(value["id"])
        if "literal" in value:
            return str(value["literal"])
        if "translatable" in value:
            params = value.get("translatableParams") or []
            return str(value["translatable"]) + (f" ({', '.join(map(str, params))})" if params else "")
        if set(value) == {"name", "protocol"}:
            return f"{value['name']} (protocol {value['protocol']})"
        return ", ".join(f"{k}={short(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(short(v) for v in value) if value else "-"
    return str(value)


def _is_player(value: Any) -> bool:
    return isinstance(value, dict) and "name" in value and set(value) <= {"name", "id"}


def render(value: Any) -> RenderableType:
    if isinstance(value, bool):
        return Text("true" if value else "false", style="green" if value else "yellow")
    if isinstance(value, list):
        if not value:
            return Text("(none)", style="dim")
        if all(_is_player(v) for v in value):
            text = Text()
            for i, player in enumerate(value):
                if i:
                    text.append("\n")
                text.append(str(player.get("name") or "?"))
                if player.get("id"):
                    text.append(f"  {player['id']}", style="dim")
            return text
        if all(isinstance(v, dict) for v in value):
            columns: list[str] = []
            for row in value:
                columns.extend(k for k in row if k not in columns)
            table = Table(box=None, pad_edge=False, header_style="bold cyan")
            for column in columns:
                table.add_column(column)
            for row in value:
                table.add_row(*(short(row.get(c)) for c in columns))
            return table
        return Text("\n".join(short(v) for v in value))
    if isinstance(value, dict) and not _is_player(value):
        table = Table(box=None, pad_edge=False, show_header=False)
        table.add_column(style="bold cyan")
        table.add_column()
        for key, item in value.items():
            table.add_row(key, short(item))
        return table
    return Text(short(value))


def print_result(console: Console, value: Any) -> None:
    if value is None:
        return
    console.print(render(value))


def notification_text(method: str, params: Any) -> Text:
    """`minecraft:notification/players/joined` with `[jeb_]` -> `players/joined  jeb_`."""
    name = method.split("notification/", 1)[-1] if "notification/" in method else method
    text = Text()
    text.append("» ", style="dim")
    text.append(name, style="magenta")
    if isinstance(params, list):
        params = params[0] if len(params) == 1 else params
    if params not in (None, [], {}):
        text.append("  ")
        text.append(short(params))
    return text
