"""JSON config merger with sigil support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.merger.sigils import KeySigil, parse_key_sigil, strip_sigils


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
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


def merge_json(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* (JSON string) into *existing_path*."""
    overlay: dict[str, Any] = json.loads(overlay_content)

    if existing_path.exists():
        with existing_path.open() as f:
            base: dict[str, Any] = json.load(f)
        merged = deep_merge(base, overlay)
    else:
        merged = strip_sigils(overlay)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    with existing_path.open("w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")
