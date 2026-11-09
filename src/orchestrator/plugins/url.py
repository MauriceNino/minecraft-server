from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

import httpx

from orchestrator.constants import PlatformType
from orchestrator.http import fetch_headers, remote_version
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin


def _parse_content_disposition_filename(header: str) -> str | None:
    """Extract the filename from a Content-Disposition header.

    The RFC 5987 `filename*=UTF-8''...` form takes precedence over the plain `filename="..."` form.
    """
    m = re.search(r"filename\*=(?:[A-Za-z0-9-]+'[^']*')?([^;\s]+)", header, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip().strip('"'))

    m = re.search(r'filename=["\']?([^"\';]+)["\']?', header, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        # Skip RFC 2047 encoded values (=?utf-8?...?=)
        if name and not name.startswith("=?"):
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
        headers = await fetch_headers(client, url)
        remote = remote_version(headers)

        filename = _parse_content_disposition_filename(headers.get("Content-Disposition", ""))
        if not filename:
            filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        if not filename:
            raise RuntimeError(f"Could not determine filename for URL: {url}")

        return ResolvedPlugin(
            display_name=filename.removesuffix(".jar"),
            # Without Last-Modified or ETag there is no way to detect updates
            version=remote.version or "url",
            download_url=url,
            filename=filename,
            etag=remote.etag,
            last_modified=remote.last_modified,
        )
