from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory, HOCONConverter

from orchestrator.merger.sigils import SIGIL_KEY_PATTERN, deep_merge, strip_sigils

# Bare sigil keys at the start of a line or right after `{` / `,`
_SIGIL_KEY_RE = re.compile(rf"(?P<lead>^\s*|[{{,]\s*)(?P<key>{SIGIL_KEY_PATTERN})", re.MULTILINE)


def _escape_sigils(hocon_str: str) -> str:
    return _SIGIL_KEY_RE.sub(r'\g<lead>"\g<key>"', hocon_str)


def merge_conf(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* into the HOCON file at *existing_path*, creating it if needed.

    Unlike the YAML and TOML mergers, comments in the existing file are lost.
    """
    overlay: Any = ConfigFactory.parse_string(_escape_sigils(overlay_content))

    if existing_path.exists():
        base: Any = ConfigFactory.parse_file(str(existing_path))
        merged = deep_merge(base.as_plain_ordered_dict(), overlay.as_plain_ordered_dict())
    else:
        merged = strip_sigils(overlay.as_plain_ordered_dict())

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(HOCONConverter.to_hocon(ConfigFactory.from_dict(merged)), encoding="utf-8")
