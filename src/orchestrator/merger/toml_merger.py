from __future__ import annotations

import re
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import tomlkit

from orchestrator.merger.sigils import SIGIL_KEY_PATTERN, KeySigil, parse_key_sigil, strip_sigils

# Bare sigil keys at the start of a line (`!replace:key = ...`) or inside a table header (`[a.!replace:b]`)
_SIGIL_KEY_RE = re.compile(
    rf"^(?P<prefix>\s*(?:\[{{1,2}}\s*(?:[^\]\n]*\.\s*)?)?)(?P<key>{SIGIL_KEY_PATTERN})", re.MULTILINE
)


def _escape_sigils(toml_str: str) -> str:
    return _SIGIL_KEY_RE.sub(r'\g<prefix>"\g<key>"', toml_str)


def _merge_into(base: MutableMapping[str, Any], overlay: dict[str, Any]) -> None:
    """Apply *overlay* to *base* in place. Comments in *base* survive, new keys are appended."""
    for raw_key, overlay_value in overlay.items():
        sigil, clean_key = parse_key_sigil(raw_key)

        if sigil == KeySigil.DELETE:
            base.pop(clean_key, None)
        elif sigil == KeySigil.NONE and isinstance(base.get(clean_key), dict) and isinstance(overlay_value, dict):
            _merge_into(base[clean_key], overlay_value)
        else:
            base[clean_key] = _to_tomlkit_item(strip_sigils(overlay_value))


def _to_tomlkit_item(value: Any) -> Any:
    if isinstance(value, dict):
        table = tomlkit.table()
        for k, v in value.items():
            table.add(k, _to_tomlkit_item(v))
        return table
    if isinstance(value, list):
        arr = tomlkit.array()
        arr.extend(_to_tomlkit_item(item) for item in value)
        return arr
    return value


def _strip_sigils_in_place(node: Any) -> None:
    """Like `strip_sigils`, but keeps the comments of a parsed document."""
    if isinstance(node, dict):
        for raw_key in list(node.keys()):
            value = node[raw_key]
            _strip_sigils_in_place(value)
            sigil, clean_key = parse_key_sigil(raw_key)
            if sigil == KeySigil.NONE:
                continue
            del node[raw_key]
            if sigil != KeySigil.DELETE:
                node[clean_key] = value
    elif isinstance(node, list):
        for item in node:
            _strip_sigils_in_place(item)


def merge_toml(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* into the TOML file at *existing_path*, creating it if needed."""
    overlay = tomlkit.loads(_escape_sigils(overlay_content))

    if existing_path.exists():
        with existing_path.open(encoding="utf-8") as f:
            result = tomlkit.load(f)
        _merge_into(result, overlay.unwrap())
    else:
        result = overlay
        _strip_sigils_in_place(result)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(tomlkit.dumps(result), encoding="utf-8")
