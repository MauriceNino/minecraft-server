"""Interactive / one-shot client for the Minecraft Server Management Protocol, run inside the server container.

The commands are generated from the schema the server returns for `rpc.discover`, so every method of the running
server is available, including those of custom namespaces.
"""

from __future__ import annotations

import difflib
import json
import os
import shlex
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.theme import Theme
from websockets.exceptions import InvalidHandshake, InvalidStatus

from msmp.client import MsmpClient, MsmpConnectionClosedError, MsmpError
from msmp.commands import (
    PARAMS_JSON_FLAG,
    Binding,
    Node,
    UsageError,
    build_tree,
    command_path,
    display_path,
    iter_bindings,
    normalize_word,
    parse_args,
    resolve,
)
from msmp.render import notification_text, print_result
from msmp.schema import Schema, parse_schema
from orchestrator.constants import (
    DEFAULT_DATA_DIR,
    DEFAULT_MSMP_PORT,
    MSMP_SECRET_FILENAME,
    PROXY_PLATFORMS,
    RUNTIME_SUBDIR,
)

_THEME = Theme(
    {
        "prompt": "bold cyan",
        "info": "dim cyan",
        "error": "bold red",
        "cmd": "bold",
    }
)
_console = Console(theme=_THEME, highlight=False)
_err_console = Console(theme=_THEME, stderr=True, highlight=False)

# Sent every few seconds when `status-heartbeat-interval` is set, too noisy to show unless asked for
_HEARTBEAT = "server/status"
_BUILTINS = {
    "help": "help [command]  Show the commands, or the usage of one",
    "call": "call <method> [params-json]  Call any method with raw JSON params ('-' reads them from stdin)",
    "watch": "watch [filter...]  Print notifications as they arrive, e.g. `watch players bans/added`",
    "exit": "exit  Leave the interactive session",
}


def _print_error(msg: str) -> None:
    _err_console.print(f"[error]{escape(msg)}[/error]")


def _read_secret() -> str:
    if secret := os.environ.get("MSMP_SECRET"):
        return secret
    # Generated secrets only exist in the orchestrator process, so it leaves a copy on disk
    data_dir = Path(os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIR)))
    try:
        return (data_dir / RUNTIME_SUBDIR / MSMP_SECRET_FILENAME).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass
class Session:
    client: MsmpClient
    schema: Schema
    tree: Node
    as_json: bool = False
    # Notification name prefixes to show, None shows all but the heartbeat
    watch_filters: list[str] | None = None
    print_lock: threading.Lock = field(default_factory=threading.Lock)


# --- Commands ---------------------------------------------------------------------------------------------------


def run(session: Session, words: list[str]) -> bool:
    """Run one command line, return whether it succeeded."""
    if not words:
        return True
    head = words[0].lower()
    if head in ("help", "--help", "-h"):
        _help(session, words[1:])
        return True
    if head == "call":
        return _call_raw(session, words[1:])

    node, path, rest = resolve(session.tree, words)
    if not path:
        _unknown(session, words[0])
        return False
    if "--help" in rest or "-h" in rest:
        _help(session, words[: len(path)])
        return True
    if node.binding is None:
        if rest:
            _unknown(session, " ".join(words[: len(path) + 1]), node)
            return False
        _help(session, path)
        return True

    try:
        params = parse_args(node.binding, rest)
    except UsageError as exc:
        _print_error(str(exc))
        _err_console.print(f"Usage: [cmd]{escape(node.binding.usage())}[/cmd]")
        return False
    return _call(session, node.binding.method.name, params)


def _call(session: Session, method: str, params: Any) -> bool:
    try:
        result = session.client.call(method, params)
    except MsmpError as exc:
        _print_error(f"Error: {exc}")
        if exc.code == -32602:
            hint = f"mc-msmp help {display_path(command_path(method))}" if method in session.schema.methods else ""
            if hint:
                _err_console.print(f"[info]See `{escape(hint)}`[/info]")
        return False
    if session.as_json:
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        with session.print_lock:
            print_result(_console, result)
    return True


def _call_raw(session: Session, words: list[str]) -> bool:
    if not words or len(words) > 2:
        _print_error("Usage: call <method> [params-json]")
        return False
    method = words[0]
    if ":" not in method and not method.startswith("rpc."):
        method = f"minecraft:{method}"
    params: Any = None
    if len(words) == 2:
        raw = sys.stdin.read() if words[1] == "-" else words[1]
        try:
            params = json.loads(raw)
        except json.JSONDecodeError as exc:
            _print_error(f"Invalid JSON params: {exc.msg}")
            return False
    return _call(session, method, params)


def _unknown(session: Session, word: str, node: Node | None = None) -> None:
    base = node or session.tree
    options = [c.name.replace("_", "-") for c in base.children.values()]
    if node is None:
        options += list(_BUILTINS)
    suggestions = difflib.get_close_matches(word.split()[-1].lower(), options, n=3)
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    _print_error(f"Unknown command {word!r}.{hint}")
    _err_console.print("[info]Run `help` to list the commands.[/info]")


def _help(session: Session, words: list[str]) -> None:
    node, path, _ = resolve(session.tree, words) if words else (session.tree, [], [])
    bindings = iter_bindings(node)
    if words and not path:
        _unknown(session, words[0])
        return

    if not path:
        _console.print(f"[info]Management protocol {escape(session.schema.version)}[/info]\n")
    for binding in sorted(bindings, key=lambda b: b.method.name):
        _print_usage(binding, detailed=len(bindings) == 1)

    if not path:
        _console.print("\n[bold]Built-in[/bold]")
        for usage in _BUILTINS.values():
            cmd, _, desc = usage.partition("  ")
            _console.print(f"  [cmd]{escape(cmd)}[/cmd]  [dim]{escape(desc)}[/dim]")
        _console.print(
            "\n[dim]Players are names or UUIDs. Lists take several words or comma-separated flag values. "
            f"Any command takes --{PARAMS_JSON_FLAG} '<json>' to pass the raw params. "
            "Add --json before the command for JSON output.[/dim]"
        )


def _print_usage(binding: Binding, *, detailed: bool) -> None:
    desc = binding.method.description
    _console.print(f"  [cmd]{escape(binding.usage())}[/cmd]")
    if desc:
        _console.print(f"      [dim]{escape(desc)}[/dim]")
    if detailed:
        for param in binding.method.params:
            _console.print(f"    [dim]param {escape(param.name)}: {escape(json.dumps(param.schema))}[/dim]")


# --- Notifications ----------------------------------------------------------------------------------------------


def _notification_name(method: str) -> str:
    return method.split("notification/", 1)[-1] if "notification/" in method else method


def _matches(session: Session, method: str) -> bool:
    name = normalize_word(_notification_name(method))
    if session.watch_filters is None:
        return name != _HEARTBEAT
    return any(name.startswith(f) for f in session.watch_filters)


def _watch(session: Session, filters: list[str]) -> None:
    """Block and print notifications until Ctrl-C or the server closes the connection."""
    session.watch_filters = [normalize_word(f).strip("/") for f in filters] or None

    def show(method: str, params: Any) -> None:
        if _matches(session, method):
            _console.print(notification_text(method, params))

    session.client.set_notification_handler(show)
    label = ", ".join(filters) if filters else "all notifications"
    _console.print(f"[info]Watching {escape(label)}  —  Ctrl-C to stop[/info]")
    try:
        while not session.client.closed.wait(0.5):
            pass
        _print_error("The server closed the connection")
    except KeyboardInterrupt:
        pass


# --- Interactive ------------------------------------------------------------------------------------------------


def _interactive(session: Session, address: str) -> None:
    try:
        import readline  # Not available on every platform, only line editing needs it
    except ImportError:
        readline = None

    tty = sys.stdin.isatty()
    prompt = "\001\x1b[1;36m\002msmp> \001\x1b[0m\002" if tty else ""

    def show_notification(method: str, params: Any) -> None:
        if not _matches(session, method):
            return
        with session.print_lock:
            # Print above the line being typed, then draw it again
            sys.stdout.write("\r\x1b[K")
            sys.stdout.flush()
            _console.print(notification_text(method, params))
            if readline is not None and tty:
                sys.stdout.write("\x1b[1;36mmsmp> \x1b[0m" + readline.get_line_buffer())
                sys.stdout.flush()

    session.client.set_notification_handler(show_notification)
    if readline is not None:
        readline.set_completer(_completer(session, readline))
        readline.set_completer_delims(" ")
        readline.parse_and_bind("tab: complete")

    _console.print(
        f"[info]Connected to {escape(address)} (protocol {escape(session.schema.version)})  —  "
        "type 'help' for the commands, 'exit' or Ctrl-D to quit[/info]\n"
    )
    while True:
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            _console.print("\n[info]Bye![/info]")
            return
        if session.client.closed.is_set():
            _print_error("The server closed the connection")
            return
        if not line:
            continue
        if line.lower() in ("exit", "quit", "q"):
            _console.print("[info]Bye![/info]")
            return
        try:
            words = shlex.split(line)
        except ValueError as exc:
            _print_error(f"Invalid input: {exc}")
            continue
        if words[0].lower() == "watch":
            _set_watch(session, words[1:])
            continue
        try:
            run(session, words)
        except MsmpConnectionClosedError as exc:
            _print_error(str(exc))
            return


def _set_watch(session: Session, filters: list[str]) -> None:
    if filters == ["off"]:
        session.watch_filters = []
        _console.print("[info]Notifications are hidden[/info]")
    elif filters in ([], ["all"]):
        session.watch_filters = None if not filters else [""]
        _console.print("[info]Showing all notifications[/info]")
    else:
        session.watch_filters = [normalize_word(f).strip("/") for f in filters]
        _console.print(f"[info]Showing {escape(', '.join(filters))}[/info]")


def _completer(session: Session, readline: Any) -> Any:
    matches: list[str] = []

    def complete(text: str, state: int) -> str | None:
        nonlocal matches
        if state == 0:
            before = readline.get_line_buffer()[: readline.get_begidx()]
            words = before.split()
            node, path, rest = resolve(session.tree, words)
            if rest or (words and not path):
                matches = []
            elif text.startswith("-") and node.binding is not None:
                matches = [f"--{f}" for f in node.binding.flags if f"--{f}".startswith(text)]
            else:
                options = [c.name.replace("_", "-") for c in node.children.values()]
                if not path:
                    options += [b for b in _BUILTINS if b != "exit"]
                if node.binding is not None:
                    options += [f"--{f}" for f in node.binding.flags]
                matches = sorted(f"{o} " for o in options if o.startswith(text))
        return matches[state] if state < len(matches) else None

    return complete


# --- Entry point ------------------------------------------------------------------------------------------------


def main() -> None:
    args = sys.argv[1:]
    as_json = False
    while args and args[0] in ("--json", "-j"):
        as_json = True
        args = args[1:]

    platform = os.environ.get("TYPE", "").strip().upper()
    if platform in {p.value for p in PROXY_PLATFORMS}:
        _print_error("Proxies don't support the Minecraft Server Management Protocol, use mc-rcon instead.")
        sys.exit(1)

    host = os.environ.get("MSMP_HOST", "127.0.0.1")
    port = int(os.environ.get("MSMP_PORT", str(DEFAULT_MSMP_PORT)))
    scheme = "wss" if os.environ.get("MSMP_TLS", "false").strip().lower() in ("1", "true", "yes", "on") else "ws"
    secret = _read_secret()
    if not secret:
        _print_error(
            "No management secret found.\n"
            "Set MSMP_SECRET, or run mc-msmp inside the server container after the server has started."
        )
        sys.exit(1)

    address = f"{host}:{port}"
    try:
        with MsmpClient(f"{scheme}://{address}", secret) as client:
            schema = parse_schema(client.call("rpc.discover"))
            session = Session(client, schema, build_tree(schema), as_json=as_json)
            if not args:
                _interactive(session, address)
                return
            if args[0].lower() == "watch":
                _watch(session, args[1:])
                return
            ok = run(session, args)
    except InvalidStatus as exc:
        status = exc.response.status_code
        if status == 401:
            _print_error(f"The server rejected the management secret ({address}). Check MSMP_SECRET.")
        else:
            _print_error(f"The server refused the connection with HTTP {status} ({address}).")
        sys.exit(1)
    except (ConnectionRefusedError, TimeoutError):
        _print_error(
            f"Connection refused ({address}).\n"
            "Is the server running and the management protocol enabled?\n"
            "  • It needs Minecraft 1.21.9 or newer and MSMP_ENABLED=true (the default)\n"
            "  • Proxies don't support it, use mc-rcon instead"
        )
        sys.exit(1)
    except (MsmpError, MsmpConnectionClosedError, InvalidHandshake, OSError) as exc:
        _print_error(f"Management protocol error: {exc}")
        sys.exit(1)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
