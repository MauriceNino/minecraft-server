from __future__ import annotations

from enum import Enum
from typing import Any

REPLACE_PREFIX = "!replace:"
DELETE_PREFIX = "!delete:"


class KeySigil(Enum):
    """Sigil type parsed from a config key."""

    NONE = "none"
    REPLACE = "replace"
    DELETE = "delete"


def parse_key_sigil(key: str) -> tuple[KeySigil, str]:
    """Parse a config key and return `(sigil, clean_key)`.

    Examples
    --------
    >>> parse_key_sigil("!replace:servers")
    (KeySigil.REPLACE, 'servers')
    >>> parse_key_sigil("motd")
    (KeySigil.NONE, 'motd')
    >>> parse_key_sigil("!replace:forwarding-mode")
    (KeySigil.REPLACE, 'forwarding-mode')
    """
    if key.startswith(REPLACE_PREFIX):
        return KeySigil.REPLACE, key[len(REPLACE_PREFIX) :]
    if key.startswith(DELETE_PREFIX):
        return KeySigil.DELETE, key[len(DELETE_PREFIX) :]
    return KeySigil.NONE, key


def strip_sigils(data: Any) -> Any:
    """Recursively strip all sigil prefixes from dictionary keys.

    Non-dict values are returned as-is.
    """
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            sigil, clean_key = parse_key_sigil(key)
            if sigil != KeySigil.DELETE:
                cleaned[clean_key] = strip_sigils(value)
        return cleaned

    if isinstance(data, list):
        return [strip_sigils(item) for item in data]

    return data


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge *overlay* into *base* with sigil support."""
    result = dict(base)

    for raw_key, overlay_value in overlay.items():
        sigil, clean_key = parse_key_sigil(raw_key)

        if sigil == KeySigil.DELETE:
            result.pop(clean_key, None)
        elif sigil == KeySigil.REPLACE:
            # Overwrite entirely (strip sigils from nested keys too)
            result[clean_key] = strip_sigils(overlay_value)
        elif clean_key in result and isinstance(result[clean_key], dict) and isinstance(overlay_value, dict):
            # Recursive merge
            result[clean_key] = deep_merge(result[clean_key], overlay_value)
        else:
            # Scalar / list / new key — overwrite
            result[clean_key] = strip_sigils(overlay_value)

    return result
