"""The OpenRPC schema a server returns for `rpc.discover`, with `$ref`s resolved."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Notifications are listed as methods in this namespace path, e.g. `minecraft:notification/players/joined`
_NOTIFICATION_RE = re.compile(r"^[^:]+:notification/")
# Marks the component a resolved `$ref` pointed at, e.g. "player"
REF_KEY = "x-ref"

type JsonSchema = dict[str, Any]


@dataclass(frozen=True)
class Param:
    name: str
    schema: JsonSchema
    required: bool


@dataclass(frozen=True)
class Method:
    name: str
    description: str
    params: tuple[Param, ...]
    result: JsonSchema | None

    @property
    def is_notification(self) -> bool:
        return bool(_NOTIFICATION_RE.match(self.name))


@dataclass(frozen=True)
class Schema:
    version: str
    methods: dict[str, Method]

    @property
    def commands(self) -> list[Method]:
        return [m for m in self.methods.values() if not m.is_notification]

    @property
    def notifications(self) -> list[Method]:
        return [m for m in self.methods.values() if m.is_notification]


def parse_schema(discover: dict[str, Any]) -> Schema:
    """Parse the result of `rpc.discover`."""
    components: dict[str, JsonSchema] = discover.get("components", {}).get("schemas", {})

    def resolve(schema: Any, depth: int = 0) -> Any:
        if depth > 32:  # A recursive schema, keep the rest unresolved
            return schema
        if isinstance(schema, list):
            return [resolve(s, depth + 1) for s in schema]
        if not isinstance(schema, dict):
            return schema
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[1]
            target = components.get(name, {})
            return {**resolve(target, depth + 1), REF_KEY: name}
        return {k: resolve(v, depth + 1) for k, v in schema.items()}

    methods: dict[str, Method] = {}
    for raw in discover.get("methods", []):
        name = raw.get("name")
        if not isinstance(name, str):
            continue
        params = tuple(
            Param(p["name"], resolve(p.get("schema", {})), bool(p.get("required", False)))
            for p in raw.get("params", [])
            if isinstance(p, dict) and "name" in p
        )
        result = raw.get("result")
        methods[name] = Method(
            name=name,
            description=raw.get("description") or raw.get("summary") or "",
            params=params,
            result=resolve(result.get("schema", {})) if isinstance(result, dict) else None,
        )
    return Schema(version=str(discover.get("info", {}).get("version", "?")), methods=methods)


def types_of(schema: JsonSchema) -> list[str]:
    t = schema.get("type")
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return [t] if isinstance(t, str) else []


def is_player(schema: JsonSchema) -> bool:
    """A player is referenced by name or UUID: `{"name": ..., "id": ...}`."""
    props = schema.get("properties")
    return isinstance(props, dict) and "name" in props and set(props) <= {"name", "id"}


def is_message(schema: JsonSchema) -> bool:
    """A chat message: `{"literal": ...}` or a translation key with parameters."""
    props = schema.get("properties")
    return isinstance(props, dict) and "literal" in props


def is_scalar(schema: JsonSchema) -> bool:
    types = types_of(schema)
    return bool(types) and all(t in ("string", "integer", "number", "boolean") for t in types)


def is_simple(schema: JsonSchema) -> bool:
    """Fits into a single command-line word."""
    return is_scalar(schema) or is_player(schema) or is_message(schema)


def array_items(schema: JsonSchema) -> JsonSchema | None:
    if types_of(schema) == ["array"] and isinstance(schema.get("items"), dict):
        return schema["items"]
    return None
