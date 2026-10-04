from __future__ import annotations

from pathlib import Path

from orchestrator.merger.sigils import KeySigil, parse_key_sigil


def _parse_line(line: str) -> tuple[str, str] | None:
    """Return `(key, value)` for a property line, or None for blank lines and comments."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    # `!` starts a comment in .properties files, unless it's one of our sigils
    if stripped.startswith("!") and parse_key_sigil(stripped)[0] == KeySigil.NONE:
        return None

    key, sep, value = stripped.partition("=")
    key = key.strip()
    if not sep and parse_key_sigil(key)[0] != KeySigil.DELETE:
        return None
    return key, value.strip()


def merge_properties(existing_path: Path, overlay_content: str) -> None:
    """Merge *overlay_content* into the `.properties` file at *existing_path*.

    Existing lines, comments and key order are kept. Properties are flat, so `!replace:` behaves like
    a plain overwrite, and `!delete:key` removes the key.
    """
    overlay: dict[str, str | None] = {}
    for line in overlay_content.splitlines():
        if parsed := _parse_line(line):
            sigil, key = parse_key_sigil(parsed[0])
            overlay[key] = None if sigil == KeySigil.DELETE else parsed[1]

    base_lines = existing_path.read_text(encoding="utf-8").splitlines() if existing_path.exists() else []
    result: list[str] = []
    written: set[str] = set()

    for line in base_lines:
        parsed = _parse_line(line)
        if parsed is None or parsed[0] not in overlay:
            result.append(line)
            continue

        key = parsed[0]
        value = overlay[key]
        # Drop duplicates of overridden keys, Java would otherwise use the last (stale) one
        if value is not None and key not in written:
            result.append(f"{key}={value}")
        written.add(key)

    result.extend(f"{key}={value}" for key, value in overlay.items() if value is not None and key not in written)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("\n".join(result) + "\n", encoding="utf-8")
