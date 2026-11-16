"""Turn the methods of a schema into commands, and command-line words into JSON-RPC params.

`minecraft:bans/add` becomes `bans add`. Its `add: Array<user_ban>` param becomes a list of players, and the other
fields of a ban (`reason`, `expires`, `source`) become `--flags` that apply to each of them:

    bans add Notch jeb_ --reason "Griefing"  ->  {"add": [{"player": {"name": "Notch"}, "reason": "Griefing"}, ...]}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from msmp.schema import JsonSchema, Method, Schema, array_items, is_message, is_player, is_simple, types_of

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}
# Fields of an object param that are given as positional words, the rest become flags
_IDENTITY_FIELDS = ("ip", "player", "key")
# Replaces all params of any command with raw JSON
PARAMS_JSON_FLAG = "params-json"


class UsageError(Exception):
    pass


def command_path(method_name: str) -> tuple[str, ...]:
    """`minecraft:serversettings/motd/set` -> (serversettings, motd, set). Other namespaces keep their prefix."""
    namespace, _, path = method_name.partition(":")
    if not path:
        return tuple(method_name.split("/"))
    parts = path.split("/")
    if namespace != "minecraft":
        parts[0] = f"{namespace}:{parts[0]}"
    return tuple(parts)


def normalize_word(word: str) -> str:
    return word.lower().replace("-", "_")


def cli_name(name: str) -> str:
    """`permissionLevel` / `percentage_points` -> `permission-level` / `percentage-points`."""
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", name).replace("_", "-").lower()


def display_path(path: tuple[str, ...]) -> str:
    return " ".join(p.replace("_", "-") for p in path)


# --- Values -----------------------------------------------------------------------------------------------------


def parse_bool(word: str) -> bool:
    lowered = word.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise UsageError(f"Expected true or false, got {word!r}")


def coerce(word: str, schema: JsonSchema) -> Any:
    """Convert one command-line word to a value of the given schema."""
    if is_player(schema):
        if _UUID_RE.match(word):
            return {"id": word}
        return {"name": word}
    if is_message(schema):
        if word.startswith("{"):
            return _json(word)
        return {"literal": word}

    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        for option in enum:
            if str(option).lower() == word.lower():
                return option
        raise UsageError(f"Invalid value {word!r}, expected one of: {', '.join(map(str, enum))}")

    types = types_of(schema)
    for t in types:
        try:
            if t == "boolean":
                return parse_bool(word)
            if t == "integer":
                return int(word)
            if t == "number":
                return float(word)
        except (UsageError, ValueError):
            continue
        if t == "string":
            return word
    if types and all(t in ("boolean", "integer", "number") for t in types):
        raise UsageError(f"Invalid value {word!r}, expected {' or '.join(types)}")
    if "string" in types:
        return word
    return _json(word)


def _json(word: str) -> Any:
    try:
        return json.loads(word)
    except json.JSONDecodeError as exc:
        raise UsageError(f"Invalid JSON {word!r}: {exc.msg}") from None


def type_label(schema: JsonSchema) -> str:
    if is_player(schema):
        return "player"
    if is_message(schema):
        return "text"
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return "|".join(map(str, enum))
    if items := array_items(schema):
        return f"{type_label(items)},..."
    types = types_of(schema)
    if types and all(t in ("string", "integer", "number", "boolean") for t in types):
        return "|".join("bool" if t == "boolean" else "text" if t == "string" else t for t in types)
    return "json"


# --- Binding ----------------------------------------------------------------------------------------------------


@dataclass
class Positional:
    label: str
    schema: JsonSchema
    variadic: bool
    # Where the value goes: (param,) or (param, field)
    target: tuple[str, ...]


@dataclass
class Flag:
    name: str
    schema: JsonSchema
    target: tuple[str, ...]
    is_list: bool = False
    # Needs raw JSON, as the value has no command-line form
    raw_json: bool = False

    @property
    def is_bool(self) -> bool:
        return types_of(self.schema) == ["boolean"]

    @property
    def default(self) -> bool:
        """The value of a switch that isn't given: the schema's default, else off."""
        default = self.schema.get("default")
        return default if isinstance(default, bool) else False


@dataclass
class Binding:
    """How the words of a command map to the params of its method."""

    method: Method
    positionals: list[Positional] = field(default_factory=list)
    flags: dict[str, Flag] = field(default_factory=dict)
    # Params that are an array of objects: one object per positional word, with the flags applied to each
    object_lists: set[str] = field(default_factory=set)

    @property
    def fully_mapped(self) -> bool:
        """Every param can be given without falling back to raw JSON."""
        return not any(f.raw_json for f in self.flags.values())

    def usage(self) -> str:
        parts = [display_path(command_path(self.method.name))]
        for p in self.positionals:
            parts.append(f"<{p.label}>..." if p.variadic else f"<{p.label}>")
        for f in self.flags.values():
            if f.is_bool:
                parts.append(f"[--no-{f.name}]" if f.default else f"[--{f.name}]")
            else:
                parts.append(f"[--{f.name} {type_label(f.schema)}]")
        return " ".join(parts)

    def add_positional(self, label: str, schema: JsonSchema, target: tuple[str, ...], *, variadic: bool) -> None:
        # Only the last positional can take several words, later ones become flags
        if self.positionals and self.positionals[-1].variadic:
            self.add_flag(target[-1], schema, target)
        else:
            self.positionals.append(Positional(label, schema, variadic, target))

    def add_flag(self, name: str, schema: JsonSchema, target: tuple[str, ...]) -> None:
        items = array_items(schema)
        is_list = items is not None and is_simple(items)
        flag = Flag(cli_name(name), schema, target, is_list=is_list, raw_json=not is_simple(schema) and not is_list)
        self.flags.setdefault(flag.name, flag)


def bind(method: Method) -> Binding:
    binding = Binding(method)
    is_setter = method.name.endswith("/set")

    for param in method.params:
        schema = param.schema
        target = (param.name,)
        items = array_items(schema)

        if is_simple(schema):
            # A switch reads better than a required true/false word, e.g. `server save --flush`
            if types_of(schema) == ["boolean"] and not is_setter:
                binding.add_flag(param.name, schema, target)
            else:
                label = "player" if is_player(schema) else param.name
                binding.add_positional(label, schema, target, variadic=False)
        elif items is not None and is_simple(items):
            label = "player" if is_player(items) else param.name
            binding.add_positional(label, items, target, variadic=True)
        elif _object_fields(schema) is not None:
            _bind_object(binding, param.name, schema, many=False)
        elif items is not None and _object_fields(items) is not None:
            binding.object_lists.add(param.name)
            _bind_object(binding, param.name, items, many=True)
        else:
            binding.add_flag(param.name, schema, target)
    return binding


def _object_fields(schema: JsonSchema) -> dict[str, JsonSchema] | None:
    props = schema.get("properties")
    if types_of(schema) in (["object"], []) and isinstance(props, dict) and props:
        return props
    return None


def _bind_object(binding: Binding, param: str, schema: JsonSchema, *, many: bool) -> None:
    fields = _object_fields(schema) or {}
    primary: list[str] = []
    if identity := next((f for f in _IDENTITY_FIELDS if f in fields and is_simple(fields[f])), None):
        primary.append(identity)
        # A game rule: `gamerules update <key> <value>`
        if identity == "key" and "value" in fields:
            primary.append("value")
    if "message" in fields and is_simple(fields["message"]):
        primary.append("message")
    if many:
        # Only one word per object: the rest are the same for all of them
        primary = primary[:1]

    for name in primary:
        binding.add_positional(name, fields[name], (param, name), variadic=many)
    for name, field_schema in fields.items():
        if name not in primary:
            binding.add_flag(name, field_schema, (param, name))


# --- Parsing ----------------------------------------------------------------------------------------------------


def parse_args(binding: Binding, words: list[str]) -> Any:
    """Build the params object of a call from the words after the command path, None for none."""
    positional_words: list[str] = []
    flag_values: dict[str, Any] = {}
    raw_params: Any = None

    i = 0
    only_positionals = False
    while i < len(words):
        word = words[i]
        i += 1
        if only_positionals or not word.startswith("--") or word == "--":
            if word == "--" and not only_positionals:
                only_positionals = True
                continue
            positional_words.append(word)
            continue

        name, has_value, value = word[2:].partition("=")
        name = cli_name(name)
        if name == PARAMS_JSON_FLAG:
            if not has_value:
                value, i = _next_value(words, i, name)
            raw_params = _json(value)
            continue

        negated = False
        flag = binding.flags.get(name)
        if flag is None and name.startswith("no-") and (f := binding.flags.get(name[3:])) and f.is_bool:
            flag, negated = f, True
        if flag is None:
            raise UsageError(f"Unknown option --{name}")

        if flag.is_bool and not has_value:
            if i < len(words) and words[i].lower() in _TRUE | _FALSE:
                value, i = words[i], i + 1
            else:
                value = "true"
        elif not has_value:
            value, i = _next_value(words, i, name)

        if flag.raw_json:
            parsed = _json(value)
        elif flag.is_list:
            items = array_items(flag.schema) or {}
            parsed = flag_values.get(flag.name, []) + [coerce(v.strip(), items) for v in value.split(",") if v.strip()]
        else:
            parsed = coerce(value, flag.schema)
        flag_values[flag.name] = (not parsed) if negated else parsed

    if raw_params is not None:
        if positional_words or flag_values:
            raise UsageError(f"--{PARAMS_JSON_FLAG} replaces all other arguments")
        return raw_params

    params = _assemble(binding, positional_words, flag_values)
    # Servers reject an empty params object for methods without params
    return params or None


def _next_value(words: list[str], i: int, name: str) -> tuple[str, int]:
    if i >= len(words):
        raise UsageError(f"Option --{name} needs a value")
    return words[i], i + 1


def _assemble(binding: Binding, positional_words: list[str], flag_values: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    # Fields that every object of an object list gets
    shared: dict[str, dict[str, Any]] = {}

    def put(target: tuple[str, ...], value: Any) -> None:
        if len(target) == 1:
            params[target[0]] = value
        elif target[0] in binding.object_lists:
            shared.setdefault(target[0], {})[target[1]] = value
        else:
            params.setdefault(target[0], {})[target[1]] = value

    words = list(positional_words)
    for positional in binding.positionals:
        if positional.variadic:
            if not words:
                raise UsageError(f"Missing <{positional.label}>")
            values = [coerce(w, positional.schema) for w in words]
            words = []
            if positional.target[0] in binding.object_lists:
                params[positional.target[0]] = [{positional.target[1]: v} for v in values]
            else:
                put(positional.target, values)
        else:
            if not words:
                raise UsageError(f"Missing <{positional.label}>")
            put(positional.target, coerce(words.pop(0), positional.schema))
    if words:
        raise UsageError(f"Unexpected argument {words[0]!r}")

    for flag in binding.flags.values():
        if flag.name in flag_values:
            put(flag.target, flag_values[flag.name])
        # Servers require switches that aren't given, e.g. the `overlay` of a message, so they get the schema's
        # default, or off. Optional top-level params are left out instead.
        elif flag.is_bool:
            top_level, *nested = flag.target
            if nested or any(p.name == top_level and p.required for p in binding.method.params):
                put(flag.target, flag.default)

    for param, fields in shared.items():
        objects = params.setdefault(param, [{}])
        for obj in objects:
            obj.update(fields)
    return params


# --- Command tree -----------------------------------------------------------------------------------------------


@dataclass
class Node:
    name: str
    binding: Binding | None = None
    children: dict[str, Node] = field(default_factory=dict)


def build_tree(schema: Schema) -> Node:
    root = Node("")
    for method in schema.commands:
        node = root
        for part in command_path(method.name):
            node = node.children.setdefault(normalize_word(part), Node(part))
        node.binding = bind(method)
    return root


def resolve(root: Node, words: list[str]) -> tuple[Node, list[str], list[str]]:
    """Walk the command path as far as it matches: (node, consumed path, remaining words)."""
    node = root
    consumed: list[str] = []
    for word in words:
        child = node.children.get(normalize_word(word))
        if child is None:
            break
        node = child
        consumed.append(child.name)
    return node, consumed, words[len(consumed) :]


def iter_bindings(node: Node) -> list[Binding]:
    found = [node.binding] if node.binding else []
    for child in node.children.values():
        found.extend(iter_bindings(child))
    return found
