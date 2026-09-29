"""Session-scoped native MCP transport for the XACE Codex integration.

Codex launches a fixed stdio proxy. The proxy authenticates to this loopback
broker and forwards MCP JSON-RPC messages to the live in-process XACE tool
surface. The session secret is inherited through the App Server environment;
it is never placed in argv, thread configuration, or persisted metadata.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import secrets
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import JsonValue, normalize_json_value
from .mcp_server import XaceMcpToolBridge


XACE_MCP_SESSION_TOKEN_ENV = "XACE_MCP_SESSION_TOKEN"
XACE_MCP_MAX_LINE_BYTES = 8 * 1024 * 1024
XACE_MCP_STARTUP_TIMEOUT_SECONDS = 5.0
XACE_MCP_TOOL_TIMEOUT_SECONDS = 60.0


class XaceMcpTransportError(RuntimeError):
    """Raised when the local MCP transport cannot be trusted or started."""


@dataclass(frozen=True)
class XaceMcpLaunchConfig:
    """Non-secret launch data plus the environment inherited by App Server."""

    thread_config: dict[str, JsonValue]
    app_server_environment: dict[str, str]


class XaceMcpNativeTransport:
    """Own one authenticated loopback broker for one Codex App Server session."""

    def __init__(
        self,
        bridge: XaceMcpToolBridge,
        listener: socket.socket,
        *,
        token: str,
    ) -> None:
        self._bridge = bridge
        self._listener = listener
        self._token = token
        self._closed = threading.Event()
        self._connections: set[socket.socket] = set()
        self._connections_lock = threading.RLock()
        self._bridge_lock = threading.RLock()
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="xace-mcp-loopback-broker",
            daemon=True,
        )
        self._thread.start()

    @classmethod
    def start(cls, bridge: XaceMcpToolBridge) -> "XaceMcpNativeTransport":
        if not isinstance(bridge, XaceMcpToolBridge):
            raise XaceMcpTransportError("bridge must be an XaceMcpToolBridge")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            listener.settimeout(0.2)
            return cls(bridge, listener, token=secrets.token_urlsafe(32))
        except Exception:
            listener.close()
            raise

    @property
    def launch_config(self) -> XaceMcpLaunchConfig:
        host, port = self._listener.getsockname()
        if host != "127.0.0.1":  # pragma: no cover - construction invariant
            raise XaceMcpTransportError("XACE MCP broker is not loopback-bound")
        proxy = Path(__file__).with_name("mcp_stdio_proxy.py").resolve()
        if not proxy.is_file():
            raise XaceMcpTransportError("XACE MCP stdio proxy is missing")
        server_config: dict[str, Any] = {
            "command": str(Path(sys.executable).resolve()),
            "args": [str(proxy), "--host", host, "--port", str(port)],
            "env_vars": [XACE_MCP_SESSION_TOKEN_ENV],
            "enabled": True,
            "required": True,
            "startup_timeout_sec": XACE_MCP_STARTUP_TIMEOUT_SECONDS,
            "tool_timeout_sec": XACE_MCP_TOOL_TIMEOUT_SECONDS,
            "enabled_tools": list(self._bridge.tool_names),
        }
        normalized = normalize_json_value(
            {"mcp_servers": {self._bridge.server_name: server_config}},
            "native MCP thread config",
        )
        if not isinstance(normalized, dict):  # pragma: no cover - normalize guard
            raise XaceMcpTransportError("Native MCP thread config must be an object")
        return XaceMcpLaunchConfig(
            thread_config=normalized,
            app_server_environment={XACE_MCP_SESSION_TOKEN_ENV: self._token},
        )

    def metadata(self) -> dict[str, JsonValue]:
        """Return persistence-safe state with no endpoint or session secret."""

        return {
            "transport": "mcp_stdio",
            "server_name": self._bridge.server_name,
            "required": True,
            "loopback_only": True,
            "authenticated": True,
            "secret_persisted": False,
            "tools": list(self._bridge.tool_names),
        }

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        with contextlib.suppress(Exception):
            self._listener.close()
        with self._connections_lock:
            connections = tuple(self._connections)
        for connection in connections:
            with contextlib.suppress(Exception):
                connection.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(Exception):
                connection.close()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

    def _accept_loop(self) -> None:
        while not self._closed.is_set():
            try:
                connection, address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if address[0] != "127.0.0.1":
                connection.close()
                continue
            with self._connections_lock:
                self._connections.add(connection)
            threading.Thread(
                target=self._serve_connection,
                args=(connection,),
                name="xace-mcp-loopback-connection",
                daemon=True,
            ).start()

    def _serve_connection(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(XACE_MCP_TOOL_TIMEOUT_SECONDS)
            reader = connection.makefile("rb")
            writer = connection.makefile("wb")
            try:
                auth = self._read_object(reader)
                supplied = str(auth.get("token") or "")
                if not hmac.compare_digest(supplied, self._token):
                    self._write_object(writer, {"ok": False, "error": "unauthorized"})
                    return
                self._write_object(writer, {"ok": True})
                while not self._closed.is_set():
                    envelope = self._read_object(reader, allow_eof=True)
                    if envelope is None:
                        return
                    message = envelope.get("message")
                    if not isinstance(message, dict):
                        self._write_object(writer, {"error": "invalid MCP message"})
                        continue
                    with self._bridge_lock:
                        response = self._bridge.handle_mcp_message(message)
                    self._write_object(writer, {"response": response})
            finally:
                with contextlib.suppress(Exception):
                    reader.close()
                with contextlib.suppress(Exception):
                    writer.close()
        except (EOFError, OSError, ValueError, XaceMcpTransportError):
            return
        finally:
            with self._connections_lock:
                self._connections.discard(connection)
            with contextlib.suppress(Exception):
                connection.close()

    @staticmethod
    def _read_object(reader: Any, *, allow_eof: bool = False) -> dict[str, Any] | None:
        line = reader.readline(XACE_MCP_MAX_LINE_BYTES + 1)
        if not line:
            if allow_eof:
                return None
            raise EOFError("MCP broker connection closed")
        if len(line) > XACE_MCP_MAX_LINE_BYTES or not line.endswith(b"\n"):
            raise XaceMcpTransportError("MCP broker message exceeded its size limit")
        value = json.loads(line.decode("utf-8"))
        if not isinstance(value, dict):
            raise XaceMcpTransportError("MCP broker message must be an object")
        return value

    @staticmethod
    def _write_object(writer: Any, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > XACE_MCP_MAX_LINE_BYTES:
            raise XaceMcpTransportError("MCP broker response exceeded its size limit")
        writer.write(payload + b"\n")
        writer.flush()


__all__ = [
    "XACE_MCP_MAX_LINE_BYTES",
    "XACE_MCP_SESSION_TOKEN_ENV",
    "XaceMcpLaunchConfig",
    "XaceMcpNativeTransport",
    "XaceMcpTransportError",
]
