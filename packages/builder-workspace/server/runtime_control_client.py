"""
runtime_control_client.py - Builder client for xace_runtime control socket.

The runtime control socket uses little-endian length-prefixed JSON, matching
the engine adapter framing. Commands are lifecycle controls only; gameplay
input still flows through engine adapters and network-core.
"""

from __future__ import annotations

import json
import socket
import struct
import time
import uuid
from dataclasses import dataclass
from typing import Any


CONTROL_PROTOCOL_VERSION = 1
MAX_CONTROL_MESSAGE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class RuntimeControlConfig:
    host: str = "127.0.0.1"
    port: int = 7778
    timeout_seconds: float = 2.0


class RuntimeControlError(RuntimeError):
    pass


class RuntimeControlClient:
    def __init__(self, config: RuntimeControlConfig | None = None) -> None:
        self._config = config or RuntimeControlConfig()

    @property
    def endpoint(self) -> str:
        return f"{self._config.host}:{self._config.port}"

    def send_control(
        self,
        action: str,
        *,
        session_id: str = "",
        tick: int | None = None,
        version_ids: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_id = _request_id()
        payload: dict[str, Any] = {
            "msg_type": "runtime_control",
            "protocol_version": CONTROL_PROTOCOL_VERSION,
            "request_id": request_id,
            "action": action,
            "session_id": session_id,
        }
        if tick is not None:
            payload["tick"] = int(tick)
        if version_ids:
            cgs_hash = version_ids.get("cgs_hash")
            schema_version = version_ids.get("schema_version")
            execution_plan_version = version_ids.get("execution_plan_version")
            if cgs_hash:
                payload["cgs_hash"] = str(cgs_hash)
            if schema_version:
                payload["schema_version"] = str(schema_version)
            if execution_plan_version:
                plan_version = str(execution_plan_version)
                if plan_version != "unresolved" and plan_version.isdigit():
                    payload["execution_plan_version"] = plan_version

        response = self._round_trip(payload)
        if response.get("msg_type") != "runtime_control_ack":
            raise RuntimeControlError(
                f"unexpected runtime response: {response.get('msg_type')!r}"
            )
        if response.get("request_id") != request_id:
            raise RuntimeControlError("runtime response request_id mismatch")
        return response

    def send_engine_edit(
        self,
        kind: str,
        *,
        entity_id: int | str,
        session_id: str = "",
        component_type_id: int | None = None,
        field_path: str = "",
        value: Any = None,
    ) -> dict[str, Any]:
        request_id = _request_id()
        try:
            parsed_entity_id = int(entity_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeControlError(f"invalid entity_id: {entity_id!r}") from exc
        if parsed_entity_id <= 0:
            raise RuntimeControlError("entity_id must be greater than zero")

        payload: dict[str, Any] = {
            "msg_type": "runtime_engine_edit",
            "protocol_version": CONTROL_PROTOCOL_VERSION,
            "request_id": request_id,
            "kind": kind,
            "entity_id": parsed_entity_id,
            "session_id": session_id,
        }
        if component_type_id is not None:
            payload["component_type_id"] = int(component_type_id)
        if field_path:
            payload["field_path"] = str(field_path)
        if value is not None:
            payload["value"] = value

        response = self._round_trip(payload)
        if response.get("msg_type") != "runtime_engine_edit_ack":
            raise RuntimeControlError(
                f"unexpected runtime response: {response.get('msg_type')!r}"
            )
        if response.get("request_id") != request_id:
            raise RuntimeControlError("runtime response request_id mismatch")
        return response

    def status(self, *, session_id: str = "") -> dict[str, Any]:
        return self.send_control("status", session_id=session_id)

    def _round_trip(self, payload: dict[str, Any]) -> dict[str, Any]:
        with socket.create_connection(
            (self._config.host, self._config.port),
            timeout=self._config.timeout_seconds,
        ) as sock:
            sock.settimeout(self._config.timeout_seconds)
            _write_frame(sock, payload)
            return _read_frame(sock)


def _request_id() -> str:
    return f"builder-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"


def _write_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > MAX_CONTROL_MESSAGE_BYTES:
        raise RuntimeControlError(
            f"control message too large: {len(raw)} > {MAX_CONTROL_MESSAGE_BYTES}"
        )
    sock.sendall(struct.pack("<I", len(raw)))
    sock.sendall(raw)


def _read_frame(sock: socket.socket) -> dict[str, Any]:
    header = _read_exact(sock, 4)
    size = struct.unpack("<I", header)[0]
    if size == 0 or size > MAX_CONTROL_MESSAGE_BYTES:
        raise RuntimeControlError(f"invalid control response size: {size}")
    raw = _read_exact(sock, size)
    try:
        value = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeControlError(f"runtime returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeControlError("runtime response must be a JSON object")
    return value


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeControlError("runtime control socket closed early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
