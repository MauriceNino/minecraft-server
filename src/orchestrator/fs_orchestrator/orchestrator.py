from __future__ import annotations

import shutil
from pathlib import Path

from orchestrator.constants import MERGEABLE_EXTENSIONS
from orchestrator.env_interpolation import interpolate_env
from orchestrator.fs_orchestrator.sigils import DirSigil
from orchestrator.fs_orchestrator.template_reader import TemplateNode, read_template
from orchestrator.logging import console, get_logger

log = get_logger(__name__)


def orchestrate_templates(
    templates_dir: Path,
    runtime_dir: Path,
    applied_templates: list[str],
) -> None:
    """Apply templates to the runtime directory using Replace-then-Merge.

    Each template is processed **sequentially** in the order given by
    *applied_templates*.  Within each template:
    """
    runtime_dir.mkdir(parents=True, exist_ok=True)

    for tpl_name in applied_templates:
        tpl_root = templates_dir / tpl_name
        if not tpl_root.is_dir():
            log.warning("Template directory not found: %s — skipping", tpl_root)
            continue

        console.print(f"  [info]📂[/info] [label]{tpl_name}[/label]")
        tree = read_template(tpl_root)

        _collect_and_execute_replaces(tree, runtime_dir)
        _collect_and_execute_deletes(tree, runtime_dir)

        _merge_tree(tree, runtime_dir, runtime_dir, False, False)


def _collect_and_execute_replaces(node: TemplateNode, runtime_base: Path) -> None:
    for child in node.children:
        target = runtime_base / child.clean_name
        if child.is_dir and child.sigil == DirSigil.REPLACE:
            if target.exists():
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
        elif not child.is_dir and child.sigil == DirSigil.REPLACE and target.exists():
            target.unlink()

        # Recurse into subdirectories (even replaced ones — they may have
        # nested replace markers for sub-dirs)
        if child.is_dir:
            _collect_and_execute_replaces(child, target)


def _collect_and_execute_deletes(node: TemplateNode, runtime_base: Path) -> None:
    for child in node.children:
        target = runtime_base / child.clean_name
        if not child.is_dir and child.sigil == DirSigil.DELETE and target.exists():
            target.unlink()

        if child.is_dir:
            _collect_and_execute_deletes(child, target)


def _merge_tree(
    node: TemplateNode, runtime_base: Path, runtime_dir: Path, in_replace: bool, in_force: bool
) -> None:
    for child in node.children:
        target = runtime_base / child.clean_name
        is_replace = in_replace or (child.sigil == DirSigil.REPLACE)
        is_force = in_force or (child.sigil == DirSigil.FORCE)

        if child.sigil == DirSigil.DELETE:
            # Already handled in phase 1 — nothing to write
            continue

        if child.is_dir:
            target.mkdir(parents=True, exist_ok=True)
            _merge_tree(child, target, runtime_dir, is_replace, is_force)
        else:
            _merge_file(child, target, runtime_dir, is_replace, is_force)


def _merge_file(
    node: TemplateNode, target: Path, runtime_dir: Path, in_replace: bool, in_force: bool
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    suffix = target.suffix.lower()
    rel_path = str(target.relative_to(runtime_dir))

    # If the file or its parent was explicitly `!replace:`d, just copy
    if in_replace or node.sigil == DirSigil.REPLACE:
        console.print(f"    [info]✓[/info] [dim]replacing[/dim] {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_interpolated(node.source_path, target)
        return

    if not target.exists():
        if in_force or node.sigil == DirSigil.FORCE:
            console.print(f"    [info]✓[/info] [dim]creating[/dim]  {rel_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_interpolated(node.source_path, target)
            return
        console.print(f"    [dim]⊘ skipping [/dim] {rel_path}")
        return

    if suffix in MERGEABLE_EXTENSIONS:
        console.print(f"    [info]⚙[/info] [dim]merging[/dim]   {rel_path}")
        from orchestrator.merger.engine import merge_file

        merge_file(node.source_path, target)
        return

    # Non-config files: overwrite (last template wins for binaries)
    console.print(f"    [info]✓[/info] [dim]replacing[/dim] {rel_path}")
    _write_interpolated(node.source_path, target)


def _write_interpolated(source: Path, target: Path) -> None:
    """Read *source*, interpolate env vars, and write the result to *target*.

    Falls back to a binary copy when the file cannot be decoded as UTF-8
    (e.g. jar files or other binary assets).
    """
    try:
        content = source.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        shutil.copy2(source, target)
        return
    target.write_text(interpolate_env(content), encoding="utf-8")
