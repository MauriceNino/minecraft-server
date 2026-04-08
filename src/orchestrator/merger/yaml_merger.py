from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from orchestrator.merger.sigils import KeySigil, parse_key_sigil, strip_sigils

# Shared RT (round-trip) YAML instance that preserves comments & formatting.
_yaml = YAML()
_yaml.preserve_quotes = True


def _ruamel_deep_merge(base_doc: CommentedMap, overlay: CommentedMap | dict[str, Any]) -> None:
    """Recursively apply *overlay* into *base_doc* in-place.

    - Comments and whitespace in *base_doc* are preserved wherever possible.
    - New keys from the overlay are appended without comments (they didn't
      exist in the original file anyway).
    - `!replace:key` sigils cause the entire value to be overwritten.
    - For dicts the merge recurses; scalars and lists overwrite.
    """
    for raw_key, overlay_value in overlay.items():
        sigil, clean_key = parse_key_sigil(raw_key)

        if sigil == KeySigil.DELETE:
            if clean_key in base_doc:
                del base_doc[clean_key]
        elif sigil == KeySigil.REPLACE:
            # Full replacement — strip any nested sigils and overwrite
            base_doc[clean_key] = _to_commented(strip_sigils(overlay_value))
        elif (
            clean_key in base_doc
            and isinstance(base_doc[clean_key], CommentedMap)
            and isinstance(overlay_value, (CommentedMap, dict))
        ):
            # Recurse into matching mapping — base keeps its comments
            _ruamel_deep_merge(base_doc[clean_key], overlay_value)
        else:
            # Scalar / list / new key — overwrite or insert
            base_doc[clean_key] = _to_commented(strip_sigils(overlay_value))


def _to_commented(value: Any) -> Any:
    """Convert a plain Python value to a ruamel.yaml CommentedMap/Seq (best-effort)."""
    if isinstance(value, dict):
        cm = CommentedMap()
        for k, v in value.items():
            cm[k] = _to_commented(v)
        return cm
    if isinstance(value, list):
        cs = CommentedSeq(_to_commented(item) for item in value)
        return cs
    return value


def _strip_sigils_from_doc(doc: CommentedMap) -> None:
    """Remove sigil prefixes from all keys in a CommentedMap in-place."""
    keys_to_rename = [(k, parse_key_sigil(k)) for k in list(doc.keys())]
    for raw_key, (sigil, clean_key) in keys_to_rename:
        if sigil != KeySigil.NONE:
            value = doc[raw_key]
            del doc[raw_key]
            if sigil != KeySigil.DELETE:
                doc[clean_key] = value


def merge_yaml(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* (YAML string) into *existing_path*.

    Comments already present in *existing_path* are preserved.  New keys
    from the overlay are appended without comments.

    If *existing_path* does not exist, the overlay is written directly
    (with sigils stripped).
    """
    overlay: CommentedMap = _yaml.load(overlay_content) or CommentedMap()

    if existing_path.exists():
        with existing_path.open(encoding="utf-8") as f:
            base_doc: CommentedMap = _yaml.load(f) or CommentedMap()
        _ruamel_deep_merge(base_doc, overlay)
        result_doc = base_doc
    else:
        # No existing file — write overlay after stripping sigils
        result_doc = _yaml.load(overlay_content) or CommentedMap()
        _strip_sigils_from_doc(result_doc)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    _yaml.dump(result_doc, buf)
    existing_path.write_text(buf.getvalue(), encoding="utf-8")
