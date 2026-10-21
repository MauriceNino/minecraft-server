from __future__ import annotations

import pytest

from orchestrator.runner import java_compatibility_warning


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
