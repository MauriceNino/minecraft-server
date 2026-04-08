from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomlkit
import tomlkit.container
import tomlkit.items

from orchestrator.merger.sigils import DELETE_PREFIX, REPLACE_PREFIX, KeySigil, parse_key_sigil, strip_sigils


def _escape_sigils(toml_str: str) -> str:
    r"""Quote sigil-prefixed keys so they survive TOML parsing.

    Transforms bare keys like `!replace:servers` into quoted keys
    `"!replace:servers"` which are valid TOML.  Already-quoted keys
    are left untouched.
    """
    pattern = re.compile(
        r"""
        (?P<prefix>                  # optional table-header prefix
            ^\[{1,2}\s*              # [ or [[ at start of line
        )?
        (?P<key>"""  # the sigil key
        + f"({re.escape(REPLACE_PREFIX)}|{re.escape(DELETE_PREFIX)})"
        + r"""[A-Za-z0-9_.:-]+)      # key name
        """,
        re.MULTILINE | re.VERBOSE,
    )

    def _quote(m: re.Match[str]) -> str:
        prefix = m.group("prefix") or ""
        key = m.group("key")
        return f'{prefix}"{key}"'

    return pattern.sub(_quote, toml_str)


def _tomlkit_deep_merge(base_doc: tomlkit.TOMLDocument, overlay: dict[str, Any]) -> None:
    """Recursively apply *overlay* values into *base_doc* in-place.

    - Comments and whitespace in *base_doc* are preserved wherever possible.
    - New keys from the overlay are appended without comments (they didn't
      exist in the original file anyway).
    - `!replace:key` sigils cause the entire value to be overwritten.
    - For dicts / TOML tables the merge recurses; scalars and lists overwrite.
    """
    for raw_key, overlay_value in overlay.items():
        sigil, clean_key = parse_key_sigil(raw_key)

        if sigil == KeySigil.DELETE:
            if clean_key in base_doc:
                del base_doc[clean_key]
        elif sigil == KeySigil.REPLACE:
            # Full replacement — strip any nested sigils and overwrite
            base_doc[clean_key] = _to_tomlkit_item(strip_sigils(overlay_value))
        elif clean_key in base_doc and isinstance(base_doc[clean_key], dict) and isinstance(overlay_value, dict):
            # Recurse into matching table — base table keeps its comments
            _tomlkit_deep_merge(base_doc[clean_key], overlay_value)  # type: ignore[arg-type]
        else:
            # Scalar / list / new key — overwrite or insert
            base_doc[clean_key] = _to_tomlkit_item(strip_sigils(overlay_value))


def _to_tomlkit_item(value: Any) -> Any:
    """Convert a plain Python value to a tomlkit item (best-effort).

    tomlkit is smart enough to wrap plain Python scalars when assigned to a
    document, but being explicit avoids surprises with nested dicts/lists.
    """
    if isinstance(value, dict):
        table = tomlkit.table()
        for k, v in value.items():
            table.add(k, _to_tomlkit_item(v))
        return table
    if isinstance(value, list):
        arr = tomlkit.array()
        for item in value:
            arr.append(_to_tomlkit_item(item))
        return arr
    return value


def merge_toml(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* (TOML string) into *existing_path*.

    Comments already present in *existing_path* are preserved.  New keys
    from the overlay are appended without comments.
    """
    escaped = _escape_sigils(overlay_content)
    overlay: dict[str, Any] = tomlkit.loads(escaped)  # type: ignore[assignment]

    if existing_path.exists():
        with existing_path.open(encoding="utf-8") as f:
            base_doc: tomlkit.TOMLDocument = tomlkit.load(f)
        _tomlkit_deep_merge(base_doc, overlay)
        result_doc = base_doc
    else:
        # No existing file — just write the overlay (strip sigils first)
        result_doc = tomlkit.loads(_escape_sigils(overlay_content))
        _strip_sigils_from_doc(result_doc)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    with existing_path.open("w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(result_doc))


def _strip_sigils_from_doc(doc: tomlkit.TOMLDocument) -> None:
    """Remove sigil prefixes from all keys in a tomlkit document in-place."""
    keys_to_rename = [(k, parse_key_sigil(k)) for k in list(doc)]
    for raw_key, (sigil, clean_key) in keys_to_rename:
        if sigil != KeySigil.NONE:
            value = doc.item(raw_key)
            del doc[raw_key]
            if sigil != KeySigil.DELETE:
                doc.add(clean_key, value)
