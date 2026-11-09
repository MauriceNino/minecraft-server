from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from orchestrator.world import import_world

URL = "https://cdn.example/world.zip"


def _zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return out.getvalue()


async def test_zip_with_nested_world_and_dimensions(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=URL,
        content=_zip(
            {
                "export/survival/level.dat": b"overworld",
                "export/survival/region/r.0.0.mca": b"r",
                "export/survival_nether/DIM-1/level.dat_old": b"n",
                "export/survival_the_end/DIM1/x": b"e",
                "export/survival/datapacks/pack/level.dat": b"deeper, ignored",
            }
        ),
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "server.properties").write_text("level-name=lobby\n")

    await import_world(URL, runtime)

    assert (runtime / "lobby" / "level.dat").read_bytes() == b"overworld"
    assert (runtime / "lobby" / "region" / "r.0.0.mca").is_file()
    assert (runtime / "lobby_nether" / "DIM-1").is_dir()
    assert (runtime / "lobby_the_end" / "DIM1").is_dir()
    assert not [p for p in runtime.iterdir() if p.name.startswith(".world_")]


async def test_existing_world_is_kept(tmp_path: Path) -> None:
    (tmp_path / "world").mkdir()
    (tmp_path / "world" / "level.dat").write_bytes(b"mine")

    await import_world("/does/not/matter.zip", tmp_path)

    assert (tmp_path / "world" / "level.dat").read_bytes() == b"mine"


async def test_tar_gz_file(tmp_path: Path) -> None:
    archive = tmp_path / "world.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        data = b"overworld"
        info = tarfile.TarInfo("level.dat")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    runtime = tmp_path / "runtime"

    await import_world(str(archive), runtime)

    assert (runtime / "world" / "level.dat").read_bytes() == b"overworld"


async def test_directory(tmp_path: Path) -> None:
    (tmp_path / "src" / "myworld").mkdir(parents=True)
    (tmp_path / "src" / "myworld" / "level.dat").write_bytes(b"x")
    runtime = tmp_path / "runtime"

    await import_world(str(tmp_path / "src"), runtime)

    assert (runtime / "world" / "level.dat").is_file()
    assert (tmp_path / "src" / "myworld" / "level.dat").is_file()  # the source is copied, not moved


async def test_without_level_dat_fails(tmp_path: Path) -> None:
    archive = tmp_path / "world.zip"
    archive.write_bytes(_zip({"readme.txt": b"hi"}))

    with pytest.raises(RuntimeError, match=r"no level\.dat"):
        await import_world(str(archive), tmp_path / "runtime")


async def test_path_traversal_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "world.zip"
    archive.write_bytes(_zip({"../../evil/level.dat": b"x"}))

    with pytest.raises(RuntimeError, match="outside of the world directory"):
        await import_world(str(archive), tmp_path / "runtime")


async def test_non_empty_folder_without_level_dat_is_not_overwritten(tmp_path: Path) -> None:
    archive = tmp_path / "world.zip"
    archive.write_bytes(_zip({"level.dat": b"x"}))
    runtime = tmp_path / "runtime"
    (runtime / "world").mkdir(parents=True)
    (runtime / "world" / "keep.txt").write_text("keep")

    with pytest.raises(RuntimeError, match="already exists"):
        await import_world(str(archive), runtime)
    assert (runtime / "world" / "keep.txt").is_file()
