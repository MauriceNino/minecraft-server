"""Import a world from WORLD when the server has none yet."""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

from orchestrator.http import ApiTokens, create_http_client, download_file
from orchestrator.logging import console, log_change
from orchestrator.merger.properties_merger import read_properties

DEFAULT_LEVEL_NAME = "world"
# Bukkit-based servers keep the other dimensions next to the world, e.g. `world_nether`
DIMENSION_SUFFIXES = ("_nether", "_the_end")


def level_name(runtime_dir: Path) -> str:
    props_path = runtime_dir / "server.properties"
    name = read_properties(props_path).get("level-name", "") if props_path.exists() else ""
    return name.strip() or DEFAULT_LEVEL_NAME


def has_world(runtime_dir: Path) -> bool:
    return (runtime_dir / level_name(runtime_dir) / "level.dat").is_file()


def _is_url(source: str) -> bool:
    return source.startswith(("https://", "http://"))


def _extract_zip(archive: Path, dest: Path) -> None:
    dest_root = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest_root):
                raise RuntimeError(f"Refusing to extract {member.filename!r} outside of the world directory")
        zf.extractall(dest)  # noqa: S202 - every member was checked above


def _unpack(source: Path, dest: Path) -> None:
    """Copy a directory or extract a zip or tar archive into *dest*."""
    if source.is_dir():
        shutil.copytree(source, dest, symlinks=False, dirs_exist_ok=True)
    elif zipfile.is_zipfile(source):
        _extract_zip(source, dest)
    elif tarfile.is_tarfile(source):
        with tarfile.open(source) as tf:
            tf.extractall(dest, filter="data")
    else:
        raise RuntimeError(f"{source.name} is neither a directory nor a zip or tar archive")


def find_world_root(extracted: Path) -> Path:
    """The shallowest directory that contains a `level.dat`."""
    candidates = sorted(extracted.rglob("level.dat"), key=lambda p: (len(p.parts), str(p)))
    if not candidates:
        raise RuntimeError("The world contains no level.dat")
    return candidates[0].parent


def _move_world(root: Path, runtime_dir: Path, name: str) -> list[str]:
    moves = [(root, runtime_dir / name)]
    moves += [
        (root.parent / f"{root.name}{suffix}", runtime_dir / f"{name}{suffix}")
        for suffix in DIMENSION_SUFFIXES
        if root.parent != root and (root.parent / f"{root.name}{suffix}").is_dir()
    ]
    for _, target in moves:
        if target.exists() and any(target.iterdir()):
            raise RuntimeError(f"{target.name} already exists without a level.dat. Remove it to import the world")

    imported: list[str] = []
    for src, target in moves:
        if target.exists():
            target.rmdir()
        src.rename(target)
        imported.append(target.name)
    return imported


def _import_local(source: Path, runtime_dir: Path, work_dir: Path, name: str) -> list[str]:
    extracted = work_dir / "extracted"
    extracted.mkdir()
    _unpack(source, extracted)
    return _move_world(find_world_root(extracted), runtime_dir, name)


async def import_world(source: str, runtime_dir: Path, tokens: ApiTokens | None = None) -> None:
    """Import the world from *source* (URL or path) unless the server already has one.

    Failures raise: starting without the world would generate a new one, and the import would never happen.
    """
    name = level_name(runtime_dir)
    if has_world(runtime_dir):
        log_change("skipped", name, reason="world already exists")
        return

    runtime_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    # Inside the runtime directory, so the final move is a rename on the same filesystem
    with tempfile.TemporaryDirectory(dir=runtime_dir, prefix=".world_") as tmp:
        work_dir = Path(tmp)
        if _is_url(source):
            local = work_dir / "download"
            async with create_http_client(tokens=tokens) as client:
                await download_file(client, source, local)
        else:
            local = Path(source)
            if not local.exists():
                raise RuntimeError(f"WORLD={source} does not exist in the container")
        imported = _import_local(local, runtime_dir, work_dir, name)

    for directory in imported:
        log_change("created", directory, reason=f"imported from {source}")
    console.print("  [info]🛈[/info] Delete the world folder to import it again")
