"""Fail-closed security policy for XACE Builder Agent Mode.

The policy in this module is deliberately provider-neutral.  Adapters own
provider lifecycle and event mapping, but every adapter is constrained to the
same XACE tool catalog and proposal-only mutation boundary.  Provider-native
shell, filesystem, permission-escalation, credential, GDE, SGC, and runtime
mutation surfaces are never part of the Builder Agent capability set.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from secret_redaction import redact_text

from .contracts import (
    AgentCapabilities,
    AgentEvent,
    AgentEventType,
    AgentSecurityPolicy,
    AgentToolPermission,
    AgentToolSpec,
)


AGENT_SECURITY_POLICY_SCHEMA = "xace.agent_security_policy.v1"
AGENT_CAPSULE_DIR_PARTS = (".xace", "agent_capsules")
AGENT_PROPOSAL_TOOL_NAME = "xace.submit_proposal"

ALLOWED_CODEX_AGENT_METHODS = frozenset(
    {
        "thread/start",
        "thread/resume",
        "thread/fork",
        "thread/compact/start",
        "turn/start",
        "turn/interrupt",
        "thread/backgroundTerminals/clean",
        "mcpServerStatus/list",
    }
)

FORBIDDEN_PROVIDER_ITEM_TYPES = frozenset(
    {
        "applyPatch",
        "commandExecution",
        "fileChange",
        "imageGeneration",
        "requestPermissions",
        "webSearch",
    }
)

FORBIDDEN_PROVIDER_METHOD_FRAGMENTS = (
    "commandExecution",
    "fileChange",
    "applyPatch",
    "permissions/requestApproval",
)

FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "access_token",
        "allow_credential_access",
        "allow_direct_gde_commit",
        "allow_direct_runtime_mutation",
        "allow_raw_shell",
        "allow_real_project_writes",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "gde_commit",
        "password",
        "raw_shell",
        "refresh_token",
        "runtime_mutation",
        "secret",
        "shell_command",
        "token",
    }
)
BOOLEAN_AUTHORITY_METADATA_KEYS = frozenset(
    {
        "allow_credential_access",
        "allow_direct_gde_commit",
        "allow_direct_runtime_mutation",
        "allow_raw_shell",
        "allow_real_project_writes",
        "raw_shell",
        "runtime_mutation",
    }
)



class AgentSecurityPolicyError(RuntimeError):
    """Raised when Builder Agent Mode cannot prove a request is safe."""


@dataclass(frozen=True)
class AgentSecurityDecision:
    """A small auditable decision returned for provider-originated events."""

    allowed: bool
    code: str = ""
    reason: str = ""
    tool_name: str = ""
    schema: str = AGENT_SECURITY_POLICY_SCHEMA


class AgentSecurityPolicyEnforcer:
    """Enforce the immutable Builder Agent security boundary.

    The exact tool catalog is the authority.  Names that merely look safe are
    not accepted, and proposal-write permission is reserved for the one typed
    preview ingress tool.
    """

    def __init__(
        self,
        *,
        policy: AgentSecurityPolicy | None = None,
        tool_specs: Sequence[AgentToolSpec] = (),
    ) -> None:
        resolved = policy or AgentSecurityPolicy()
        if not isinstance(resolved, AgentSecurityPolicy):
            raise AgentSecurityPolicyError("security policy must be an AgentSecurityPolicy")
        if not resolved.builder_safe:
            raise AgentSecurityPolicyError(
                "Builder Agent Mode requires every privileged policy flag to remain false"
            )
        self.policy = resolved
        self._tools: dict[str, AgentToolSpec] = {}
        self.register_tool_specs(tool_specs)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def register_tool_specs(self, tool_specs: Sequence[AgentToolSpec]) -> None:
        for raw_spec in tool_specs:
            if not isinstance(raw_spec, AgentToolSpec):
                raise AgentSecurityPolicyError("tool catalogs must contain AgentToolSpec values")
            self._validate_tool_spec(raw_spec)
            existing = self._tools.get(raw_spec.name)
            if existing is not None and existing != raw_spec:
                raise AgentSecurityPolicyError(
                    f"conflicting Agent tool definition for {raw_spec.name!r}"
                )
            self._tools[raw_spec.name] = raw_spec

    def validate_capabilities(self, capabilities: AgentCapabilities) -> None:
        if not isinstance(capabilities, AgentCapabilities):
            raise AgentSecurityPolicyError("adapter capabilities are invalid")
        if not capabilities.security_policy.builder_safe:
            raise AgentSecurityPolicyError(
                "adapter requested privileges forbidden in Builder Agent Mode"
            )
        for spec in capabilities.xace_tools:
            self._validate_tool_spec(spec)
            configured = self._tools.get(spec.name)
            if configured is None or configured != spec:
                raise AgentSecurityPolicyError(
                    f"adapter advertised unregistered Agent tool {spec.name!r}"
                )

    def validate_metadata(self, metadata: Mapping[str, Any]) -> None:
        if not isinstance(metadata, Mapping):
            raise AgentSecurityPolicyError("Agent metadata must be an object")
        forbidden = sorted(_find_forbidden_metadata_keys(metadata))
        if forbidden:
            raise AgentSecurityPolicyError(
                "Agent metadata may not carry credentials or privileged authority: "
                + ", ".join(forbidden)
            )

    def require_tool(
        self,
        tool_name: str,
        *,
        enabled_tools: Sequence[str] | None = None,
    ) -> AgentToolSpec:
        name = str(tool_name or "").strip()
        spec = self._tools.get(name)
        if spec is None:
            raise AgentSecurityPolicyError(
                f"tool {name!r} is not allowlisted for Builder Agent Mode"
            )
        if enabled_tools is not None and name not in set(enabled_tools):
            raise AgentSecurityPolicyError(
                f"tool {name!r} is not enabled for this Builder Agent session"
            )
        return spec

    def validate_enabled_tools(self, tool_names: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(str(name or "").strip() for name in tool_names)
        if any(not name for name in normalized):
            raise AgentSecurityPolicyError("enabled Agent tool names must be non-empty")
        for name in normalized:
            self.require_tool(name)
        return tuple(dict.fromkeys(normalized))

    def require_codex_method(self, method: str) -> None:
        if method not in ALLOWED_CODEX_AGENT_METHODS:
            raise AgentSecurityPolicyError(
                f"Codex App Server method {method!r} is not available to Builder Agent Mode"
            )

    def resolve_capsule_cwd(
        self,
        context_capsule_path: str | None,
        metadata: Mapping[str, Any],
    ) -> str:
        """Resolve a Codex cwd and reject real-project or caller-selected roots."""

        self.validate_metadata(metadata)
        configured = str(context_capsule_path or "").strip()
        project_path = str(metadata.get("project_path") or "").strip()
        if not configured:
            if project_path:
                raise AgentSecurityPolicyError(
                    "Codex Agent Mode requires an XACE-built isolated context capsule"
                )
            return ""

        candidate = Path(configured).expanduser()
        cwd = candidate.parent if candidate.suffix else candidate
        cwd = cwd.resolve(strict=False)
        if project_path:
            project_root = Path(project_path).expanduser().resolve(strict=False)
            capsule_root = project_root.joinpath(*AGENT_CAPSULE_DIR_PARTS).resolve(strict=False)
            if cwd == project_root or not _is_relative_to(cwd, capsule_root):
                raise AgentSecurityPolicyError(
                    "Codex cwd must stay inside the XACE Agent context-capsule root"
                )
        return str(cwd)

    def codex_sandbox_policy(self, capsule_cwd: str) -> dict[str, Any]:
        readable_roots = [capsule_cwd] if capsule_cwd else []
        return {
            "type": "readOnly",
            "access": {
                "type": "restricted",
                "includePlatformDefaults": False,
                "readableRoots": readable_roots,
            },
        }

    def inspect_provider_event(
        self,
        notification: Mapping[str, Any],
        *,
        enabled_tools: Sequence[str] | None = None,
    ) -> AgentSecurityDecision:
        method = str(notification.get("method") or "").strip()
        params = notification.get("params")
        params = params if isinstance(params, Mapping) else {}
        item = params.get("item")
        item = item if isinstance(item, Mapping) else {}
        item_type = str(item.get("type") or params.get("type") or "").strip()

        if isinstance(notification.get("id"), (int, str)) and method != "item/tool/call":
            return _deny(
                "AGENT_PROVIDER_REQUEST_DENIED",
                "provider requested client authority outside the XACE tool bridge",
            )
        if method.startswith(("command/", "process/", "fs/")):
            return _deny(
                "AGENT_PROVIDER_CAPABILITY_DENIED",
                "provider attempted a raw command, process, or filesystem capability",
            )

        if any(fragment in method for fragment in FORBIDDEN_PROVIDER_METHOD_FRAGMENTS):
            return _deny("AGENT_PROVIDER_CAPABILITY_DENIED", "provider requested a forbidden capability")
        if item_type in FORBIDDEN_PROVIDER_ITEM_TYPES:
            return _deny(
                "AGENT_PROVIDER_CAPABILITY_DENIED",
                f"provider emitted forbidden {item_type} capability",
            )

        if method == "item/tool/call" or item_type in {"dynamicToolCall", "mcpToolCall", "toolCall"}:
            tool_name = _provider_tool_name(params, item)
            try:
                self.require_tool(tool_name, enabled_tools=enabled_tools)
            except AgentSecurityPolicyError as exc:
                return _deny("AGENT_TOOL_DENIED", str(exc), tool_name=tool_name)
            return AgentSecurityDecision(allowed=True, tool_name=tool_name)

        return AgentSecurityDecision(allowed=True)

    def validate_agent_event(
        self,
        event: AgentEvent,
        *,
        session_id: str,
        provider_id: str,
        enabled_tools: Sequence[str] | None = None,
    ) -> None:
        if event.session_id != session_id or event.provider_id != provider_id:
            raise AgentSecurityPolicyError(
                "adapter event identity does not match the active XACE Agent session"
            )
        if event.event_type is AgentEventType.PROPOSAL:
            proposal = event.data.get("proposal") if isinstance(event.data, Mapping) else None
            if not isinstance(proposal, Mapping):
                raise AgentSecurityPolicyError("Agent proposal events require a typed proposal object")
            return
        if event.event_type is not AgentEventType.TOOL_CALL:
            return

        tool_name = _agent_event_tool_name(event.data)
        self.require_tool(tool_name, enabled_tools=enabled_tools)

    def _validate_tool_spec(self, spec: AgentToolSpec) -> None:
        if not spec.name.startswith("xace."):
            raise AgentSecurityPolicyError("Builder Agent tools must use the xace namespace")
        if spec.permission is AgentToolPermission.DENIED:
            raise AgentSecurityPolicyError(f"denied tool {spec.name!r} cannot be advertised")
        if spec.permission is AgentToolPermission.PROPOSAL_WRITE:
            if spec.name != AGENT_PROPOSAL_TOOL_NAME or spec.read_only:
                raise AgentSecurityPolicyError(
                    "proposal-write authority is reserved for xace.submit_proposal preview ingress"
                )
        elif spec.permission is not AgentToolPermission.READ_ONLY or not spec.read_only:
            raise AgentSecurityPolicyError(
                f"tool {spec.name!r} requests unsupported Agent permission"
            )


def denial_response_for_provider_request(notification: Mapping[str, Any]) -> dict[str, Any]:
    """Return the least-authority response for a server-initiated request."""

    method = str(notification.get("method") or "")
    if method == "item/tool/call":
        return {
            "contentItems": [
                {
                    "type": "inputText",
                    "text": "XACE security policy denied this tool call.",
                }
            ],
            "success": False,
        }
    if method == "item/permissions/requestApproval":
        return {"permissions": []}
    if method == "mcpServer/elicitation/request":
        return {"action": "decline", "content": None}
    if method == "tool/requestUserInput":
        return {"action": "decline", "content": None}
    return {"decision": "decline"}


def _provider_tool_name(params: Mapping[str, Any], item: Mapping[str, Any]) -> str:
    namespace = str(
        params.get("namespace")
        or item.get("namespace")
        or item.get("server")
        or ""
    ).strip()
    raw = str(
        params.get("tool")
        or params.get("name")
        or item.get("tool")
        or item.get("name")
        or ""
    ).strip()
    if raw.startswith("xace."):
        return raw
    if namespace == "xace" and raw:
        return f"xace.{raw}"
    return raw


def _agent_event_tool_name(data: Mapping[str, Any]) -> str:
    direct = str(data.get("tool_name") or "").strip()
    if direct:
        return direct
    params = data.get("params")
    params = params if isinstance(params, Mapping) else {}
    item = params.get("item")
    item = item if isinstance(item, Mapping) else {}
    provider_name = _provider_tool_name(params, item)
    if provider_name:
        return provider_name

    response = params.get("xace_tool_response")
    items = response.get("contentItems") if isinstance(response, Mapping) else None
    first = items[0] if isinstance(items, list) and items and isinstance(items[0], Mapping) else {}
    text = first.get("text") if isinstance(first, Mapping) else None
    if isinstance(text, str):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, Mapping):
            return str(parsed.get("tool_name") or "").strip()
    return ""


def _find_forbidden_metadata_keys(value: Mapping[str, Any]) -> set[str]:
    found: set[str] = set()
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, child in current.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in FORBIDDEN_METADATA_KEYS:
                    disabled_authority = (
                        normalized in BOOLEAN_AUTHORITY_METADATA_KEYS and child in (False, None, "")
                    )
                    if not disabled_authority:
                        found.add(normalized)
                if isinstance(child, (Mapping, list, tuple)):
                    stack.append(child)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
    return found


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _deny(code: str, reason: str, *, tool_name: str = "") -> AgentSecurityDecision:
    return AgentSecurityDecision(
        allowed=False,
        code=code,
        reason=redact_text(reason),
        tool_name=tool_name,
    )


__all__ = [
    "AGENT_SECURITY_POLICY_SCHEMA",
    "ALLOWED_CODEX_AGENT_METHODS",
    "AgentSecurityDecision",
    "AgentSecurityPolicyEnforcer",
    "AgentSecurityPolicyError",
    "denial_response_for_provider_request",
]
