from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.constants import PlatformType
from orchestrator.runner import build_java_command, java_compatibility_warning


@pytest.mark.parametrize(
    ("mc_version", "java_version"),
    [("1.21.4", 21), ("1.21.4", 25), ("26.1", 25), ("1.20.4", 17), ("1.16.5", 11), ("1.8.8", 8), ("25w14a", 8)],
)
def test_compatible(mc_version: str, java_version: int) -> None:
    assert java_compatibility_warning(mc_version, java_version) is None


@pytest.mark.parametrize(
    ("mc_version", "java_version", "message"),
    [
        ("26.1", 21, "requires Java 25"),
        ("26.1.2", 23, "requires Java 25"),
        ("1.21.4", 17, "requires Java 21"),
        ("1.18.2", 11, "requires Java 17"),
        ("1.12.2", 21, "newer than 17"),
    ],
)
def test_incompatible(mc_version: str, java_version: int, message: str) -> None:
    warning = java_compatibility_warning(mc_version, java_version)
    assert warning is not None
    assert message in warning


@pytest.mark.parametrize(("java_version", "kept"), [(8, False), (11, False), (17, True), (None, True)])
def test_vector_module_flag_only_on_java_16_plus(java_version: int | None, kept: bool) -> None:
    flags = ["--add-modules=jdk.incubator.vector", "-XX:+UseG1GC"]

    args = build_java_command(Path("server.jar"), "1G", flags, PlatformType.PAPER, java_version)

    assert ("--add-modules=jdk.incubator.vector" in args) is kept
    assert "-XX:+UseG1GC" in args
    assert args[-3:] == ["-jar", "server.jar", "--nogui"]
