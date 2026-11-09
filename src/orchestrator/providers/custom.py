from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from orchestrator.constants import UNKNOWN_MC_VERSION
from orchestrator.http import download_file, safe_filename, url_build
from orchestrator.logging import console
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

DEFAULT_FILENAME = "custom-server.jar"


def is_url(source: str) -> bool:
    return source.startswith(("https://", "http://"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CustomProvider(AbstractPlatformProvider):
    """Any server JAR from `CUSTOM_JAR`, passed in as the build.

    A URL is downloaded again when it changes or when its `Last-Modified` or `ETag` header changes. A file in
    the container is copied into the runtime directory again whenever its content changes.
    """

    project = "custom"

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        source = build
        if version in ("latest", "experimental"):
            console.print(
                "  [info]🛈[/info] Set VERSION to the Minecraft version of the custom JAR "
                "to check plugins and Java against it"
            )
            mc_version = UNKNOWN_MC_VERSION
        else:
            mc_version = version

        if is_url(source):
            name = unquote(urlsplit(source).path.rsplit("/", 1)[-1])
            return ResolvedVersion(
                project=self.project,
                version=mc_version,
                # Changes when the file behind the URL changes, if the server sends Last-Modified or ETag
                build=await url_build(client, source),
                download_url=source,
                filename=safe_filename(name) if name.endswith(".jar") else DEFAULT_FILENAME,
            )

        return self._resolve_file(Path(source), mc_version)

    def _resolve_file(self, path: Path, mc_version: str) -> ResolvedVersion:
        source = str(path)
        if not path.is_file():
            raise RuntimeError(f"CUSTOM_JAR={source} is not a file in the container")
        sha256 = _sha256(path)
        return ResolvedVersion(
            project=self.project,
            version=mc_version,
            # The checksum makes a changed file count as a new build
            build=f"{source}#{sha256[:12]}",
            download_url=source,
            filename=path.name if path.name.endswith(".jar") else DEFAULT_FILENAME,
            sha256=sha256,
        )

    async def download(self, resolved: ResolvedVersion, dest: Path, client: httpx.AsyncClient) -> Path:
        target = dest / resolved.filename
        if is_url(resolved.download_url):
            await download_file(client, resolved.download_url, target)
        else:
            shutil.copyfile(resolved.download_url, target)
        return target
