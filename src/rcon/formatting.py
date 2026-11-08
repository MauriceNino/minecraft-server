"""Convert Minecraft's legacy `§` formatting codes into Rich text."""

from __future__ import annotations

import re

from rich.style import Style
from rich.text import Text

_COLORS = {
    "0": "#000000",
    "1": "#0000aa",
    "2": "#00aa00",
    "3": "#00aaaa",
    "4": "#aa0000",
    "5": "#aa00aa",
    "6": "#ffaa00",
    "7": "#aaaaaa",
    "8": "#555555",
    "9": "#5555ff",
    "a": "#55ff55",
    "b": "#55ffff",
    "c": "#ff5555",
    "d": "#ff55ff",
    "e": "#ffff55",
    "f": "#ffffff",
}

_DECORATIONS = {
    "k": Style(blink=True),  # obfuscated, a terminal has no equivalent
    "l": Style(bold=True),
    "m": Style(strike=True),
    "n": Style(underline=True),
    "o": Style(italic=True),
}

# `§x§R§R§G§G§B§B` (Spigot hex colors) or a single `§<code>`
_CODE = re.compile(r"§x((?:§[0-9a-f]){6})|§([0-9a-fk-or])", re.IGNORECASE)


def legacy_to_text(message: str) -> Text:
    """Build a Rich `Text` from a message containing `§` codes, which are stripped from the output."""
    text = Text()
    style = Style()
    pos = 0

    for match in _CODE.finditer(message):
        text.append(message[pos : match.start()], style=style)
        pos = match.end()

        if hex_digits := match.group(1):
            # Like legacy colors, a hex color also resets the decorations
            style = Style(color="#" + hex_digits.replace("§", "").lower())
            continue

        code = match.group(2).lower()
        if code in _COLORS:
            style = Style(color=_COLORS[code])
        elif code == "r":
            style = Style()
        else:
            style += _DECORATIONS[code]

    text.append(message[pos:], style=style)
    return text
