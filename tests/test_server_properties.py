from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.cli import load_config
from orchestrator.constants import PlatformType
from orchestrator.merger.properties_merger import read_properties
from orchestrator.server_properties import apply_server_properties, collect_server_properties


def test_collects_and_normalizes() -> None:
    env = {"MOTD": " My Server ", "DIFFICULTY": "Hard", "ONLINE_MODE": "FALSE", "SEED": "-123", "PVP": ""}
    assert collect_server_properties(env, PlatformType.PAPER) == {
        "motd": "My Server",
        "difficulty": "hard",
        "online-mode": "false",
        "level-seed": "-123",
    }


@pytest.mark.parametrize("platform", [PlatformType.VELOCITY, PlatformType.BUNGEECORD, PlatformType.PUMPKIN])
def test_ignored_without_server_properties(platform: PlatformType) -> None:
    assert collect_server_properties({"MOTD": "Hi"}, platform) == {}


@pytest.mark.parametrize(("var", "value"), [("PVP", "yes"), ("MAX_PLAYERS", "ten"), ("SERVER_PORT", "-1")])
def test_invalid_values(var: str, value: str) -> None:
    with pytest.raises(SystemExit, match=f"Invalid {var}"):
        load_config(environ={var: value})


def test_apply_creates_and_merges(tmp_path: Path) -> None:
    apply_server_properties({"motd": "Héllo = world", "max-players": "5"}, tmp_path)
    (tmp_path / "server.properties").write_text(
        (tmp_path / "server.properties").read_text() + "view-distance=10\n", encoding="utf-8"
    )
    apply_server_properties({"max-players": "8"}, tmp_path)

    props = read_properties(tmp_path / "server.properties")
    assert props == {"motd": "H\\u00e9llo = world", "max-players": "8", "view-distance": "10"}
