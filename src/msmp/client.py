"""A JSON-RPC 2.0 client over WebSocket for the Minecraft Server Management Protocol."""

from __future__ import annotations

import contextlib
import itertools
import json
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, Self

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

type NotificationHandler = Callable[[str, Any], None]


class MsmpError(Exception):
    """An error response of the server."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        detail = f": {data}" if data not in (None, "", message) else ""
        super().__init__(f"{message}{detail} (code {code})")


class MsmpConnectionClosedError(Exception):
    pass


class MsmpClient:
    """Sends calls and passes the notifications the server pushes to *on_notification*, from a reader thread."""

    def __init__(
        self,
        url: str,
        secret: str,
        on_notification: NotificationHandler | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._url = url
        self._secret = secret
        self._on_notification = on_notification
        self._timeout = timeout
        self._ids = itertools.count(1)
        self._pending: dict[int, Future[Any]] = {}
        self._lock = threading.Lock()
        self._ws: ClientConnection | None = None
        self._stack = contextlib.ExitStack()
        self._reader: threading.Thread | None = None
        self.closed = threading.Event()

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def connect(self) -> None:
        # No Origin header: the server only checks it for browsers
        self._ws = self._stack.enter_context(
            connect(
                self._url,
                additional_headers={"Authorization": f"Bearer {self._secret}"},
                open_timeout=self._timeout,
                max_size=None,
            )
        )
        self._reader = threading.Thread(target=self._read_loop, name="msmp-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        self._stack.close()
        if self._reader is not None:
            self._reader.join(timeout=2)

    def set_notification_handler(self, handler: NotificationHandler | None) -> None:
        self._on_notification = handler

    def call(self, method: str, params: Any = None) -> Any:
        if self._ws is None:
            raise RuntimeError("Not connected")
        request_id = next(self._ids)
        future: Future[Any] = Future()
        with self._lock:
            if self.closed.is_set():
                raise MsmpConnectionClosedError("The server closed the connection")
            self._pending[request_id] = future

        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            self._ws.send(json.dumps(message))
            return future.result(timeout=self._timeout)
        except ConnectionClosed:
            raise MsmpConnectionClosedError("The server closed the connection") from None
        except TimeoutError:
            raise MsmpError(-1, f"No response within {self._timeout:g}s") from None
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            for raw in self._ws:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    self._dispatch(message)
        except ConnectionClosed:
            pass
        finally:
            with self._lock:
                self.closed.set()
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(MsmpConnectionClosedError("The server closed the connection"))

    def _dispatch(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id is None:
            method = message.get("method")
            if isinstance(method, str) and self._on_notification is not None:
                self._on_notification(method, message.get("params"))
            return

        with self._lock:
            future = self._pending.get(request_id) if isinstance(request_id, int) else None
        if future is None or future.done():
            return

        result = message.get("result")
        error = message.get("error")
        # Some servers nest an error response in `result`
        if error is None and isinstance(result, dict) and "error" in result and "jsonrpc" in result:
            error = result["error"]
        if isinstance(error, dict):
            future.set_exception(
                MsmpError(int(error.get("code", 0)), str(error.get("message", "Error")), error.get("data"))
            )
        else:
            future.set_result(result)
