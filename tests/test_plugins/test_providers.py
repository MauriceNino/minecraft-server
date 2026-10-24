from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from orchestrator.constants import PlatformType, PluginProviderType
from orchestrator.http import create_http_client
from orchestrator.plugins.base import PluginSpec
from orchestrator.plugins.github import GithubProvider
from orchestrator.plugins.hangar import HangarProvider
from orchestrator.plugins.spiget import SpigetProvider
from orchestrator.plugins.url import UrlProvider, _parse_content_disposition_filename


def _spec(provider: PluginProviderType, identifier: str, version: str = "latest", **params: str) -> PluginSpec:
    return PluginSpec(provider, identifier, version, force=False, params=params)


class TestHangar:
    API = "https://hangar.papermc.io/api/v1/projects/Demo"

    @staticmethod
    def _version(name: str, channel: str, mc_versions: list[str], platforms: tuple[str, ...] = ("PAPER",)) -> dict:
        return {
            "name": name,
            "channel": {"name": channel},
            "downloads": {
                p: {
                    "fileInfo": {"name": f"demo-{name}.jar", "sha256Hash": "ab"},
                    "downloadUrl": f"https://hangar.example/{name}.jar",
                    "externalUrl": None,
                }
                for p in platforms
            },
            "platformDependencies": {p: mc_versions for p in platforms},
        }

    def _mock(self, httpx_mock: HTTPXMock, versions: list[dict], tags: list[str] | None = None) -> None:
        httpx_mock.add_response(
            url=self.API,
            json={"name": "Demo", "settings": {"tags": tags or []}, "supportedPlatforms": {"PAPER": ["1.21"]}},
        )
        httpx_mock.add_response(
            url=f"{self.API}/versions?offset=0&limit=50",
            json={"pagination": {"count": len(versions)}, "result": versions},
        )

    async def test_latest_skips_incompatible_and_wrong_platform(self, httpx_mock: HTTPXMock) -> None:
        self._mock(
            httpx_mock,
            [
                self._version("3.0", "Snapshot", ["1.21.4"]),
                self._version("2.1", "Release", ["1.21.4"], platforms=("VELOCITY",)),
                self._version("2.0", "Release", ["1.22"]),
                self._version("1.9", "Release", ["1.21", "1.21.4"]),
            ],
        )

        async with create_http_client() as client:
            resolved = await HangarProvider().resolve(
                _spec(PluginProviderType.HANGAR, "Demo"), PlatformType.PAPER, "1.21.4", client
            )

        assert resolved.version == "1.9"
        assert resolved.sha256 == "ab"

    async def test_folia_requires_tag(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=self.API,
            json={"name": "Demo", "settings": {"tags": []}, "supportedPlatforms": {"PAPER": ["1.21"]}},
        )

        async with create_http_client() as client:
            with pytest.raises(RuntimeError, match="does not support platform 'FOLIA'"):
                await HangarProvider().resolve(
                    _spec(PluginProviderType.HANGAR, "Demo"), PlatformType.FOLIA, "1.21.4", client
                )


class TestGithub:
    API = "https://api.github.com/repos/owner/repo"

    @staticmethod
    def _release(tag: str, assets: list[str], prerelease: bool = False) -> dict:
        return {
            "tag_name": tag,
            "draft": False,
            "prerelease": prerelease,
            "assets": [
                {"name": a, "digest": "sha256:ff", "browser_download_url": f"https://gh.example/{a}"} for a in assets
            ],
        }

    async def test_latest_with_platform_disambiguation(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=f"{self.API}/releases/latest",
            json=self._release("v1", ["demo-paper.jar", "demo-velocity.jar", "sources.zip"]),
        )

        async with create_http_client() as client:
            resolved = await GithubProvider().resolve(
                _spec(PluginProviderType.GITHUB, "owner/repo"), PlatformType.PAPER, "1.21.4", client
            )

        assert resolved.filename == "demo-paper.jar"
        assert resolved.sha256 == "ff"

    async def test_experimental_prefers_prerelease(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=f"{self.API}/releases?per_page=100",
            json=[self._release("v2", ["a.jar"]), self._release("v2-rc1", ["a.jar"], prerelease=True)],
        )

        async with create_http_client() as client:
            resolved = await GithubProvider().resolve(
                _spec(PluginProviderType.GITHUB, "owner/repo", "experimental"), PlatformType.PAPER, "1.21.4", client
            )

        assert resolved.version == "v2-rc1"

    async def test_ambiguous_assets(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{self.API}/releases/latest", json=self._release("v1", ["a.jar", "b.jar"]))

        async with create_http_client() as client:
            with pytest.raises(RuntimeError, match="Ambiguous JAR selection"):
                await GithubProvider().resolve(
                    _spec(PluginProviderType.GITHUB, "owner/repo"), PlatformType.PAPER, "1.21.4", client
                )

    async def test_regex(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=f"{self.API}/releases/latest", json=self._release("v1", ["a-1.jar", "b-1.jar"]))

        async with create_http_client() as client:
            resolved = await GithubProvider().resolve(
                _spec(PluginProviderType.GITHUB, "owner/repo", regex=r"^b-\d"), PlatformType.PAPER, "1.21.4", client
            )

        assert resolved.filename == "b-1.jar"


class TestSpiget:
    API = "https://api.spiget.org/v2/resources/1331"

    def _mock(self, httpx_mock: HTTPXMock, **overrides: object) -> None:
        resource = {
            "name": "SuperVanish",
            "external": False,
            "premium": False,
            "testedVersions": ["1.20", "1.21"],
            "versions": [{"id": 10}, {"id": 11}],
            "version": {"id": 11},
        }
        httpx_mock.add_response(url=self.API, json=resource | overrides)

    async def test_slug_identifier(self, httpx_mock: HTTPXMock) -> None:
        self._mock(httpx_mock)

        async with create_http_client() as client:
            resolved = await SpigetProvider().resolve(
                _spec(PluginProviderType.SPIGET, "supervanish-be-invisible.1331"), PlatformType.PAPER, "1.21.4", client
            )

        assert resolved.version == "11"
        assert resolved.download_url == f"{self.API}/download?version=11"

    async def test_premium(self, httpx_mock: HTTPXMock) -> None:
        self._mock(httpx_mock, premium=True)

        async with create_http_client() as client:
            with pytest.raises(RuntimeError, match="premium"):
                await SpigetProvider().resolve(
                    _spec(PluginProviderType.SPIGET, "1331"), PlatformType.PAPER, "1.21", client
                )


class TestUrl:
    URL = "https://ci.example/job/Plugin%20Build.jar"

    async def test_version_from_last_modified(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=self.URL, method="HEAD", headers={"Last-Modified": "Wed, 01 Oct 2026 12:00:00 GMT", "ETag": 'W/"abc"'}
        )

        async with create_http_client() as client:
            resolved = await UrlProvider().resolve(
                _spec(PluginProviderType.URL, self.URL), PlatformType.PAPER, "", client
            )

        assert resolved.version == "2026-10-01_12-00-00"
        assert resolved.etag == "abc"
        assert resolved.filename == "Plugin Build.jar"

    async def test_falls_back_to_get_when_head_not_allowed(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=self.URL, method="HEAD", status_code=405)
        httpx_mock.add_response(
            url=self.URL,
            method="GET",
            headers={"ETag": '"v2"', "Content-Disposition": 'attachment; filename="plugin-2.jar"'},
        )

        async with create_http_client() as client:
            resolved = await UrlProvider().resolve(
                _spec(PluginProviderType.URL, self.URL), PlatformType.PAPER, "", client
            )

        assert resolved.version == "v2"
        assert resolved.filename == "plugin-2.jar"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('attachment; filename="plugin.jar"', "plugin.jar"),
        ("attachment; filename*=UTF-8''floodgate%20spigot.jar", "floodgate spigot.jar"),
        ("attachment; filename*=UTF-8'en'x.jar; filename=\"fallback.jar\"", "x.jar"),
        ("attachment; filename==?utf-8?b?abc?=", None),
        ("inline", None),
    ],
)
def test_content_disposition(header: str, expected: str | None) -> None:
    assert _parse_content_disposition_filename(header) == expected
