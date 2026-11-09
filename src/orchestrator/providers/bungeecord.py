from __future__ import annotations

from typing import NotRequired, TypedDict, cast

import httpx

from orchestrator.constants import UNKNOWN_MC_VERSION
from orchestrator.logging import console
from orchestrator.providers.base import AbstractPlatformProvider, ResolvedVersion

JENKINS_JOB = "https://hub.spigotmc.org/jenkins/job/BungeeCord"
ARTIFACT_PATH = "bootstrap/target/BungeeCord.jar"


class BungeeCordProvider(AbstractPlatformProvider):
    """BungeeCord from SpigotMC's Jenkins. It has no Minecraft version, only build numbers."""

    project = "bungeecord"

    async def resolve_version(self, version: str, build: str, client: httpx.AsyncClient) -> ResolvedVersion:
        if version not in ("latest", "experimental"):
            console.print(
                f"  [warning]⚠[/warning] BungeeCord has no Minecraft versions, VERSION={version} is ignored. "
                "Use BUILD to pin a Jenkins build."
            )

        path = "lastSuccessfulBuild" if build in ("latest", "experimental") else build
        resp = await client.get(
            f"{JENKINS_JOB}/{path}/api/json", params={"tree": "number,result,artifacts[relativePath]"}
        )
        if resp.status_code == 404:
            raise RuntimeError(f"BungeeCord build {build!r} not found on {JENKINS_JOB}")
        resp.raise_for_status()
        data = cast(JenkinsBuild, resp.json())

        if data.get("result") != "SUCCESS":
            raise RuntimeError(f"BungeeCord build {data['number']} did not succeed ({data.get('result')})")
        if not any(a["relativePath"] == ARTIFACT_PATH for a in data.get("artifacts", [])):
            raise RuntimeError(f"BungeeCord build {data['number']} has no {ARTIFACT_PATH}")

        number = str(data["number"])
        return ResolvedVersion(
            project=self.project,
            version=UNKNOWN_MC_VERSION,
            build=number,
            download_url=f"{JENKINS_JOB}/{number}/artifact/{ARTIFACT_PATH}",
            filename=f"bungeecord-{number}.jar",
        )


class JenkinsArtifact(TypedDict):
    relativePath: str


class JenkinsBuild(TypedDict):
    number: int
    result: NotRequired[str | None]
    artifacts: NotRequired[list[JenkinsArtifact]]
