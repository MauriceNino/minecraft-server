"""Tests for the `mc-msmp` client: commands generated from the schema, params, the client and the injection."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from websockets.sync.server import ServerConnection, serve

from msmp.client import MsmpClient, MsmpError
from msmp.commands import UsageError, bind, build_tree, command_path, parse_args, resolve
from msmp.schema import Schema, parse_schema
from orchestrator.cli import load_config
from orchestrator.constants import PlatformType
from orchestrator.remote_access import inject_msmp

FIXTURE = Path(__file__).parent / "fixtures" / "msmp_schema_3.1.0.json"


@pytest.fixture(scope="module")
def schema() -> Schema:
    return parse_schema(json.loads(FIXTURE.read_text()))


def params_for(schema: Schema, line: str) -> Any:
    words = line.split()
    node, _, rest = resolve(build_tree(schema), words)
    assert node.binding is not None, line
    return parse_args(node.binding, rest)


class TestSchema:
    def test_splits_notifications(self, schema: Schema) -> None:
        assert len(schema.commands) == 68
        assert len(schema.notifications) == 21
        assert schema.version == "3.1.0"

    def test_resolves_refs(self, schema: Schema) -> None:
        item = schema.methods["minecraft:allowlist/add"].params[0].schema["items"]
        assert item["x-ref"] == "player"
        assert set(item["properties"]) == {"name", "id"}

    def test_coverage(self, schema: Schema) -> None:
        """At least 95% of the methods can be called without raw JSON."""
        bindings = [bind(m) for m in schema.commands]
        mapped = [b for b in bindings if b.fully_mapped]
        assert len(mapped) / len(bindings) >= 0.95, [b.method.name for b in bindings if not b.fully_mapped]


class TestCommands:
    def test_command_path(self) -> None:
        assert command_path("minecraft:serversettings/motd/set") == ("serversettings", "motd", "set")
        assert command_path("minecraft:allowlist") == ("allowlist",)
        assert command_path("mymod:homes/list") == ("mymod:homes", "list")

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("allowlist", None),
            ("server status", None),
            ("allowlist add jeb_ Notch", {"add": [{"name": "jeb_"}, {"name": "Notch"}]}),
            (
                "allowlist add 853c80ef-3c37-49fd-aa49-938b674adae6",
                {"add": [{"id": "853c80ef-3c37-49fd-aa49-938b674adae6"}]},
            ),
            (
                "bans add Notch jeb_ --reason Griefing --expires 2030-01-01T00:00:00Z",
                {
                    "add": [
                        {"player": {"name": "Notch"}, "reason": "Griefing", "expires": "2030-01-01T00:00:00Z"},
                        {"player": {"name": "jeb_"}, "reason": "Griefing", "expires": "2030-01-01T00:00:00Z"},
                    ]
                },
            ),
            (
                "operators add jeb_ --permission-level 3 --bypasses-player-limit",
                {"add": [{"player": {"name": "jeb_"}, "permissionLevel": 3, "bypassesPlayerLimit": True}]},
            ),
            ("ip-bans add 1.2.3.4 --player Notch", {"add": [{"ip": "1.2.3.4", "player": {"name": "Notch"}}]}),
            ("ip-bans remove 1.2.3.4 5.6.7.8", {"ip": ["1.2.3.4", "5.6.7.8"]}),
            (
                "players kick jeb_ --message AFK",
                {"kick": [{"player": {"name": "jeb_"}, "message": {"literal": "AFK"}}]},
            ),
            ("server system-message Hi", {"message": {"message": {"literal": "Hi"}, "overlay": False}}),
            ("operators add jeb_", {"add": [{"player": {"name": "jeb_"}, "bypassesPlayerLimit": False}]}),
            ("server save", {"flush": False}),
            ("server save --flush", {"flush": True}),
            (
                "server system-message Hi --receiving-players jeb_,Notch --overlay",
                {
                    "message": {
                        "message": {"literal": "Hi"},
                        "receivingPlayers": [{"name": "jeb_"}, {"name": "Notch"}],
                        "overlay": True,
                    }
                },
            ),
            ("serversettings difficulty set HARD", {"difficulty": "hard"}),
            ("serversettings autosave set off", {"enable": False}),
            ("serversettings max-players set 30", {"max": 30}),
            ("gamerules update keep_inventory true", {"gamerule": {"key": "keep_inventory", "value": True}}),
            ("gamerules update random_tick_speed 5", {"gamerule": {"key": "random_tick_speed", "value": 5}}),
            ('serversettings motd set --params-json {"message":"x"}', {"message": "x"}),
        ],
    )
    def test_params(self, schema: Schema, line: str, expected: Any) -> None:
        assert params_for(schema, line) == expected

    @pytest.mark.parametrize(
        ("line", "error"),
        [
            ("allowlist add", "Missing <player>"),
            ("serversettings max-players set abc", "expected integer"),
            ("serversettings difficulty set extreme", "expected one of"),
            ("bans add Notch --nope x", "Unknown option --nope"),
            ("serversettings motd set a b", "Unexpected argument"),
        ],
    )
    def test_usage_errors(self, schema: Schema, line: str, error: str) -> None:
        with pytest.raises(UsageError, match=error):
            params_for(schema, line)

    def test_words_are_case_and_dash_insensitive(self, schema: Schema) -> None:
        node, path, rest = resolve(build_tree(schema), ["ServerSettings", "max_players", "set", "5"])
        assert node.binding is not None
        assert node.binding.method.name == "minecraft:serversettings/max_players/set"
        assert path == ["serversettings", "max_players", "set"]
        assert rest == ["5"]

    def test_switches_use_the_schema_default(self) -> None:
        options = {
            "type": "object",
            "properties": {
                "player": {"type": "object", "properties": {"name": {"type": "string"}}},
                "notify": {"type": "boolean", "default": True},
                "silent": {"type": "boolean"},
            },
        }
        schema = parse_schema(
            {"methods": [{"name": "mymod:warn", "params": [{"name": "o", "schema": options, "required": True}]}]}
        )
        node, _, _ = resolve(build_tree(schema), ["mymod:warn"])
        assert node.binding is not None
        assert node.binding.usage() == "mymod:warn <player> [--no-notify] [--silent]"
        assert parse_args(node.binding, ["jeb_"]) == {
            "o": {"player": {"name": "jeb_"}, "notify": True, "silent": False}
        }
        assert parse_args(node.binding, ["jeb_", "--no-notify"])["o"]["notify"] is False

    def test_custom_namespace_and_unknown_shapes(self) -> None:
        schema = parse_schema(
            {
                "methods": [
                    {
                        "name": "mymod:homes/set",
                        "params": [
                            {"name": "player", "schema": {"$ref": "#/components/schemas/player"}, "required": True},
                            {"name": "pos", "schema": {"type": "object", "properties": {"x": {"type": "object"}}}},
                        ],
                    }
                ],
                "components": {"schemas": {"player": {"type": "object", "properties": {"name": {"type": "string"}}}}},
            }
        )
        node, _, rest = resolve(build_tree(schema), ["mymod:homes", "set", "jeb_", "--x", '{"a": 1}'])
        assert node.binding is not None
        assert not node.binding.fully_mapped
        assert parse_args(node.binding, rest) == {"player": {"name": "jeb_"}, "pos": {"x": {"a": 1}}}


class FakeServer:
    """A management server that answers from a dict and sends a notification after each call."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []
        self.authorization: str | None = None

    def handler(self, ws: ServerConnection) -> None:
        assert ws.request is not None
        self.authorization = ws.request.headers.get("Authorization")
        for raw in ws:
            request = json.loads(raw)
            self.requests.append(request)
            ws.send(json.dumps({"jsonrpc": "2.0", "method": "minecraft:notification/server/saved"}))
            response = self.responses.get(request["method"])
            if response is None:
                body = {"error": {"code": -32601, "message": "Method not found", "data": request["method"]}}
            elif isinstance(response, dict) and "error" in response:
                # The nested error shape some servers send
                body = {"result": {"jsonrpc": "2.0", "id": request["id"], **response}}
            else:
                body = {"result": response}
            ws.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], **body}))


@pytest.fixture
def fake_server() -> Iterator[tuple[FakeServer, str]]:
    fake = FakeServer(
        {
            "minecraft:players": [{"name": "jeb_", "id": "853c80ef-3c37-49fd-aa49-938b674adae6"}],
            "minecraft:nested": {"error": {"code": -32603, "message": "Not ready"}},
        }
    )
    with serve(fake.handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield fake, f"ws://127.0.0.1:{server.socket.getsockname()[1]}"
        server.shutdown()


class TestClient:
    def test_call_and_notifications(self, fake_server: tuple[FakeServer, str]) -> None:
        fake, url = fake_server
        notifications: list[str] = []
        with MsmpClient(url, "s" * 40, on_notification=lambda m, _: notifications.append(m)) as client:
            assert client.call("minecraft:players") == [{"name": "jeb_", "id": "853c80ef-3c37-49fd-aa49-938b674adae6"}]
        assert fake.authorization == f"Bearer {'s' * 40}"
        assert fake.requests == [{"jsonrpc": "2.0", "id": 1, "method": "minecraft:players"}]
        assert notifications == ["minecraft:notification/server/saved"]

    def test_errors(self, fake_server: tuple[FakeServer, str]) -> None:
        _, url = fake_server
        with MsmpClient(url, "secret") as client:
            with pytest.raises(MsmpError, match="Method not found") as exc:
                client.call("minecraft:foo", {"a": 1})
            assert exc.value.code == -32601
            with pytest.raises(MsmpError, match="Not ready"):
                client.call("minecraft:nested")


class TestInjectMsmp:
    SECRET = "A" * 40

    def test_server_properties(self, tmp_path: Path) -> None:
        (tmp_path / "server.properties").write_text("motd=Hello\nmanagement-server-tls-enabled=true\n")
        inject_msmp(PlatformType.PAPER, tmp_path, 25585, self.SECRET)

        props = (tmp_path / "server.properties").read_text().splitlines()
        assert "motd=Hello" in props
        assert "management-server-enabled=true" in props
        assert "management-server-port=25585" in props
        assert f"management-server-secret={self.SECRET}" in props
        assert "management-server-tls-enabled=false" in props
        assert (tmp_path / ".msmp-secret").read_text() == self.SECRET
        assert (tmp_path / ".msmp-secret").stat().st_mode & 0o777 == 0o600

    def test_pumpkin(self, tmp_path: Path) -> None:
        (tmp_path / "pumpkin.toml").write_text('[networking.management]\nenabled = false\nsecret = "1234"\n')
        inject_msmp(PlatformType.PUMPKIN, tmp_path, 25590, self.SECRET)

        content = (tmp_path / "pumpkin.toml").read_text()
        assert "enabled = true" in content
        assert 'address = "0.0.0.0:25590"' in content
        assert f'secret = "{self.SECRET}"' in content
        assert not (tmp_path / "server.properties").exists()

    def test_disable_server_properties(self, tmp_path: Path) -> None:
        inject_msmp(PlatformType.PAPER, tmp_path, 25585, self.SECRET)
        inject_msmp(PlatformType.PAPER, tmp_path, 25585, self.SECRET, enabled=False)

        props = (tmp_path / "server.properties").read_text().splitlines()
        assert "management-server-enabled=false" in props
        assert not (tmp_path / ".msmp-secret").exists()

    def test_disable_pumpkin(self, tmp_path: Path) -> None:
        (tmp_path / "pumpkin.toml").write_text('[networking.management]\nenabled = true\nsecret = "1234"\n')
        inject_msmp(PlatformType.PUMPKIN, tmp_path, 25585, self.SECRET, enabled=False)

        assert "enabled = false" in (tmp_path / "pumpkin.toml").read_text()

    def test_proxies_are_skipped(self, tmp_path: Path) -> None:
        inject_msmp(PlatformType.VELOCITY, tmp_path, 25585, self.SECRET)
        assert list(tmp_path.iterdir()) == []


class TestMsmpConfig:
    def test_defaults(self) -> None:
        config = load_config(environ={})
        assert config.msmp_enabled is True
        assert config.msmp_port == 25585
        assert len(config.msmp_secret) == 40
        assert config.msmp_secret.isalnum()

    def test_explicit(self) -> None:
        config = load_config(environ={"MSMP_ENABLED": "false", "MSMP_PORT": "1234", "MSMP_SECRET": "b" * 40})
        assert (config.msmp_enabled, config.msmp_port, config.msmp_secret) == (False, 1234, "b" * 40)

    @pytest.mark.parametrize("secret", ["short", "x" * 39 + "!"])
    def test_invalid_secret(self, secret: str) -> None:
        with pytest.raises(SystemExit, match="Invalid MSMP_SECRET"):
            load_config(environ={"MSMP_SECRET": secret})

    def test_invalid_port(self) -> None:
        with pytest.raises(SystemExit, match="Invalid MSMP_PORT"):
            load_config(environ={"MSMP_PORT": "0"})
