from __future__ import annotations

import os
import re
from typing import TypedDict, cast

import httpx

from orchestrator.constants import MODRINTH_PLATFORM_TAGS, PlatformType
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

API_BASE = "https://api.github.com"


class GithubProvider(AbstractPluginProvider):
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get_release(self, spec: PluginSpec, client: httpx.AsyncClient) -> GitHubRelease:
        if spec.version == "experimental":
            resp = await client.get(
                f"{API_BASE}/repos/{spec.identifier}/releases", params={"per_page": 100}, headers=self._headers()
            )
            resp.raise_for_status()
            releases = [r for r in cast(list[GitHubRelease], resp.json()) if not r["draft"]]
            if not releases:
                raise RuntimeError(f"No releases found for {spec.identifier}")
            # Newest pre-release, or the newest release if the repo never publishes pre-releases
            return next((r for r in releases if r["prerelease"]), releases[0])

        if spec.version == "latest":
            url = f"{API_BASE}/repos/{spec.identifier}/releases/latest"
        else:
            url = f"{API_BASE}/repos/{spec.identifier}/releases/tags/{spec.version}"

        resp = await client.get(url, headers=self._headers())
        if resp.status_code == 404:
            raise self._version_could_not_be_found(spec)
        resp.raise_for_status()
        return cast(GitHubRelease, resp.json())

    def _select_asset(self, assets: list[GitHubAsset], spec: PluginSpec, platform_type: PlatformType) -> GitHubAsset:
        if regex := spec.param("regex"):
            pattern = re.compile(regex)
            matches = [a for a in assets if pattern.search(a["name"])]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                names = ", ".join(f"'{a['name']}'" for a in assets)
                raise RuntimeError(f"No assets match regex {regex!r} for {spec.identifier}. Available: {names}")
            raise RuntimeError(
                f"Multiple assets match regex {regex!r} for {spec.identifier}: {', '.join(a['name'] for a in matches)}"
            )

        jars = [a for a in assets if a["name"].lower().endswith(".jar")]
        if not jars:
            raise RuntimeError(f"No JAR assets found for {spec.identifier}")
        if len(jars) == 1:
            return jars[0]

        # Several JARs: try to pick the one named after the platform (e.g. "-paper", "-velocity")
        loaders = MODRINTH_PLATFORM_TAGS.get(platform_type, [])
        matches = [jar for jar in jars if any(loader in jar["name"].lower() for loader in loaders)]
        if len(matches) == 1:
            return matches[0]

        jar_list = "\n".join(f"- {j['name']}" for j in jars)
        raise RuntimeError(
            f"Ambiguous JAR selection for {spec.identifier} (found {len(jars)} JARs). "
            f"Use \\[regex=...] to pick one. The regex needs to match exactly one of:\n{jar_list}"
        )

    async def resolve(
        self, spec: PluginSpec, platform_type: PlatformType, mc_version: str, client: httpx.AsyncClient
    ) -> ResolvedPlugin:
        if spec.identifier.count("/") != 1:
            raise ValueError(f"Invalid GitHub identifier {spec.identifier!r}. Expected owner/repo")

        release = await self._get_release(spec, client)
        asset = self._select_asset(release["assets"], spec, platform_type)

        digest = asset.get("digest") or ""
        return ResolvedPlugin(
            display_name=spec.identifier,
            version=release["tag_name"],
            download_url=asset["browser_download_url"],
            filename=asset["name"],
            sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
        )


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


class GitHubAsset(TypedDict):
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
    assets: list[GitHubAsset]
    tarball_url: str
    zipball_url: str
    body: str
