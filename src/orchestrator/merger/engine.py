from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from orchestrator.env_interpolation import interpolate_env
from orchestrator.fs_orchestrator.sigils import DirSigil
from orchestrator.logging import console
from orchestrator.merger.conf_merger import merge_conf
from orchestrator.merger.json_merger import merge_json
from orchestrator.merger.properties_merger import merge_properties
from orchestrator.merger.toml_merger import merge_toml
from orchestrator.merger.yaml_merger import merge_yaml

# String-based merge  (env var content -> runtime file)
_STRING_MERGERS: dict[str, Callable[[Path, str], None]] = {
    ".yml": merge_yaml,
    ".yaml": merge_yaml,
    ".json": merge_json,
    ".conf": merge_conf,
    ".toml": merge_toml,
    ".properties": merge_properties,
}


def log_change(action: str, rel_path: str, reason: str | None = None, indentation: int = 0) -> None:
    indentation += 1
    action_pad = 13 - (indentation * 2)
    indent = "  " * indentation
    match action:
        case "errored":
            action_icon = "[error]✗[/error]"
        case "created":
            action_icon = "[info]✓[/info]"
        case "deleted":
            action_icon = "[info]✓[/info]"
        case "merged":
            action_icon = "[info]✓[/info]"
        case "replaced":
            action_icon = "[info]⟳[/info]"
        case "skipped":
            action_icon = "[dim]⊘[/dim]"
        case _:
            action_icon = " "

    if reason:
        console.print(f"{indent}{action_icon} [dim]{action.ljust(action_pad)}[/dim]{rel_path} [dim]({reason})[/dim]")
    else:
        console.print(f"{indent}{action_icon} [dim]{action.ljust(action_pad)}[/dim]{rel_path}")


def merge_file_content(target_path: Path, overlay_content: str) -> None:
    suffix = target_path.suffix.lower()
    string_merger = _STRING_MERGERS.get(suffix)

    if string_merger is None:
        raise ValueError(f"Unsupported file format: {suffix} for file {target_path!s}")

    interpolated = interpolate_env(overlay_content)
    string_merger(target_path, interpolated)


def merge_file(overlay_path: Path, target_path: Path) -> None:
    if target_path.suffix.lower() not in _STRING_MERGERS:
        log_change("skipped", target_path.name, reason="unsupported format")
        return

    raw_overlay = overlay_path.read_text(encoding="utf-8")
    merge_file_content(target_path, raw_overlay)


def apply_config_overrides(
    overrides: list[tuple[DirSigil, str, str]],
    runtime_dir: Path,
) -> None:
    """Apply config overrides parsed from `CONFIG_PATHS` + `CONFIG_<key>`.

    Behaviour by sigil
    ------------------
    - DirSigil.NONE    - merge into the existing file. If the file does not exist the override is skipped.
    - DirSigil.FORCE   - create if absent, deep-merge if present.
    - DirSigil.REPLACE - always write (create or overwrite); no merge.
    - DirSigil.DELETE  - delete the target file (content ignored).
    """
    for sigil, rel_path, raw_content in overrides:
        target = runtime_dir / rel_path
        suffix = target.suffix.lower()

        # --- DELETE ---
        if sigil == DirSigil.DELETE:
            if target.exists():
                target.unlink()
                log_change("deleted", rel_path)
            else:
                log_change("skipped", rel_path, reason="nothing to delete")
            continue

        content = interpolate_env(raw_content)

        # --- REPLACE ---
        if sigil == DirSigil.REPLACE:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            log_change("replaced", rel_path)
            continue

        # --- FORCE or NONE ---
        if not target.exists():
            if sigil == DirSigil.FORCE:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                log_change("created", rel_path)
            else:
                log_change("skipped", rel_path, reason="nothing to create")
            continue

        merger_fn = _STRING_MERGERS.get(suffix)
        if merger_fn is None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            log_change("replaced", rel_path, reason="merge not supported")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        merger_fn(target, content)
        log_change("merged", rel_path)
