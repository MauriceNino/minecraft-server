from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from orchestrator.constants import USER_AGENT


def create_http_client(*, timeout: float = 60.0, connect_timeout: float = 15.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        headers={"User-Agent": USER_AGENT},
    )


def safe_filename(name: str) -> str:
    """Strip any directory components from a remotely supplied filename."""
    clean = Path(name.replace("\\", "/")).name
    if clean in ("", ".", ".."):
        raise ValueError(f"Refusing to use unsafe filename {name!r}")
    return clean


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    checksums: dict[str, str | None] | None = None,
) -> None:
    """Stream *url* into *target*, verifying any given checksums (keyed by hashlib algorithm name).

    The partially written file is removed if the download or verification fails.
    """
    expected = {algo: value.lower() for algo, value in (checksums or {}).items() if value}
    hashers = {algo: hashlib.new(algo) for algo in expected}

    try:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    for hasher in hashers.values():
                        hasher.update(chunk)

        for algo, hasher in hashers.items():
            if hasher.hexdigest() != expected[algo]:
                raise RuntimeError(f"{algo.upper()} checksum mismatch for {target.name}")
    except BaseException:
        target.unlink(missing_ok=True)  # noqa: ASYNC240
        raise
