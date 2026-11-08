from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from orchestrator.constants import PlatformType, PluginProviderType
from orchestrator.http import ApiTokens, create_http_client
from orchestrator.plugins.base import PluginSpec
from orchestrator.plugins.curseforge import CurseForgeProvider

API = "https://api.curseforge.com/v1"
TOKENS = ApiTokens(curseforge="key")


def _file(name: str, date: str, release_type: int = 1, download_url: str | None = "https://cdn.example/x.jar") -> dict:
    return {
        "displayName": name,
        "fileName": f"{name}.jar",
        "fileDate": date,
        "releaseType": release_type,
        "hashes": [],
        "downloadUrl": download_url,
        "gameVersions": ["1.21.4", "Bukkit"],
    }


def _mock_mod(httpx_mock: HTTPXMock, pages: list[list[dict]]) -> None:
    httpx_mock.add_response(url=f"{API}/mods/42", json={"data": {"id": 42, "name": "Demo"}})
    total = sum(len(p) for p in pages)
    for index, page in enumerate(pages):
        httpx_mock.add_response(
            url=f"{API}/mods/42/files?pageSize=50&gameVersion=1.21.4&index={index * 50}",
            json={"data": page, "pagination": {"totalCount": total}},
        )


def _spec(version: str = "latest") -> PluginSpec:
    return PluginSpec(PluginProviderType.CURSEFORGE, "42", version, force=False)


async def test_picks_newest_release_across_pages(httpx_mock: HTTPXMock) -> None:
    first_page = [_file(f"old-{i}", f"2024-01-{i + 1:02d}T00:00:00Z") for i in range(50)]
    second_page = [
        _file("newest-beta", "2026-03-01T00:00:00Z", release_type=2),
        _file("newest-release", "2026-02-01T00:00:00Z"),
    ]
    _mock_mod(httpx_mock, [first_page, second_page])

    async with create_http_client(tokens=TOKENS) as client:
        resolved = await CurseForgeProvider().resolve(_spec(), PlatformType.PAPER, "1.21.4", client)

    assert resolved.version == "newest-release"


async def test_experimental_includes_betas(httpx_mock: HTTPXMock) -> None:
    _mock_mod(httpx_mock, [[_file("release", "2026-02-01T00:00:00Z"), _file("beta", "2026-03-01T00:00:00Z", 2)]])

    async with create_http_client(tokens=TOKENS) as client:
        resolved = await CurseForgeProvider().resolve(_spec("experimental"), PlatformType.PAPER, "1.21.4", client)

    assert resolved.version == "beta"


async def test_third_party_downloads_disabled(httpx_mock: HTTPXMock) -> None:
    _mock_mod(httpx_mock, [[_file("release", "2026-02-01T00:00:00Z", download_url=None)]])

    async with create_http_client(tokens=TOKENS) as client:
        with pytest.raises(RuntimeError, match="disabled third-party downloads"):
            await CurseForgeProvider().resolve(_spec(), PlatformType.PAPER, "1.21.4", client)


async def test_sends_api_key(httpx_mock: HTTPXMock) -> None:
    _mock_mod(httpx_mock, [[_file("release", "2026-02-01T00:00:00Z")]])

    async with create_http_client(tokens=TOKENS) as client:
        await CurseForgeProvider().resolve(_spec(), PlatformType.PAPER, "1.21.4", client)

    assert all(r.headers["x-api-key"] == "key" for r in httpx_mock.get_requests())


async def test_missing_api_key(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{API}/mods/42", status_code=403)

    async with create_http_client() as client:
        with pytest.raises(RuntimeError, match="CURSEFORGE_API_KEY"):
            await CurseForgeProvider().resolve(_spec(), PlatformType.PAPER, "1.21.4", client)
