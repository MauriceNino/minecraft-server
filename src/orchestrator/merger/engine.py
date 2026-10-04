from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from orchestrator.env_interpolation import interpolate_env
from orchestrator.logging import log_change
from orchestrator.merger.conf_merger import merge_conf
from orchestrator.merger.json_merger import merge_json
from orchestrator.merger.properties_merger import merge_properties
from orchestrator.merger.toml_merger import merge_toml
from orchestrator.merger.yaml_merger import merge_yaml
from orchestrator.sigils import DirSigil

_MERGERS: dict[str, Callable[[Path, str], None]] = {
    ".yml": merge_yaml,
    ".yaml": merge_yaml,
    ".json": merge_json,
    ".conf": merge_conf,
    ".toml": merge_toml,
    ".properties": merge_properties,
}


def is_mergeable(path: Path) -> bool:
    return path.suffix.lower() in _MERGERS


def merge_file_content(target_path: Path, overlay_content: str) -> None:
    """Interpolate `$[VAR]` placeholders in *overlay_content* and deep-merge it into *target_path*."""
    merger = _MERGERS.get(target_path.suffix.lower())
    if merger is None:
        raise ValueError(f"Unsupported file format: {target_path.suffix} for file {target_path}")
    merger(target_path, interpolate_env(overlay_content))


def merge_file(overlay_path: Path, target_path: Path) -> None:
    merge_file_content(target_path, overlay_path.read_text(encoding="utf-8"))


def apply_config_overrides(overrides: list[tuple[DirSigil, str, str]], runtime_dir: Path) -> None:
    """Apply the overrides parsed from `CONFIG_PATHS` + `CONFIG_<key>`.

    NONE merges into an existing file and skips missing ones, FORCE also creates missing files,
    REPLACE always overwrites and DELETE removes the file.
    """
    for sigil, rel_path, raw_content in overrides:
        target = runtime_dir / rel_path

        if sigil == DirSigil.DELETE:
            if target.exists():
                target.unlink()
                log_change("deleted", rel_path)
            else:
                log_change("skipped", rel_path, reason="nothing to delete")
            continue

        if not target.exists() and sigil == DirSigil.NONE:
            log_change("skipped", rel_path, reason="nothing to create")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        content = interpolate_env(raw_content)

        if sigil == DirSigil.REPLACE or not target.exists():
            target.write_text(content, encoding="utf-8")
            log_change("replaced" if sigil == DirSigil.REPLACE else "created", rel_path)
        elif is_mergeable(target):
            _MERGERS[target.suffix.lower()](target, content)
            log_change("merged", rel_path)
        else:
            target.write_text(content, encoding="utf-8")
            log_change("replaced", rel_path, reason="merge not supported")
