"""Docker health check: a Minecraft status ping (Server List Ping) against the local server."""

from __future__ import annotations

import json
import socket
import struct
import tomllib
from dataclasses import dataclass

from ruamel.yaml import YAML

from orchestrator.cli import Config
from orchestrator.constants import BUNGEE_PLATFORMS, PROXY_PLATFORMS, PlatformType
from orchestrator.merger.properties_merger import read_properties

DEFAULT_SERVER_PORT = 25565
DEFAULT_PROXY_PORT = 25577
LOCALHOST = "127.0.0.1"
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "*"})  # noqa: S104


@dataclass(frozen=True, slots=True)
class ServerAddress:
    host: str
    port: int
    # False when the server doesn't answer status pings (`enable-status=false`)
    status_enabled: bool = True


def _connect_host(host: str) -> str:
    """The host to connect to for a configured bind address, localhost for wildcard addresses."""
    host = host.strip().removeprefix("[").removesuffix("]")
    return LOCALHOST if host in _WILDCARD_HOSTS else host


def _parse_address(address: object, default_port: int) -> ServerAddress:
    """Parse a `host:port` bind address as used by the proxies and Pumpkin."""
    if not isinstance(address, str):
        return ServerAddress(LOCALHOST, default_port)
    host, _, port = address.rpartition(":")
    if not port.isdigit():
        return ServerAddress(_connect_host(address), default_port)
    return ServerAddress(_connect_host(host), int(port))


def server_address(config: Config) -> ServerAddress:
    """The address the server listens on, read from the platform's config file."""
    runtime = config.runtime_dir
    try:
        if config.platform == PlatformType.VELOCITY:
            data = tomllib.loads((runtime / "velocity.toml").read_text(encoding="utf-8"))
            return _parse_address(data.get("bind"), DEFAULT_PROXY_PORT)
        if config.platform in BUNGEE_PLATFORMS:
            data = YAML(typ="safe").load(runtime / "config.yml") or {}
            listeners = data.get("listeners") or [{}]
            return _parse_address(listeners[0].get("host"), DEFAULT_PROXY_PORT)
        if config.platform == PlatformType.PUMPKIN:
            data = tomllib.loads((runtime / "config" / "configuration.toml").read_text(encoding="utf-8"))
            return _parse_address(data.get("java_edition_address"), DEFAULT_SERVER_PORT)
        props = read_properties(runtime / "server.properties")
        port = props.get("server-port", "")
        return ServerAddress(
            _connect_host(props.get("server-ip", "")),
            int(port) if port.isdigit() else DEFAULT_SERVER_PORT,
            status_enabled=props.get("enable-status", "true").lower() != "false",
        )
    except (OSError, ValueError, AttributeError, IndexError):
        default_port = DEFAULT_PROXY_PORT if config.platform in PROXY_PLATFORMS else DEFAULT_SERVER_PORT
        return ServerAddress(LOCALHOST, default_port)


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint(sock: socket.socket) -> int:
    result = 0
    for shift in range(0, 35, 7):
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("connection closed while reading")
        result |= (byte[0] & 0x7F) << shift
        if not byte[0] & 0x80:
            return result
    raise ValueError("VarInt too long")


def _packet(packet_id: int, payload: bytes = b"") -> bytes:
    body = _varint(packet_id) + payload
    return _varint(len(body)) + body


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("connection closed while reading")
        data.extend(chunk)
    return bytes(data)


def status_ping(host: str, port: int, timeout: float = 5.0) -> dict:
    """Send a status request and return the server's status JSON."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        address = host.encode()
        # Handshake: protocol version -1 (any, as an unsigned VarInt), address, port, next state 1 (status)
        handshake = _varint(0xFFFFFFFF) + _varint(len(address)) + address
        handshake += struct.pack(">H", port) + _varint(1)
        sock.sendall(_packet(0x00, handshake) + _packet(0x00))

        _read_varint(sock)  # packet length
        if _read_varint(sock) != 0x00:
            raise ValueError("unexpected packet in status response")
        payload = _recv_exact(sock, _read_varint(sock))
    return json.loads(payload)


def check_health(config: Config) -> tuple[bool, str]:
    address = server_address(config)
    target = f"{address.host}:{address.port}"

    if not address.status_enabled:
        # Without status pings, the best we can check is that the server accepts connections
        try:
            socket.create_connection((address.host, address.port), timeout=5.0).close()
        except OSError as e:
            return False, f"Connecting to {target} failed: {e}"
        return True, f"OK, {target} accepts connections (enable-status=false, player count unknown)"

    try:
        status = status_ping(address.host, address.port)
    except (OSError, ValueError) as e:
        return False, f"Status ping to {target} failed: {e}"
    players = status.get("players", {})
    return True, f"OK, {players.get('online', '?')}/{players.get('max', '?')} players on {target}"
