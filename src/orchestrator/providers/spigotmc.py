from __future__ import annotations

import re
from pathlib import Path

import httpx

from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

# getbukkit.org lists versions as `<h4>Version</h4> <h2>1.21.4</h2>`, newest first
_VERSION_RE = re.compile(r"<h4>Version</h4>\s*<h2>([^<]+)</h2>", re.IGNORECASE)


class GetBukkitProvider(AbstractPlatformProvider):
    def __init__(self, project: str) -> None:
        self.project = project  # "spigot" or "craftbukkit"

    async def _resolve_latest_version(self, client: httpx.AsyncClient) -> str:
        resp = await client.get(f"https://getbukkit.org/download/{self.project}")
        resp.raise_for_status()

        match = _VERSION_RE.search(resp.text)
        if not match:
            raise RuntimeError(f"Could not find latest version on GetBukkit for {self.project}")
        return match.group(1).strip()

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        if version in ("latest", "experimental"):
            version = await self._resolve_latest_version(client)

        filename = f"{self.project}-{version}.jar"
        return ResolvedVersion(
            project=self.project,
            version=version,
            build="stable",
            download_url=f"https://cdn.getbukkit.org/{self.project}/{filename}",
            filename=filename,
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        try:
            return await super().download(resolved, dest, client)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
            raise RuntimeError(
                f"Direct download for {self.project} {resolved.version} failed (404). "
                f"The version might be incorrect or not hosted on cdn.getbukkit.org. "
                f"URL: [link]{resolved.download_url}[/link]"
            ) from None
