from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import TypedDict, cast

import httpx

from orchestrator.constants import PLATFORM_LOADER_TAGS, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

API_BASE = "https://api.github.com"


class GithubProvider(AbstractPluginProvider):
    def _headers(self) -> dict[str, str]:
        """Build request headers, injecting a Bearer token when GITHUB_TOKEN is set."""
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get_release(self, identifier: str, version: str, client: httpx.AsyncClient) -> GitHubRelease:
        """Fetch the appropriate release based on the version specifier."""
        if version == "latest":
            url = f"{API_BASE}/repos/{identifier}/releases/latest"
        elif version == "experimental":
            # Fetch recent releases and find the first pre-release; fall back to the newest if none found
            resp = await client.get(
                f"{API_BASE}/repos/{identifier}/releases", params={"per_page": 100}, headers=self._headers()
            )
            resp.raise_for_status()
            releases = cast(list[GitHubRelease], resp.json())
            return releases[0]
        else:
            # Treat as an exact tag name
            url = f"{API_BASE}/repos/{identifier}/releases/tags/{version}"

        resp = await client.get(url, headers=self._headers())
        resp.raise_for_status()
        return cast(GitHubRelease, resp.json())

    def _select_asset(
        self, assets: list[GitHubReleaseAsset], spec: PluginSpec, platform_type: PlatformType
    ) -> GitHubReleaseAsset:
        """Pick the single JAR asset to download, using optional regex or automatic detection."""
        owner, repo = spec.identifier.split("/", 1)
        regex = spec.param("regex")

        # 1. Regex mode: must match exactly one asset
        if regex:
            pattern = re.compile(regex)
            matches = [a for a in assets if pattern.search(a["name"])]
            if len(matches) == 1:
                return matches[0]

            names = ", ".join(f"'{a['name']}'" for a in assets)
            if not matches:
                raise RuntimeError(f"No assets match regex {regex!r} for {owner}/{repo}. Available: {names}")
            raise RuntimeError(
                f"Multiple assets match regex {regex!r} for {owner}/{repo}: {', '.join(a['name'] for a in matches)}"
            )

        # 2. Automatic mode: filter to .jar files
        jars = [a for a in assets if a["name"].lower().endswith(".jar")]
        if not jars:
            raise RuntimeError(f"No JAR assets found for {owner}/{repo}")
        if len(jars) == 1:
            return jars[0]

        # 3. Loader keyword disambiguation: try to find a JAR matching the platform (e.g. 'paper', 'spigot')
        loaders = PLATFORM_LOADER_TAGS.get(platform_type, [])
        matches = [jar for jar in jars if any(loader in jar["name"].lower() for loader in loaders)]
        if len(matches) == 1:
            return matches[0]

        raise RuntimeError(
            f"Ambiguous JAR selection for {owner}/{repo} (found {len(jars)} JARs). "
            f"Use \[regex=...] to specify the JAR for {owner}/{repo}. "
            f"The regex needs to match exactly one of: \n{'\n'.join(f'- {j["name"]}' for j in jars)}"
        )

    async def resolve(
        self, spec: PluginSpec, platform_type: PlatformType, mc_version: str, client: httpx.AsyncClient
    ) -> ResolvedPlugin:
        if "/" not in spec.identifier:
            raise ValueError(f"Invalid GitHub identifier {spec.identifier!r}. Expected owner/repo")

        release = await self._get_release(spec.identifier, spec.version, client)
        asset = self._select_asset(release["assets"], spec, platform_type)

        return ResolvedPlugin(
            spec=spec,
            display_name=spec.identifier,
            version=release["tag_name"],
            download_url=asset["browser_download_url"],
            filename=asset["name"],
        )

    async def download(self, resolved: ResolvedPlugin, dest: Path, client: httpx.AsyncClient) -> Path:
        target = dest / resolved.filename
        async with client.stream("GET", resolved.download_url, follow_redirects=True) as resp:
            resp.raise_for_status()
            sha = hashlib.sha256()
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    f.write(chunk)
                    sha.update(chunk)
        return target


class GitHubUser(TypedDict):
    login: str
    id: int
    node_id: str
    avatar_url: str
    gravatar_id: str
    url: str
    html_url: str
    followers_url: str
    following_url: str
    gists_url: str
    starred_url: str
    subscriptions_url: str
    organizations_url: str
    repos_url: str
    events_url: str
    received_events_url: str
    type: str
    user_view_type: str
    site_admin: bool


class GitHubReleaseAsset(TypedDict):
    url: str
    id: int
    node_id: str
    name: str
    label: str | None
    uploader: GitHubUser
    content_type: str
    state: str
    size: int
    digest: str | None
    download_count: int
    created_at: str
    updated_at: str
    browser_download_url: str


class GitHubRelease(TypedDict):
    url: str
    assets_url: str
    upload_url: str
    html_url: str
    id: int
    author: GitHubUser
    node_id: str
    tag_name: str
    target_commitish: str
    name: str
    draft: bool
    immutable: bool
    prerelease: bool
    created_at: str
    updated_at: str
    published_at: str
    assets: list[GitHubReleaseAsset]
    tarball_url: str
    zipball_url: str
    body: str
