import re
from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory, HOCONConverter

from orchestrator.merger.sigils import DELETE_PREFIX, REPLACE_PREFIX, deep_merge, strip_sigils


def _escape_sigils(hocon_str: str) -> str:
    r"""Quote sigil-prefixed keys so they survive HOCON parsing.

    Transforms bare keys like `!replace:servers` into quoted keys
    `"!replace:servers"` which are valid HOCON.
    """
    pattern = re.compile(
        r"^(?P<key>(" + re.escape(REPLACE_PREFIX) + "|" + re.escape(DELETE_PREFIX) + r")[A-Za-z0-9_.:-]+)",
        re.MULTILINE,
    )

    return pattern.sub(r'"\g<key>"', hocon_str)


def merge_conf(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* (HOCON string) into *existing_path*."""
    escaped = _escape_sigils(overlay_content)
    overlay: Any = ConfigFactory.parse_string(escaped)

    if existing_path.exists():
        base: Any = ConfigFactory.parse_file(str(existing_path))
        # Convert to dict to apply our sigil-aware deep_merge
        merged_dict = deep_merge(base.as_plain_ordered_dict(), overlay.as_plain_ordered_dict())
    else:
        # No existing file — just write the overlay (strip sigils first)
        merged_dict = strip_sigils(overlay.as_plain_ordered_dict())

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    hocon_str = HOCONConverter.to_hocon(ConfigFactory.from_dict(merged_dict))
    existing_path.write_text(hocon_str, encoding="utf-8")
