from __future__ import annotations

import re
from pathlib import Path

import httpx

from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion


class GetBukkitProvider(AbstractPlatformProvider):
    def __init__(self, project: str = "spigot") -> None:
        self._project = project  # "spigot" or "craftbukkit"

    async def _resolve_latest_from_getbukkit(self, client: httpx.AsyncClient) -> str:
        url = f"https://getbukkit.org/download/{self._project}"
        resp = await client.get(url)
        resp.raise_for_status()

        # Simple regex to find the first version number in the HTML
        # The structure seen on getbukkit.org is:
        # <div class="col-md-3">
        #     <h4>Version</h4>
        #     <h2>1.20.1</h2>
        # </div>
        pattern = re.compile(r"<h4>Version</h4>\s*<h2>([^<]+)</h2>", re.IGNORECASE | re.DOTALL)

        match = pattern.search(resp.text)
        if not match:
            raise RuntimeError(f"Could not find latest version on GetBukkit for {self._project}")

        return match.group(1).strip()

    async def resolve_version(
        self,
        version: str,
        build: str,
        client: httpx.AsyncClient,
    ) -> ResolvedVersion:
        target_version = version
        if target_version in ("latest", "experimental"):
            target_version = await self._resolve_latest_from_getbukkit(client)

        download_url = f"https://cdn.getbukkit.org/{self._project}/{self._project}-{target_version}.jar"

        return ResolvedVersion(
            project=self._project,
            version=target_version,
            build="stable",
            download_url=download_url,
            filename=f"{self._project}-{target_version}.jar",
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        target = dest / resolved.filename

        async with client.stream("GET", resolved.download_url) as resp:
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Direct download for {self._project} {resolved.version} failed (404). "
                    f"The version might be incorrect or not hosted on cdn.getbukkit.org. "
                    f"URL: [link]{resolved.download_url}[/link]"
                )

            resp.raise_for_status()

            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)

        return target
