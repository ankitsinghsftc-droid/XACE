"""Read-only, provider-neutral MCP bridge for XACE Agent Mode.

The bridge owns the MCP-shaped tool protocol and delegates every invocation to
``XaceToolSurface``.  It deliberately exposes no resources, prompts, shell,
file-write, credential, GDE, or runtime-mutation capability.

Codex App Server normally consumes configured MCP servers from its own config.
For an embedded XACE session, changing that global provider configuration would
be unsafe.  The same bridge therefore also renders the catalog as documented
App Server dynamic tools.  That is a transport fallback only: permissions,
arguments, results, and audit records remain the shared XACE tool contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from secret_redaction import redact_text, redact_value

from .contracts import AgentToolSpec, JsonValue, ToolTransport, normalize_json_value
from .tool_surface import (
    AGENT_TOOL_CALL_RESULT_SCHEMA,
    AGENT_TOOL_SURFACE_SCHEMA,
    READ_ONLY_XACE_TOOL_NAMES,
    XaceToolCallRequest,
    XaceToolCallResult,
    XaceToolSurface,
)


AGENT_MCP_BRIDGE_SCHEMA = "xace.agent_mcp_bridge.v1"
XACE_MCP_SERVER_NAME = "xace"
XACE_MCP_PROTOCOL_VERSION = "2024-11-05"

_JSONRPC_INVALID_REQUEST = -32600
_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_INVALID_PARAMS = -32602


class XaceMcpBridgeError(RuntimeError):
    """Raised when an MCP request is malformed or unsafe for XACE."""


@dataclass(frozen=True)
class XaceMcpToolContext:
    """Identity bound by XACE, never supplied by the agent tool arguments."""

    xace_session_id: str
    provider_id: str
    cgs_hash: str
    allowed_tools: tuple[str, ...] = field(default_factory=lambda: READ_ONLY_XACE_TOOL_NAMES)

    def __post_init__(self) -> None:
        # Reuse the authoritative contract validation rather than maintaining a
        # second identifier/hash validator in the MCP layer.
        XaceToolCallRequest(
            tool_name=READ_ONLY_XACE_TOOL_NAMES[0],
            xace_session_id=self.xace_session_id,
            provider_id=self.provider_id,
            cgs_hash=self.cgs_hash,
        )
        tools = tuple(str(item or "").strip() for item in self.allowed_tools)
        if not tools:
            tools = READ_ONLY_XACE_TOOL_NAMES
        unsupported = sorted(set(tools).difference(READ_ONLY_XACE_TOOL_NAMES))
        if unsupported:
            raise XaceMcpBridgeError(
                "XACE MCP context may only allow read-only XACE tools: "
                + ", ".join(unsupported)
            )
        object.__setattr__(self, "allowed_tools", tuple(sorted(set(tools))))


class XaceMcpToolBridge:
    """Serve XACE's stable read-only tool contract over MCP or a safe fallback."""

    def __init__(
        self,
        surface: XaceToolSurface,
        context: XaceMcpToolContext,
        *,
        server_name: str = XACE_MCP_SERVER_NAME,
    ) -> None:
        if not isinstance(surface, XaceToolSurface):
            raise XaceMcpBridgeError("surface must be an XaceToolSurface")
        if not isinstance(context, XaceMcpToolContext):
            raise XaceMcpBridgeError("context must be an XaceMcpToolContext")
        if not str(server_name or "").strip():
            raise XaceMcpBridgeError("server_name must be non-empty")
        self.surface = surface
        self.context = context
        self.server_name = str(server_name).strip()

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(
            tool_name
            for tool_name in READ_ONLY_XACE_TOOL_NAMES
            if tool_name in self.context.allowed_tools
        )

    def metadata(self) -> dict[str, JsonValue]:
        """Describe the bridge without exposing project data or credentials."""

        return {
            "schema": AGENT_MCP_BRIDGE_SCHEMA,
            "server_name": self.server_name,
            "preferred_transport": ToolTransport.MCP.value,
            "codex_fallback_transport": "app_server_dynamic_tools",
            "read_only": True,
            "tools": list(self.tool_names),
            "resources": False,
            "prompts": False,
            "raw_shell": False,
            "real_project_writes": False,
            "credential_access": False,
        }

    def mcp_tools(self) -> list[dict[str, JsonValue]]:
        return [_mcp_tool_descriptor(spec) for spec in self._tool_specs()]

    def codex_dynamic_tools(self) -> list[dict[str, JsonValue]]:
        """Render the same catalog for App Server's session-local fallback."""

        tools = []
        for spec in self._tool_specs():
            tool_name = _codex_dynamic_tool_name(spec.name)
            tools.append(
                {
                    "type": "function",
                    "name": tool_name,
                    "description": spec.description,
                    "inputSchema": dict(spec.input_schema),
                }
            )
        return [
            {
                "type": "namespace",
                "name": self.server_name,
                "description": (
                    "Read-only XACE Builder project context. Use these tools instead "
                    "of shell, filesystem, credential, project-write, or runtime-write tools."
                ),
                "tools": tools,
            }
        ]

    def handle_mcp_message(self, message: Mapping[str, Any]) -> dict[str, JsonValue] | None:
        """Handle the intentionally small JSON-RPC/MCP surface used by XACE."""

        if not isinstance(message, Mapping):
            raise XaceMcpBridgeError("MCP message must be an object")
        method = str(message.get("method") or "").strip()
        request_id = message.get("id")
        if not method:
            return _jsonrpc_error(request_id, _JSONRPC_INVALID_REQUEST, "method is required")

        if method in {"notifications/initialized", "initialized"}:
            return None
        if method == "initialize":
            return _jsonrpc_result(
                request_id,
                {
                    "protocolVersion": XACE_MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.server_name, "version": "0.1.0"},
                },
            )
        if method == "tools/list":
            return _jsonrpc_result(request_id, {"tools": self.mcp_tools()})
        if method == "tools/call":
            params = message.get("params")
            if not isinstance(params, Mapping):
                return _jsonrpc_error(
                    request_id,
                    _JSONRPC_INVALID_PARAMS,
                    "tools/call params must be an object",
                )
            tool_name = str(params.get("name") or "").strip()
            if not tool_name:
                return _jsonrpc_error(
                    request_id, _JSONRPC_INVALID_PARAMS, "tools/call name is required"
                )
            arguments = params.get("arguments", {})
            if not isinstance(arguments, Mapping):
                return _jsonrpc_error(
                    request_id,
                    _JSONRPC_INVALID_PARAMS,
                    "tools/call arguments must be an object",
                )
            result = self.invoke(
                tool_name,
                arguments,
                call_id=_safe_call_id(params.get("_meta")),
                transport=ToolTransport.MCP,
            )
            return _jsonrpc_result(request_id, _mcp_tool_result(result))
        return _jsonrpc_error(
            request_id,
            _JSONRPC_METHOD_NOT_FOUND,
            f"MCP method {method!r} is not supported by XACE",
        )

    def handle_codex_dynamic_call(self, params: Mapping[str, Any]) -> dict[str, JsonValue]:
        """Return an App Server dynamic-tool response using the shared contract."""

        namespace = str(params.get("namespace") or "").strip()
        tool = str(params.get("tool") or "").strip()
        arguments = params.get("arguments", {})
        if namespace != self.server_name:
            return _codex_dynamic_error("XACE dynamic tool namespace is not allowlisted")
        if not isinstance(arguments, Mapping):
            return _codex_dynamic_error("XACE dynamic tool arguments must be an object")
        tool_name = f"{self.server_name}.{tool}" if tool else ""
        result = self.invoke(
            tool_name,
            arguments,
            call_id=_safe_call_id(params.get("callId")),
            transport=ToolTransport.PROVIDER_DIRECT,
        )
        return _codex_dynamic_result(result)

    def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        call_id: str = "",
        transport: ToolTransport = ToolTransport.MCP,
    ) -> XaceToolCallResult:
        """Execute through the sole XACE permission and audit boundary."""

        request = XaceToolCallRequest(
            tool_name=tool_name,
            xace_session_id=self.context.xace_session_id,
            provider_id=self.context.provider_id,
            cgs_hash=self.context.cgs_hash,
            arguments=arguments,
            call_id=call_id,
            transport=transport,
        )
        # Tool inclusion is narrowed when the catalog is rendered. The surface
        # remains the final allowlist/audit authority for every invocation.
        return self.surface.execute(request, allowed_tools=self.context.allowed_tools)

    def _tool_specs(self) -> tuple[AgentToolSpec, ...]:
        return tuple(
            spec for spec in self.surface.tool_specs() if spec.name in self.tool_names
        )


def _mcp_tool_descriptor(spec: AgentToolSpec) -> dict[str, JsonValue]:
    return {
        "name": spec.name,
        "description": spec.description,
        "inputSchema": dict(spec.input_schema),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
        "_meta": {
            "xace_schema": AGENT_TOOL_SURFACE_SCHEMA,
            "permission": spec.permission.value,
            "transport": ToolTransport.MCP.value,
        },
    }


def _mcp_tool_result(result: XaceToolCallResult) -> dict[str, JsonValue]:
    payload = result.to_dict()
    return {
        "content": [{"type": "text", "text": _canonical_json(payload)}],
        "structuredContent": dict(payload),
        "isError": not result.allowed,
        "_meta": {
            "xace_schema": AGENT_TOOL_CALL_RESULT_SCHEMA,
            "call_id": result.call_id,
            "status": result.status,
            "read_only": True,
        },
    }


def _codex_dynamic_result(result: XaceToolCallResult) -> dict[str, JsonValue]:
    return {
        "contentItems": [
            {"type": "inputText", "text": _canonical_json(result.to_dict())}
        ],
        "success": result.allowed,
    }


def _codex_dynamic_error(message: str) -> dict[str, JsonValue]:
    return {
        "contentItems": [{"type": "inputText", "text": redact_text(message)}],
        "success": False,
    }


def _jsonrpc_result(request_id: Any, result: Mapping[str, Any]) -> dict[str, JsonValue]:
    return _json_object({"id": request_id, "result": dict(result)})


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, JsonValue]:
    return _json_object(
        {
            "id": request_id,
            "error": {"code": code, "message": redact_text(message)},
        }
    )


def _codex_dynamic_tool_name(tool_name: str) -> str:
    prefix = f"{XACE_MCP_SERVER_NAME}."
    if not tool_name.startswith(prefix):
        raise XaceMcpBridgeError(f"XACE tool {tool_name!r} has no XACE namespace")
    name = tool_name[len(prefix) :]
    if not name.replace("_", "").isalnum():
        raise XaceMcpBridgeError(f"XACE dynamic tool name is unsafe: {tool_name!r}")
    return name


def _safe_call_id(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("callId") or value.get("call_id") or ""
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        XaceToolCallRequest(
            tool_name=READ_ONLY_XACE_TOOL_NAMES[0],
            xace_session_id="xace_mcp_probe",
            provider_id="xace",
            cgs_hash="0" * 64,
            call_id=candidate,
        )
    except Exception:
        return ""
    return candidate


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        redact_value(normalize_json_value(value, "mcp bridge payload")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_object(value: Mapping[str, Any]) -> dict[str, JsonValue]:
    normalized = normalize_json_value(redact_value(dict(value)), "mcp bridge object")
    if not isinstance(normalized, dict):  # pragma: no cover - normalize guard
        raise XaceMcpBridgeError("MCP bridge payload must be an object")
    return normalized


__all__ = [
    "AGENT_MCP_BRIDGE_SCHEMA",
    "XACE_MCP_PROTOCOL_VERSION",
    "XACE_MCP_SERVER_NAME",
    "XaceMcpBridgeError",
    "XaceMcpToolBridge",
    "XaceMcpToolContext",
]
