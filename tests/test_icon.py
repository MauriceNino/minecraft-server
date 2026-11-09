from __future__ import annotations

import io
import tomllib
from pathlib import Path

from PIL import Image
from pytest_httpx import HTTPXMock

from orchestrator.cli import load_config
from orchestrator.constants import PlatformType
from orchestrator.icon import ICON_FILENAME, ICON_LOCK_KEY, apply_icon, convert_icon
from orchestrator.lockfile import ServerLockfile

URL = "https://cdn.example/logo.jpg"


def _image(size: tuple[int, int], fmt: str, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format=fmt)
    return out.getvalue()


def _lockfile(runtime: Path) -> ServerLockfile:
    return ServerLockfile.load(runtime / "server-lock.json")


def test_converts_and_pads_non_square_images() -> None:
    with Image.open(io.BytesIO(convert_icon(_image((200, 100), "JPEG")))) as icon:
        assert (icon.format, icon.size, icon.mode) == ("PNG", (64, 64), "RGBA")
        assert icon.getpixel((0, 0))[3] == 0  # padding above the image is transparent  # type: ignore[index]
        assert icon.getpixel((32, 32))[3] == 255  # type: ignore[index]


def test_every_platform_takes_an_icon() -> None:
    assert load_config(environ={"TYPE": "VELOCITY", "ICON": URL}).icon == URL
    assert load_config(environ={"TYPE": "PUMPKIN", "ICON": URL}).icon == URL


async def test_pumpkin_is_pointed_at_the_icon(tmp_path: Path) -> None:
    source = tmp_path / "logo.png"
    source.write_bytes(_image((64, 64), "PNG"))
    config = tmp_path / "config" / "configuration.toml"
    config.parent.mkdir()
    config.write_text("java_edition = true\nuse_favicon = false\n")

    await apply_icon(str(source), tmp_path, _lockfile(tmp_path), platform=PlatformType.PUMPKIN)

    data = tomllib.loads(config.read_text())
    assert data == {"java_edition": True, "use_favicon": True, "favicon_path": ICON_FILENAME}


async def test_pumpkin_config_is_untouched_without_an_icon(tmp_path: Path) -> None:
    source = tmp_path / "broken.png"
    source.write_bytes(b"not an image")

    await apply_icon(str(source), tmp_path, _lockfile(tmp_path), platform=PlatformType.PUMPKIN)

    assert not (tmp_path / "config" / "configuration.toml").exists()


async def test_url_is_only_downloaded_once(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=URL, content=_image((128, 128), "JPEG"))
    lockfile = _lockfile(tmp_path)

    await apply_icon(URL, tmp_path, lockfile)
    await apply_icon(URL, tmp_path, _lockfile(tmp_path))

    assert (tmp_path / ICON_FILENAME).is_file()
    assert len(httpx_mock.get_requests()) == 1


async def test_file_is_converted_again_when_it_changes(tmp_path: Path) -> None:
    source = tmp_path / "logo.webp"
    source.write_bytes(_image((64, 64), "WEBP", (255, 0, 0)))
    await apply_icon(str(source), tmp_path, _lockfile(tmp_path))
    first = (tmp_path / ICON_FILENAME).read_bytes()

    source.write_bytes(_image((64, 64), "WEBP", (0, 0, 255)))
    await apply_icon(str(source), tmp_path, _lockfile(tmp_path))

    assert (tmp_path / ICON_FILENAME).read_bytes() != first


async def test_invalid_image_is_skipped(tmp_path: Path) -> None:
    source = tmp_path / "logo.png"
    source.write_bytes(b"not an image")

    await apply_icon(str(source), tmp_path, _lockfile(tmp_path))

    assert not (tmp_path / ICON_FILENAME).exists()


async def test_icon_is_kept_when_unset(tmp_path: Path) -> None:
    source = tmp_path / "logo.png"
    source.write_bytes(_image((64, 64), "PNG"))
    await apply_icon(str(source), tmp_path, _lockfile(tmp_path))

    lockfile = _lockfile(tmp_path)
    await apply_icon(None, tmp_path, lockfile)

    assert (tmp_path / ICON_FILENAME).exists()
    assert ICON_LOCK_KEY not in _lockfile(tmp_path).extras
