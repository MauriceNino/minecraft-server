from __future__ import annotations

import re
from enum import Enum
from typing import Any

from orchestrator.sigils import DELETE_PREFIX, REPLACE_PREFIX

# A bare `!replace:key` / `!delete:key` is not valid syntax in TOML or HOCON, so those mergers quote it first
SIGIL_KEY_PATTERN = rf"(?:{re.escape(REPLACE_PREFIX)}|{re.escape(DELETE_PREFIX)})[A-Za-z0-9_-]+"


class KeySigil(Enum):
    NONE = "none"
    REPLACE = "replace"
    DELETE = "delete"


def parse_key_sigil(key: object) -> tuple[KeySigil, str]:
    """Split a config key into its sigil and the plain key, e.g. `"!replace:servers"` -> `(REPLACE, "servers")`."""
    if not isinstance(key, str):
        return KeySigil.NONE, str(key)
    if key.startswith(REPLACE_PREFIX):
        return KeySigil.REPLACE, key.removeprefix(REPLACE_PREFIX)
    if key.startswith(DELETE_PREFIX):
        return KeySigil.DELETE, key.removeprefix(DELETE_PREFIX)
    return KeySigil.NONE, key


def strip_sigils(data: Any) -> Any:
    """Return a copy of *data* with sigil prefixes removed from all keys and `!delete:` keys dropped."""
    if isinstance(data, dict):
        cleaned: dict[Any, Any] = {}
        for key, value in data.items():
            sigil, clean_key = parse_key_sigil(key)
            if sigil != KeySigil.DELETE:
                cleaned[clean_key] = strip_sigils(value)
        return cleaned
    if isinstance(data, list):
        return [strip_sigils(item) for item in data]
    return data


def deep_merge(base: dict[Any, Any], overlay: dict[Any, Any]) -> dict[Any, Any]:
    """Return *base* deep-merged with *overlay*, honouring `!replace:` and `!delete:` keys in the overlay."""
    result = dict(base)

    for raw_key, overlay_value in overlay.items():
        sigil, clean_key = parse_key_sigil(raw_key)

        if sigil == KeySigil.DELETE:
            result.pop(clean_key, None)
        elif sigil == KeySigil.NONE and isinstance(result.get(clean_key), dict) and isinstance(overlay_value, dict):
            result[clean_key] = deep_merge(result[clean_key], overlay_value)
        else:
            result[clean_key] = strip_sigils(overlay_value)

    return result
