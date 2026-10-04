from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from orchestrator.merger.sigils import KeySigil, parse_key_sigil, strip_sigils

# Round-trip instance, keeps comments and formatting of the existing file
_yaml = YAML()
_yaml.preserve_quotes = True


def _merge_into(base: CommentedMap, overlay: dict[Any, Any]) -> None:
    """Apply *overlay* to *base* in place. Comments in *base* survive, new keys are appended."""
    for raw_key, overlay_value in overlay.items():
        sigil, clean_key = parse_key_sigil(raw_key)

        if sigil == KeySigil.DELETE:
            base.pop(clean_key, None)
        elif (
            sigil == KeySigil.NONE and isinstance(base.get(clean_key), CommentedMap) and isinstance(overlay_value, dict)
        ):
            _merge_into(base[clean_key], overlay_value)
        else:
            base[clean_key] = _to_commented(strip_sigils(overlay_value))


def _to_commented(value: Any) -> Any:
    if isinstance(value, dict):
        return CommentedMap((k, _to_commented(v)) for k, v in value.items())
    if isinstance(value, list):
        return CommentedSeq(_to_commented(item) for item in value)
    return value


def _strip_sigils_in_place(node: Any) -> None:
    """Like `strip_sigils`, but keeps comments and key positions of a loaded document."""
    if isinstance(node, CommentedMap):
        # Walk backwards so positions of the remaining keys stay valid while renaming
        for pos, raw_key in reversed(list(enumerate(list(node.keys())))):
            value = node[raw_key]
            _strip_sigils_in_place(value)
            sigil, clean_key = parse_key_sigil(raw_key)
            if sigil == KeySigil.NONE:
                continue
            del node[raw_key]
            if sigil != KeySigil.DELETE:
                node.insert(pos, clean_key, value)
    elif isinstance(node, CommentedSeq):
        for item in node:
            _strip_sigils_in_place(item)


def merge_yaml(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* into the YAML file at *existing_path*, creating it if needed."""
    overlay: CommentedMap = _yaml.load(overlay_content) or CommentedMap()

    if existing_path.exists():
        with existing_path.open(encoding="utf-8") as f:
            result: CommentedMap = _yaml.load(f) or CommentedMap()
        _merge_into(result, overlay)
    else:
        result = overlay
        _strip_sigils_in_place(result)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    _yaml.dump(result, buf)
    existing_path.write_text(buf.getvalue(), encoding="utf-8")
