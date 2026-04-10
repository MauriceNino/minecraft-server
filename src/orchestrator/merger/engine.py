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


def merge_file(overlay_path: Path, target_path: Path) -> None:
    """Deep-merge *overlay_path* into *target_path*, dispatching by extension.

    Environment variable placeholders (`$[VAR]`) in *overlay_path* are
    substituted from `os.environ` before merging.
    """
    suffix = target_path.suffix.lower()
    string_merger = _STRING_MERGERS.get(suffix)

    if string_merger is None:
        console.print(
            f"  [warning]✗[/warning] [dim]skipping[/dim]    {target_path.name}  [dim](unsupported format)[/dim]"
        )
        return

    # Interpolate env vars in the overlay content, then merge as a string
    raw_overlay = overlay_path.read_text(encoding="utf-8")
    interpolated = interpolate_env(raw_overlay)
    string_merger(target_path, interpolated)  # type: ignore[operator]


def apply_config_overrides(
    overrides: list[tuple[DirSigil, str, str]],
    runtime_dir: Path,
) -> None:
    """Apply config overrides parsed from `CONFIG_PATHS` + `CONFIG_<key>`.

    Parameters
    ----------
    overrides:
        List of `(sigil, relative_path, raw_content)` tuples produced by
        :func:`orchestrator.cli._collect_config_overrides`.
        `$[VAR]` placeholders in *raw_content* are substituted from
        `os.environ` before writing.
    runtime_dir:
        The runtime directory where config files reside.

    Behaviour by sigil
    ------------------
    - :attr:`~DirSigil.NONE`    — merge into the existing file.  If the file
      does not exist the override is **skipped**.
    - :attr:`~DirSigil.FORCE`   — create if absent, deep-merge if present.
    - :attr:`~DirSigil.REPLACE` — always write (create or overwrite); no merge.
    - :attr:`~DirSigil.DELETE`  — delete the target file (content ignored).
    """
    for sigil, rel_path, raw_content in overrides:
        target = runtime_dir / rel_path
        suffix = target.suffix.lower()

        # --- DELETE ---
        if sigil == DirSigil.DELETE:
            if target.exists():
                target.unlink()
                console.print(f"  [warning]✗[/warning] [dim]deleted[/dim]     {rel_path}")
            else:
                console.print(f"  [dim]⊘ skipping[/dim]    {rel_path} (delete — not found)")
            continue

        content = interpolate_env(raw_content)

        # --- REPLACE ---
        if sigil == DirSigil.REPLACE:
            console.print(f"  [info]✓[/info] [dim]replacing[/dim]   {rel_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            continue

        # --- FORCE or NONE ---
        if not target.exists():
            if sigil == DirSigil.FORCE:
                console.print(f"  [info]✓[/info] [dim]creating[/dim]    {rel_path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            else:
                console.print(f"  [dim]⊘ skipping[/dim]    {rel_path}")
            continue

        merger_fn = _STRING_MERGERS.get(suffix)
        if merger_fn is None:
            console.print(f"  [warning]✓[/warning] [dim]replacing[/dim]   {rel_path}  [dim](merge not supported)[/dim]")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            continue

        console.print(f"  [info]⚙[/info] [dim]merging[/dim]     {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        merger_fn(target, content)
