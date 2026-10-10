from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urlsplit

import httpx

from orchestrator.constants import PlatformType
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


async def _fetch_headers(client: httpx.AsyncClient, url: str) -> httpx.Headers:
    resp = await client.head(url)
    if resp.status_code in (403, 405, 501):
        # Some hosts don't allow HEAD; read the headers of a GET without downloading the body
        async with client.stream("GET", url) as stream:
            stream.raise_for_status()
            return stream.headers
    resp.raise_for_status()
    return resp.headers


class UrlProvider(AbstractPluginProvider):
    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        url = spec.identifier
        headers = await _fetch_headers(client, url)

        etag = headers.get("ETag")
        if etag:
            etag = etag.removeprefix("W/").strip('"')

        last_modified: str | None = None
        version: str | None = None
        if raw := headers.get("Last-Modified"):
            try:
                dt = parsedate_to_datetime(raw)
                last_modified = dt.isoformat()
                version = dt.strftime("%Y-%m-%d_%H-%M-%S")
            except (ValueError, TypeError):
                pass

        filename = _parse_content_disposition_filename(headers.get("Content-Disposition", ""))
        if not filename:
            filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        if not filename:
            raise RuntimeError(f"Could not determine filename for URL: {url}")

        return ResolvedPlugin(
            display_name=filename.removesuffix(".jar"),
            # Without Last-Modified or ETag there is no way to detect updates
            version=version or etag or "url",
            download_url=url,
            filename=filename,
            etag=etag,
            last_modified=last_modified,
        )
