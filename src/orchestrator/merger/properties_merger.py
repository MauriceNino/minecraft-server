from __future__ import annotations

import re
from pathlib import Path

from orchestrator.merger.sigils import KeySigil, parse_key_sigil

# Matches `key=value` or `key = value` lines
_PROP_RE = re.compile(r"^([^=\s]+)\s*=\s*(.*)$")


def _parse_properties(content: str) -> dict[str, str]:
    """Parse a `.properties` string into an ordered dict."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            # Check if it's a sigil-prefixed key
            m = _PROP_RE.match(line)
            if m:
                result[m.group(1)] = m.group(2)
            continue
        m = _PROP_RE.match(line)
        if m:
            result[m.group(1)] = m.group(2)
    return result


def _serialize_properties(data: dict[str, str]) -> str:
    """Serialize a dict back to `.properties` format."""
    lines = [f"{key}={value}" for key, value in data.items()]
    return "\n".join(lines) + "\n"


def merge_properties(existing_path: Path, overlay_content: str) -> None:
    """Merge *overlay_content* (`.properties` string) into *existing_path*.

    `.properties` files are flat key-value, so merge simply means
    overwriting keys.  The `!replace:` sigil is supported for
    consistency but behaves identically to a normal overwrite.
    """
    overlay_raw = _parse_properties(overlay_content)

    # Process sigils
    overlay: dict[str, str] = {}
    for key, value in overlay_raw.items():
        sigil, clean_key = parse_key_sigil(key)
        if sigil == KeySigil.DELETE:
            # Mark for deletion using None
            overlay[clean_key] = None  # type: ignore[assignment]
        else:
            overlay[clean_key] = value

    if existing_path.exists():
        base = _parse_properties(existing_path.read_text())
        for k, v in overlay.items():
            if v is None:
                base.pop(k, None)
            else:
                base[k] = v
        merged = base
    else:
        merged = {k: v for k, v in overlay.items() if v is not None}

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(_serialize_properties(merged))
