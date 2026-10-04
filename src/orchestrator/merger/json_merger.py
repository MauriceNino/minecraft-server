from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.merger.sigils import deep_merge, strip_sigils


def merge_json(existing_path: Path, overlay_content: str) -> None:
    """Deep-merge *overlay_content* into the JSON file at *existing_path*, creating it if needed."""
    overlay: dict[str, Any] = json.loads(overlay_content)

    if existing_path.exists():
        base: dict[str, Any] = json.loads(existing_path.read_text(encoding="utf-8"))
        merged = deep_merge(base, overlay)
    else:
        merged = strip_sigils(overlay)

    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
