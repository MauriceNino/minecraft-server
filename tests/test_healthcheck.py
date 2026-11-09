from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestrator.cli import load_config
from orchestrator.healthcheck import (
    ServerAddress,
    _read_varint,
    _varint,
    check_health,
    server_address,
    status_ping,
)

STATUS = {"version": {"name": "1.21.4", "protocol": 769}, "players": {"online": 2, "max": 20}}


@pytest.fixture
def fake_server() -> Iterator[int]:
    """A minimal server that answers one status request."""
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve() -> None:
        conn, _ = listener.accept()
        with conn:
            for _ in range(2):  # handshake + status request
                conn.recv(_read_varint(conn))
            payload = json.dumps(STATUS).encode()
            body = _varint(0) + _varint(len(payload)) + payload
            conn.sendall(_varint(len(body)) + body)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield port
    listener.close()
    thread.join(timeout=5)


def test_status_ping(fake_server: int) -> None:
    assert status_ping("127.0.0.1", fake_server) == STATUS


def test_check_health(tmp_path: Path, fake_server: int) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "server.properties").write_text(f"#comment\nserver-port={fake_server}\n")

    healthy, message = check_health(load_config({"DATA_DIR": str(tmp_path)}))

    assert healthy
    assert "2/20 players" in message


def test_check_health_fails_without_server(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    (runtime / "server.properties").write_text(f"server-port={free_port}\n")

    healthy, message = check_health(load_config({"DATA_DIR": str(tmp_path)}))

    assert not healthy
    assert str(free_port) in message


def test_check_health_without_status_only_connects(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with socket.create_server(("127.0.0.1", 0)) as listener:  # accepts, but never answers
        port = listener.getsockname()[1]
        (runtime / "server.properties").write_text(f"server-port={port}\nenable-status=false\n")

        healthy, message = check_health(load_config({"DATA_DIR": str(tmp_path)}))

    assert healthy
    assert "accepts connections" in message


@pytest.mark.parametrize(
    ("platform", "path", "content", "expected"),
    [
        ("PAPER", "server.properties", "server-port=25599\n", ServerAddress("127.0.0.1", 25599)),
        ("PAPER", None, None, ServerAddress("127.0.0.1", 25565)),
        (
            "PAPER",
            "server.properties",
            "server-ip=10.0.0.5\nserver-port=25599\nenable-status=false\n",
            ServerAddress("10.0.0.5", 25599, status_enabled=False),
        ),
        ("VELOCITY", "velocity.toml", 'bind = "0.0.0.0:25588"\n', ServerAddress("127.0.0.1", 25588)),
        ("VELOCITY", "velocity.toml", 'bind = "10.0.0.5:25588"\n', ServerAddress("10.0.0.5", 25588)),
        ("VELOCITY", "velocity.toml", 'bind = "[::]:25588"\n', ServerAddress("127.0.0.1", 25588)),
        ("VELOCITY", None, None, ServerAddress("127.0.0.1", 25577)),
        ("WATERFALL", "config.yml", "listeners:\n- host: 0.0.0.0:25590\n", ServerAddress("127.0.0.1", 25590)),
        ("BUNGEECORD", "config.yml", "listeners:\n- host: 0.0.0.0:25592\n", ServerAddress("127.0.0.1", 25592)),
        (
            "PUMPKIN",
            "config/configuration.toml",
            'java_edition_address = "0.0.0.0:25591"\n',
            ServerAddress("127.0.0.1", 25591),
        ),
    ],
)
def test_server_address(
    tmp_path: Path, platform: str, path: str | None, content: str | None, expected: ServerAddress
) -> None:
    if path and content:
        target = tmp_path / "runtime" / path
        target.parent.mkdir(parents=True)
        target.write_text(content)

    config = load_config({"DATA_DIR": str(tmp_path), "TYPE": platform, "VERSION": "experimental"})

    assert server_address(config) == expected
