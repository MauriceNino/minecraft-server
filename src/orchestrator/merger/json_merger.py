"""JSON config merger with sigil support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.merger.sigils import deep_merge, strip_sigils


def merge_json(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* (JSON string) into *existing_path*."""
    overlay: dict[str | int, Any] = json.loads(overlay_content)

    if existing_path.exists():
        with existing_path.open() as f:
            base: dict[str | int, Any] = json.load(f)
        merged = deep_merge(base, overlay)
    else:
        merged = strip_sigils(overlay)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    with existing_path.open("w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")
