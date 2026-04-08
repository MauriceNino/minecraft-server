"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_runtime(tmp_path: Path) -> Path:
    """Create a temporary runtime directory."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    return runtime


@pytest.fixture
def tmp_templates(tmp_path: Path) -> Path:
    """Create a temporary templates directory."""
    templates = tmp_path / "templates"
    templates.mkdir()
    return templates
