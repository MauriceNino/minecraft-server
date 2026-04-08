from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from orchestrator.constants import PlatformType
from orchestrator.logging import get_logger
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

log = get_logger(__name__)


def _parse_content_disposition_filename(header: str) -> str | None:
    """Extract a sane filename from a Content-Disposition header.

    Handles both the legacy `filename="..."` form and the RFC 5987
    `filename*=UTF-8''...` extended form (the latter takes precedence).
    """
    # RFC 5987 extended value takes priority: filename*=UTF-8''floodgate-spigot.jar
    m = re.search(r"filename\*=(?:[A-Za-z0-9-]+'')?([^;\s]+)", header, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip())

    # Plain filename="..." or filename=...  — skip RFC 2047 encoded values (=?...?=)
    m = re.search(r'filename=["\']?([^"\';\s]+)["\']?', header, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        if not name.startswith("=?"):
            return name

    return None


class UrlProvider(AbstractPluginProvider):
    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        url = spec.identifier

        try:
            head_resp = await client.head(url, follow_redirects=True)
            head_resp.raise_for_status()
        except httpx.HTTPError:
            head_resp = None

        etag = head_resp.headers.get("ETag") if head_resp else None
        etag = etag.strip('"') if etag else None
        last_modified = head_resp.headers.get("Last-Modified") if head_resp else None
        last_modified = (
            datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z").isoformat() if last_modified else None
        )

        filename: str | None = None
        if head_resp:
            cd = head_resp.headers.get("Content-Disposition", "")
            if cd:
                filename = _parse_content_disposition_filename(cd)

        if not filename:
            url_path = urlsplit(url).path
            filename = url_path.rsplit("/", 1)[-1]

        if not filename:
            raise RuntimeError(f"Could not determine filename for URL: {url}")

        display_name = filename[:-4] if filename.endswith(".jar") else filename

        return ResolvedPlugin(
            spec=spec,
            display_name=display_name,
            version="url",
            download_url=url,
            filename=filename,
            etag=etag,
            last_modified=last_modified,
        )

    async def download(
        self,
        resolved: ResolvedPlugin,
        dest: Path,
        client: httpx.AsyncClient,
    ) -> Path:
        target = dest / resolved.filename
        async with client.stream("GET", resolved.download_url, follow_redirects=True) as resp:
            resp.raise_for_status()
            sha = hashlib.sha256()
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    sha.update(chunk)

        return target
