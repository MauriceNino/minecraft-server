"""Set the server icon from ICON: any image, converted to a 64x64 PNG."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from orchestrator.constants import PlatformType
from orchestrator.http import ApiTokens, create_http_client
from orchestrator.lockfile import ServerLockfile, file_matches
from orchestrator.logging import console, log_change
from orchestrator.merger import merge_file_content

ICON_FILENAME = "server-icon.png"
ICON_LOCK_KEY = "server-icon"
ICON_SIZE = (64, 64)


# Pumpkin only reads an icon from `favicon_path`, otherwise it shows its built-in one
PUMPKIN_CONFIG = Path("config") / "configuration.toml"


def _is_url(source: str) -> bool:
    return source.startswith(("https://", "http://"))


def convert_icon(data: bytes) -> bytes:
    """Fit any image into a transparent 64x64 PNG, keeping its aspect ratio."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        fitted = ImageOps.contain(image.convert("RGBA"), ICON_SIZE, Image.Resampling.LANCZOS)
    icon = Image.new("RGBA", ICON_SIZE, (0, 0, 0, 0))
    icon.paste(fitted, ((ICON_SIZE[0] - fitted.width) // 2, (ICON_SIZE[1] - fitted.height) // 2))
    out = io.BytesIO()
    icon.save(out, format="PNG")
    return out.getvalue()


def _read_file(path: Path) -> bytes:
    return path.read_bytes()


async def apply_icon(
    source: str | None,
    runtime_dir: Path,
    lockfile: ServerLockfile,
    tokens: ApiTokens | None = None,
    platform: PlatformType | None = None,
) -> None:
    """Write `server-icon.png` from *source*. When *source* is unset, the icon is kept but no longer managed."""
    await _write_icon(source, runtime_dir, lockfile, tokens)
    if source is not None and platform == PlatformType.PUMPKIN and (runtime_dir / ICON_FILENAME).is_file():
        # Relative to the working directory, the runtime directory. Kept when ICON is removed, like the icon itself.
        merge_file_content(runtime_dir / PUMPKIN_CONFIG, f'use_favicon = true\nfavicon_path = "{ICON_FILENAME}"\n')


async def _write_icon(
    source: str | None, runtime_dir: Path, lockfile: ServerLockfile, tokens: ApiTokens | None
) -> None:
    icon_path = runtime_dir / ICON_FILENAME
    entry = lockfile.extras.get(ICON_LOCK_KEY)

    if source is None:
        if entry is not None:
            # Keep the file, but drop the lock entry: it is no longer downloaded again, so backups must include it
            del lockfile.extras[ICON_LOCK_KEY]
            lockfile.save()
            log_change("skipped", ICON_FILENAME, reason="ICON is no longer set, keeping the icon")
        return

    up_to_date = entry is not None and file_matches(icon_path, entry.sha256)
    try:
        if _is_url(source):
            # A URL is only downloaded again when it changes
            if up_to_date and entry is not None and entry.build == source:
                log_change("skipped", ICON_FILENAME, reason="no changes")
                return
            async with create_http_client(tokens=tokens) as client:
                resp = await client.get(source)
                resp.raise_for_status()
            data, build = resp.content, source
        else:
            data = _read_file(Path(source))
            # The checksum makes a changed file count as a new icon
            build = f"{source}#{hashlib.sha256(data).hexdigest()[:12]}"
            if up_to_date and entry is not None and entry.build == build:
                log_change("skipped", ICON_FILENAME, reason="no changes")
                return
        icon = convert_icon(data)
    except (OSError, httpx.HTTPError, UnidentifiedImageError, Image.DecompressionBombError, ValueError) as e:
        console.print(f"  [warning]⚠[/warning] Could not set the server icon from {source}: {e or type(e).__name__}")
        return

    icon_path.write_bytes(icon)
    lockfile.update_extra(ICON_LOCK_KEY, runtime_dir, icon_path, build)
    lockfile.save()
    log_change("replaced", ICON_FILENAME, reason="64x64 PNG")
