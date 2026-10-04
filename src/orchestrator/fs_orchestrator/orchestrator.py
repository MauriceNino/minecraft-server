from __future__ import annotations

import shutil
from pathlib import Path

from orchestrator.env_interpolation import interpolate_env
from orchestrator.fs_orchestrator.template_reader import TemplateNode, read_template
from orchestrator.logging import console, log_change
from orchestrator.merger import is_mergeable, merge_file
from orchestrator.sigils import DirSigil


def orchestrate_templates(templates_dir: Path, runtime_dir: Path, applied_templates: list[str]) -> None:
    """Apply templates to the runtime directory, one after another in the given order.

    For each template, everything marked `!delete:` or `!replace:` is removed from the runtime
    directory first, then the template's files are written or merged into it.
    """
    runtime_dir.mkdir(parents=True, exist_ok=True)

    for tpl_name in applied_templates:
        tpl_root = templates_dir / tpl_name
        if not tpl_root.is_dir():
            console.print(f"  [warning]⚠[/warning] [label]Template directory not found: {tpl_name}[/label]")
            continue

        console.print(f"  [info]📂[/info] [label]{tpl_name}[/label]")
        tree = read_template(tpl_root)

        _remove_deleted_and_replaced(tree, runtime_dir)
        _merge_tree(tree, runtime_dir, runtime_dir, in_replace=False, in_force=False)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _remove_deleted_and_replaced(node: TemplateNode, runtime_base: Path) -> None:
    for child in node.children:
        target = runtime_base / child.clean_name
        if child.sigil in (DirSigil.DELETE, DirSigil.REPLACE):
            _remove(target)
        elif child.is_dir:
            _remove_deleted_and_replaced(child, target)


def _merge_tree(node: TemplateNode, runtime_base: Path, runtime_dir: Path, *, in_replace: bool, in_force: bool) -> None:
    for child in node.children:
        target = runtime_base / child.clean_name
        rel_path = str(target.relative_to(runtime_dir))
        is_replace = in_replace or child.sigil == DirSigil.REPLACE
        is_force = in_force or child.sigil == DirSigil.FORCE

        if child.sigil == DirSigil.DELETE:
            log_change("deleted", rel_path, indentation=1)
        elif child.is_dir:
            target.mkdir(parents=True, exist_ok=True)
            _merge_tree(child, target, runtime_dir, in_replace=is_replace, in_force=is_force)
        else:
            try:
                _apply_file(child.source_path, target, rel_path, replace=is_replace, force=is_force)
            except Exception as e:
                log_change("errored", rel_path, reason=str(e), indentation=1)
                raise


def _apply_file(source: Path, target: Path, rel_path: str, *, replace: bool, force: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    if replace:
        _write_interpolated(source, target)
        log_change("replaced", rel_path, indentation=1)
    elif not target.exists():
        if force:
            _write_interpolated(source, target)
            log_change("created", rel_path, indentation=1)
        else:
            log_change("skipped", rel_path, indentation=1)
    elif is_mergeable(target):
        merge_file(source, target)
        log_change("merged", rel_path, indentation=1)
    else:
        # Not a config format we can merge: last template wins
        _write_interpolated(source, target)
        log_change("replaced", rel_path, indentation=1)


def _write_interpolated(source: Path, target: Path) -> None:
    try:
        content = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Binary file, copy as-is
        shutil.copy2(source, target)
        return
    target.write_text(interpolate_env(content), encoding="utf-8")
