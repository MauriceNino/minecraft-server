from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.fs_orchestrator.sigils import DirSigil, parse_dir_sigil


@dataclass(slots=True)
class TemplateNode:
    name: str  # original name on disk (may include sigil)
    clean_name: str  # name with sigil stripped
    sigil: DirSigil
    is_dir: bool
    source_path: Path  # absolute path on disk
    children: list[TemplateNode] = field(default_factory=list)


def read_template(root: Path) -> TemplateNode:
    sigil, clean = parse_dir_sigil(root.name)
    node = TemplateNode(
        name=root.name,
        clean_name=clean,
        sigil=sigil,
        is_dir=root.is_dir(),
        source_path=root,
    )

    if root.is_dir():
        for child_path in sorted(root.iterdir()):
            node.children.append(read_template(child_path))

    return node
