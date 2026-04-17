from __future__ import annotations

import shutil
from pathlib import Path

from orchestrator.constants import MERGEABLE_EXTENSIONS
from orchestrator.env_interpolation import interpolate_env
from orchestrator.fs_orchestrator.sigils import DirSigil
from orchestrator.fs_orchestrator.template_reader import TemplateNode, read_template
from orchestrator.logging import console
from orchestrator.merger import log_change, merge_file


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
            console.print(f"  [warning]⚠[/warning] [label]Template directory not found: {tpl_name}[/label]")
            continue

        console.print(f"  [info]📂[/info] [label]{tpl_name}[/label]")
        tree = read_template(tpl_root)

        _execute_deletes_and_replaces(tree, runtime_dir)
        _merge_tree(tree, runtime_dir, runtime_dir, False, False)


def _execute_deletes_and_replaces(node: TemplateNode, runtime_base: Path) -> None:
    for child in node.children:
        target = runtime_base / child.clean_name

        if child.sigil in (DirSigil.DELETE, DirSigil.REPLACE):
            if not child.is_dir and target.exists():
                target.unlink()
            elif child.is_dir and target.exists():
                shutil.rmtree(target)

        elif child.is_dir:
            _execute_deletes_and_replaces(child, target)


def _merge_tree(node: TemplateNode, runtime_base: Path, runtime_dir: Path, in_replace: bool, in_force: bool) -> None:
    for child in node.children:
        target = runtime_base / child.clean_name
        is_replace = in_replace or (child.sigil == DirSigil.REPLACE)
        is_force = in_force or (child.sigil == DirSigil.FORCE)

        if child.sigil == DirSigil.DELETE:
            # Already handled in phase 1 — nothing to write
            log_change("deleted", str(target.relative_to(runtime_dir)))
            continue

        if child.is_dir:
            target.mkdir(parents=True, exist_ok=True)
            _merge_tree(child, target, runtime_dir, is_replace, is_force)
        else:
            try:
                _merge_file(child, target, runtime_dir, is_replace, is_force)
            except Exception as e:
                log_change("errored", str(target.relative_to(runtime_dir)), reason=str(e))
                raise e


def _merge_file(node: TemplateNode, target: Path, runtime_dir: Path, in_replace: bool, in_force: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    suffix = target.suffix.lower()
    rel_path = str(target.relative_to(runtime_dir))

    # If the file or its parent was explicitly `!replace:`d, just copy
    if in_replace or node.sigil == DirSigil.REPLACE:
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_interpolated(node.source_path, target)
        log_change("replaced", rel_path, indentation=1)
        return

    if not target.exists():
        if in_force or node.sigil == DirSigil.FORCE:
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_interpolated(node.source_path, target)
            log_change("created", rel_path, indentation=1)
            return
        log_change("skipped", rel_path, indentation=1)
        return

    if suffix in MERGEABLE_EXTENSIONS:
        merge_file(node.source_path, target)
        log_change("merged", rel_path, indentation=1)
        return

    # Non-config files: overwrite (last template wins for binaries)
    _write_interpolated(node.source_path, target)
    log_change("replaced", rel_path, indentation=1)


def _write_interpolated(source: Path, target: Path) -> None:
    try:
        content = source.read_text(encoding="utf-8")
        target.write_text(interpolate_env(content), encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        shutil.copy2(source, target)
