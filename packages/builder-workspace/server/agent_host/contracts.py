"""AG-001 provider-neutral contracts for XACE Agent Mode.

These contracts deliberately model agents as proposal producers. They do not
grant project mutation, shell, credential, GDE, SGC, or runtime authority.
"""

from __future__ import annotations

import math
import re
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, TypeAlias, TypeVar


AGENT_CONTRACT_SCHEMA = "xace.agent_host.v1"

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_CGS_HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_ENUM = TypeVar("_ENUM", bound=Enum)


class AgentContractError(ValueError):
    """Raised when an agent-host contract object is invalid."""


class AgentMode(str, Enum):
    API_BYOK = "api_byok"
    AGENT = "agent"
    LOCAL_AGENT = "local_agent"


class AgentProviderKind(str, Enum):
    MOCK = "mock"
    CODEX_APP_SERVER = "codex_app_server"
    CLAUDE_RESERVED = "claude_reserved"
    LOCAL_RESERVED = "local_reserved"
    CUSTOM = "custom"


class AgentAuthState(str, Enum):
    NOT_REQUIRED = "not_required"
    SIGNED_IN = "signed_in"
    API_KEY = "api_key"
    MISSING = "missing"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class ToolTransport(str, Enum):
    MCP = "mcp"
    PROVIDER_DIRECT = "provider_direct"
    INTERNAL = "internal"
    NONE = "none"


class AgentToolPermission(str, Enum):
    READ_ONLY = "read_only"
    PROPOSAL_WRITE = "proposal_write"
    DENIED = "denied"


class AgentEventType(str, Enum):
    SESSION_STARTED = "session_started"
    TURN_STARTED = "turn_started"
    STATUS = "status"
    TOOL_CALL = "tool_call"
    PROPOSAL = "proposal"
    TURN_COMPLETED = "turn_completed"
    TURN_CANCELLED = "turn_cancelled"
    ERROR = "error"


class AgentRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentProposalKind(str, Enum):
    NO_OP = "no_op"
    MUTATION = "mutation"


def utc_now_iso() -> str:
    """Return a compact UTC timestamp for event metadata."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def normalize_json_value(value: Any, label: str = "value") -> JsonValue:
    """Return a JSON-safe deep copy or raise a contract error."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AgentContractError(f"{label} must be a finite JSON number")
        return value
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise AgentContractError(f"{label} object keys must be strings")
            normalized[key] = normalize_json_value(item, f"{label}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            normalize_json_value(item, f"{label}[{index}]")
            for index, item in enumerate(value)
        ]
    raise AgentContractError(
        f"{label} must be JSON-safe; got {type(value).__name__}"
    )


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise AgentContractError(
            f"{label} must match {_IDENTIFIER_RE.pattern!r}; got {value!r}"
        )


def _require_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentContractError(f"{label} must not be empty")


def _require_cgs_hash(value: str, label: str = "base_cgs_hash") -> None:
    if not isinstance(value, str) or not _CGS_HASH_RE.fullmatch(value):
        raise AgentContractError(f"{label} must be a 64-character hex CGS hash")


def _require_bool(value: bool, label: str) -> None:
    if not isinstance(value, bool):
        raise AgentContractError(f"{label} must be boolean")


def _enum(enum_cls: type[_ENUM], value: _ENUM | str, label: str) -> _ENUM:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise AgentContractError(f"{label} has unsupported value {value!r}") from exc


def _str_tuple(values: Iterable[str] | None, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raise AgentContractError(f"{label} must be an iterable of strings")
    result = tuple(values)
    for value in result:
        _require_nonempty(value, label)
    return result


def _json_object(value: Mapping[str, Any] | None, label: str) -> dict[str, JsonValue]:
    normalized = normalize_json_value(dict(value or {}), label)
    if not isinstance(normalized, dict):
        raise AgentContractError(f"{label} must be a JSON object")
    return normalized


def _json_object_tuple(
    values: Iterable[Mapping[str, Any]] | None,
    label: str,
) -> tuple[dict[str, JsonValue], ...]:
    if values is None:
        return ()
    result: list[dict[str, JsonValue]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise AgentContractError(f"{label}[{index}] must be a JSON object")
        result.append(_json_object(value, f"{label}[{index}]"))
    return tuple(result)


@dataclass(frozen=True)
class AgentSecurityPolicy:
    allow_raw_shell: bool = False
    allow_real_project_writes: bool = False
    allow_direct_gde_commit: bool = False
    allow_direct_runtime_mutation: bool = False
    allow_credential_access: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "allow_raw_shell",
            "allow_real_project_writes",
            "allow_direct_gde_commit",
            "allow_direct_runtime_mutation",
            "allow_credential_access",
        ):
            _require_bool(getattr(self, field_name), field_name)

    @property
    def builder_safe(self) -> bool:
        return not any(
            (
                self.allow_raw_shell,
                self.allow_real_project_writes,
                self.allow_direct_gde_commit,
                self.allow_direct_runtime_mutation,
                self.allow_credential_access,
            )
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "allow_raw_shell": self.allow_raw_shell,
            "allow_real_project_writes": self.allow_real_project_writes,
            "allow_direct_gde_commit": self.allow_direct_gde_commit,
            "allow_direct_runtime_mutation": self.allow_direct_runtime_mutation,
            "allow_credential_access": self.allow_credential_access,
            "builder_safe": self.builder_safe,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentSecurityPolicy":
        return cls(
            allow_raw_shell=bool(value.get("allow_raw_shell", False)),
            allow_real_project_writes=bool(
                value.get("allow_real_project_writes", False)
            ),
            allow_direct_gde_commit=bool(value.get("allow_direct_gde_commit", False)),
            allow_direct_runtime_mutation=bool(
                value.get("allow_direct_runtime_mutation", False)
            ),
            allow_credential_access=bool(value.get("allow_credential_access", False)),
        )


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    description: str
    permission: AgentToolPermission
    transport: ToolTransport = ToolTransport.MCP
    read_only: bool = True
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.name, "tool name")
        _require_nonempty(self.description, "tool description")
        object.__setattr__(
            self,
            "permission",
            _enum(AgentToolPermission, self.permission, "tool permission"),
        )
        object.__setattr__(
            self,
            "transport",
            _enum(ToolTransport, self.transport, "tool transport"),
        )
        _require_bool(self.read_only, "tool read_only")
        if (
            self.permission is AgentToolPermission.READ_ONLY
            and self.read_only is not True
        ):
            raise AgentContractError("read-only tools must set read_only=True")
        if self.permission is AgentToolPermission.PROPOSAL_WRITE and self.read_only:
            raise AgentContractError("proposal-write tools must set read_only=False")
        object.__setattr__(
            self,
            "input_schema",
            _json_object(self.input_schema, "tool input_schema"),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "transport": self.transport.value,
            "read_only": self.read_only,
            "input_schema": dict(self.input_schema),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentToolSpec":
        return cls(
            name=str(value.get("name", "")),
            description=str(value.get("description", "")),
            permission=_enum(
                AgentToolPermission,
                str(value.get("permission", "")),
                "tool permission",
            ),
            transport=_enum(
                ToolTransport,
                str(value.get("transport", ToolTransport.MCP.value)),
                "tool transport",
            ),
            read_only=bool(value.get("read_only", True)),
            input_schema=_json_object(value.get("input_schema", {}), "input_schema"),
        )


@dataclass(frozen=True)
class AgentCapabilities:
    supports_mcp_tools: bool = False
    supports_streaming_events: bool = False
    supports_thread_resume: bool = False
    supports_thread_fork: bool = False
    supports_compaction: bool = False
    supports_cancellation: bool = False
    supports_model_discovery: bool = False
    supports_account_state: bool = False
    supports_progressive_retrieval: bool = False
    supported_tool_transports: tuple[ToolTransport, ...] = ()
    xace_tools: tuple[AgentToolSpec, ...] = ()
    security_policy: AgentSecurityPolicy = field(default_factory=AgentSecurityPolicy)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "supports_mcp_tools",
            "supports_streaming_events",
            "supports_thread_resume",
            "supports_thread_fork",
            "supports_compaction",
            "supports_cancellation",
            "supports_model_discovery",
            "supports_account_state",
            "supports_progressive_retrieval",
        ):
            _require_bool(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "supported_tool_transports",
            tuple(
                _enum(ToolTransport, transport, "supported_tool_transports")
                for transport in self.supported_tool_transports
            ),
        )
        object.__setattr__(
            self,
            "xace_tools",
            tuple(
                tool if isinstance(tool, AgentToolSpec) else AgentToolSpec.from_dict(tool)
                for tool in self.xace_tools
            ),
        )
        if not isinstance(self.security_policy, AgentSecurityPolicy):
            object.__setattr__(
                self,
                "security_policy",
                AgentSecurityPolicy.from_dict(self.security_policy),
            )
        object.__setattr__(self, "warnings", _str_tuple(self.warnings, "warnings"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "supports_mcp_tools": self.supports_mcp_tools,
            "supports_streaming_events": self.supports_streaming_events,
            "supports_thread_resume": self.supports_thread_resume,
            "supports_thread_fork": self.supports_thread_fork,
            "supports_compaction": self.supports_compaction,
            "supports_cancellation": self.supports_cancellation,
            "supports_model_discovery": self.supports_model_discovery,
            "supports_account_state": self.supports_account_state,
            "supports_progressive_retrieval": self.supports_progressive_retrieval,
            "supported_tool_transports": [
                transport.value for transport in self.supported_tool_transports
            ],
            "xace_tools": [tool.to_dict() for tool in self.xace_tools],
            "security_policy": self.security_policy.to_dict(),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentCapabilities":
        return cls(
            supports_mcp_tools=bool(value.get("supports_mcp_tools", False)),
            supports_streaming_events=bool(
                value.get("supports_streaming_events", False)
            ),
            supports_thread_resume=bool(value.get("supports_thread_resume", False)),
            supports_thread_fork=bool(value.get("supports_thread_fork", False)),
            supports_compaction=bool(value.get("supports_compaction", False)),
            supports_cancellation=bool(value.get("supports_cancellation", False)),
            supports_model_discovery=bool(
                value.get("supports_model_discovery", False)
            ),
            supports_account_state=bool(value.get("supports_account_state", False)),
            supports_progressive_retrieval=bool(
                value.get("supports_progressive_retrieval", False)
            ),
            supported_tool_transports=tuple(
                _enum(ToolTransport, item, "supported_tool_transports")
                for item in value.get("supported_tool_transports", ())
            ),
            xace_tools=tuple(
                AgentToolSpec.from_dict(item)
                for item in value.get("xace_tools", ())
            ),
            security_policy=AgentSecurityPolicy.from_dict(
                value.get("security_policy", {})
            ),
            warnings=_str_tuple(value.get("warnings", ()), "warnings"),
        )


@dataclass(frozen=True)
class AgentProviderStatus:
    provider_id: str
    display_name: str
    provider_kind: AgentProviderKind
    installed: bool
    available: bool
    auth_state: AgentAuthState = AgentAuthState.UNKNOWN
    executable_path: str | None = None
    version: str | None = None
    min_supported_version: str | None = None
    account_label: str | None = None
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    warnings: tuple[str, ...] = ()
    last_checked_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = AGENT_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTRACT_SCHEMA:
            raise AgentContractError(
                f"schema must equal {AGENT_CONTRACT_SCHEMA!r}"
            )
        _require_identifier(self.provider_id, "provider_id")
        _require_nonempty(self.display_name, "display_name")
        object.__setattr__(
            self,
            "provider_kind",
            _enum(AgentProviderKind, self.provider_kind, "provider_kind"),
        )
        _require_bool(self.installed, "installed")
        _require_bool(self.available, "available")
        object.__setattr__(
            self,
            "auth_state",
            _enum(AgentAuthState, self.auth_state, "auth_state"),
        )
        if not isinstance(self.capabilities, AgentCapabilities):
            object.__setattr__(
                self,
                "capabilities",
                AgentCapabilities.from_dict(self.capabilities),
            )
        object.__setattr__(self, "warnings", _str_tuple(self.warnings, "warnings"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_kind": self.provider_kind.value,
            "installed": self.installed,
            "available": self.available,
            "auth_state": self.auth_state.value,
            "executable_path": self.executable_path,
            "version": self.version,
            "min_supported_version": self.min_supported_version,
            "account_label": self.account_label,
            "capabilities": self.capabilities.to_dict(),
            "warnings": list(self.warnings),
            "last_checked_at": self.last_checked_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentProviderStatus":
        return cls(
            provider_id=str(value.get("provider_id", "")),
            display_name=str(value.get("display_name", "")),
            provider_kind=_enum(
                AgentProviderKind,
                str(value.get("provider_kind", "")),
                "provider_kind",
            ),
            installed=bool(value.get("installed", False)),
            available=bool(value.get("available", False)),
            auth_state=_enum(
                AgentAuthState,
                str(value.get("auth_state", AgentAuthState.UNKNOWN.value)),
                "auth_state",
            ),
            executable_path=value.get("executable_path"),
            version=value.get("version"),
            min_supported_version=value.get("min_supported_version"),
            account_label=value.get("account_label"),
            capabilities=AgentCapabilities.from_dict(value.get("capabilities", {})),
            warnings=_str_tuple(value.get("warnings", ()), "warnings"),
            last_checked_at=str(value.get("last_checked_at", "")),
            metadata=_json_object(value.get("metadata", {}), "metadata"),
            schema=str(value.get("schema", AGENT_CONTRACT_SCHEMA)),
        )


@dataclass(frozen=True)
class AgentSessionHandle:
    xace_session_id: str
    provider_id: str
    provider_session_id: str
    base_cgs_hash: str
    latest_cgs_hash: str | None = None
    created_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = AGENT_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTRACT_SCHEMA:
            raise AgentContractError(
                f"schema must equal {AGENT_CONTRACT_SCHEMA!r}"
            )
        _require_identifier(self.xace_session_id, "xace_session_id")
        _require_identifier(self.provider_id, "provider_id")
        _require_nonempty(self.provider_session_id, "provider_session_id")
        _require_cgs_hash(self.base_cgs_hash)
        if self.latest_cgs_hash is not None:
            _require_cgs_hash(self.latest_cgs_hash, "latest_cgs_hash")
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "xace_session_id": self.xace_session_id,
            "provider_id": self.provider_id,
            "provider_session_id": self.provider_session_id,
            "base_cgs_hash": self.base_cgs_hash,
            "latest_cgs_hash": self.latest_cgs_hash,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentSessionHandle":
        latest = value.get("latest_cgs_hash")
        return cls(
            xace_session_id=str(value.get("xace_session_id", "")),
            provider_id=str(value.get("provider_id", "")),
            provider_session_id=str(value.get("provider_session_id", "")),
            base_cgs_hash=str(value.get("base_cgs_hash", "")),
            latest_cgs_hash=None if latest is None else str(latest),
            created_at=str(value.get("created_at", "")),
            metadata=_json_object(value.get("metadata", {}), "metadata"),
            schema=str(value.get("schema", AGENT_CONTRACT_SCHEMA)),
        )


@dataclass(frozen=True)
class AgentStartRequest:
    xace_session_id: str
    user_prompt: str
    base_cgs_hash: str
    project_id: str = ""
    context_capsule_path: str | None = None
    allowed_tools: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = AGENT_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTRACT_SCHEMA:
            raise AgentContractError(
                f"schema must equal {AGENT_CONTRACT_SCHEMA!r}"
            )
        _require_identifier(self.xace_session_id, "xace_session_id")
        _require_nonempty(self.user_prompt, "user_prompt")
        _require_cgs_hash(self.base_cgs_hash)
        if self.project_id:
            _require_identifier(self.project_id, "project_id")
        object.__setattr__(
            self,
            "allowed_tools",
            _str_tuple(self.allowed_tools, "allowed_tools"),
        )
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "xace_session_id": self.xace_session_id,
            "user_prompt": self.user_prompt,
            "base_cgs_hash": self.base_cgs_hash,
            "project_id": self.project_id,
            "context_capsule_path": self.context_capsule_path,
            "allowed_tools": list(self.allowed_tools),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentTurnRequest:
    handle: AgentSessionHandle
    user_prompt: str
    base_cgs_hash: str
    allowed_tools: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = AGENT_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTRACT_SCHEMA:
            raise AgentContractError(
                f"schema must equal {AGENT_CONTRACT_SCHEMA!r}"
            )
        if not isinstance(self.handle, AgentSessionHandle):
            object.__setattr__(
                self,
                "handle",
                AgentSessionHandle.from_dict(self.handle),
            )
        _require_nonempty(self.user_prompt, "user_prompt")
        _require_cgs_hash(self.base_cgs_hash)
        object.__setattr__(
            self,
            "allowed_tools",
            _str_tuple(self.allowed_tools, "allowed_tools"),
        )
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "handle": self.handle.to_dict(),
            "user_prompt": self.user_prompt,
            "base_cgs_hash": self.base_cgs_hash,
            "allowed_tools": list(self.allowed_tools),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentProposalEnvelope:
    proposal_id: str
    session_id: str
    provider_id: str
    base_cgs_hash: str
    intent: str
    summary: str
    operations: tuple[Mapping[str, Any], ...] = ()
    required_assets: tuple[Mapping[str, Any], ...] = ()
    validation_claims: tuple[Mapping[str, Any], ...] = ()
    risk_level: AgentRiskLevel = AgentRiskLevel.LOW
    proposal_kind: AgentProposalKind = AgentProposalKind.NO_OP
    requires_structural_regeneration: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema: str = AGENT_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTRACT_SCHEMA:
            raise AgentContractError(
                f"schema must equal {AGENT_CONTRACT_SCHEMA!r}"
            )
        _require_identifier(self.proposal_id, "proposal_id")
        _require_identifier(self.session_id, "session_id")
        _require_identifier(self.provider_id, "provider_id")
        _require_cgs_hash(self.base_cgs_hash)
        _require_nonempty(self.intent, "intent")
        _require_nonempty(self.summary, "summary")
        object.__setattr__(
            self,
            "operations",
            _json_object_tuple(self.operations, "operations"),
        )
        object.__setattr__(
            self,
            "required_assets",
            _json_object_tuple(self.required_assets, "required_assets"),
        )
        object.__setattr__(
            self,
            "validation_claims",
            _json_object_tuple(self.validation_claims, "validation_claims"),
        )
        object.__setattr__(
            self,
            "risk_level",
            _enum(AgentRiskLevel, self.risk_level, "risk_level"),
        )
        object.__setattr__(
            self,
            "proposal_kind",
            _enum(AgentProposalKind, self.proposal_kind, "proposal_kind"),
        )
        _require_bool(
            self.requires_structural_regeneration,
            "requires_structural_regeneration",
        )
        if self.proposal_kind is AgentProposalKind.MUTATION and not self.operations:
            raise AgentContractError("mutation proposals require at least one operation")
        if self.proposal_kind is AgentProposalKind.NO_OP and self.operations:
            raise AgentContractError("no-op proposals must not include operations")
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "proposal_id": self.proposal_id,
            "session_id": self.session_id,
            "provider_id": self.provider_id,
            "base_cgs_hash": self.base_cgs_hash,
            "intent": self.intent,
            "summary": self.summary,
            "operations": [dict(operation) for operation in self.operations],
            "required_assets": [dict(asset) for asset in self.required_assets],
            "validation_claims": [
                dict(claim) for claim in self.validation_claims
            ],
            "risk_level": self.risk_level.value,
            "proposal_kind": self.proposal_kind.value,
            "requires_structural_regeneration": self.requires_structural_regeneration,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentProposalEnvelope":
        return cls(
            proposal_id=str(value.get("proposal_id", "")),
            session_id=str(value.get("session_id", "")),
            provider_id=str(value.get("provider_id", "")),
            base_cgs_hash=str(value.get("base_cgs_hash", "")),
            intent=str(value.get("intent", "")),
            summary=str(value.get("summary", "")),
            operations=tuple(value.get("operations", ())),
            required_assets=tuple(value.get("required_assets", ())),
            validation_claims=tuple(value.get("validation_claims", ())),
            risk_level=_enum(
                AgentRiskLevel,
                str(value.get("risk_level", AgentRiskLevel.LOW.value)),
                "risk_level",
            ),
            proposal_kind=_enum(
                AgentProposalKind,
                str(value.get("proposal_kind", AgentProposalKind.NO_OP.value)),
                "proposal_kind",
            ),
            requires_structural_regeneration=bool(
                value.get("requires_structural_regeneration", False)
            ),
            metadata=_json_object(value.get("metadata", {}), "metadata"),
            schema=str(value.get("schema", AGENT_CONTRACT_SCHEMA)),
        )


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    event_type: AgentEventType
    session_id: str
    provider_id: str
    sequence: int
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    schema: str = AGENT_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTRACT_SCHEMA:
            raise AgentContractError(
                f"schema must equal {AGENT_CONTRACT_SCHEMA!r}"
            )
        _require_identifier(self.event_id, "event_id")
        object.__setattr__(
            self,
            "event_type",
            _enum(AgentEventType, self.event_type, "event_type"),
        )
        _require_identifier(self.session_id, "session_id")
        _require_identifier(self.provider_id, "provider_id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise AgentContractError("sequence must be an integer")
        if self.sequence < 0:
            raise AgentContractError("sequence must be non-negative")
        if not isinstance(self.message, str):
            raise AgentContractError("message must be a string")
        object.__setattr__(self, "data", _json_object(self.data, "data"))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "provider_id": self.provider_id,
            "sequence": self.sequence,
            "message": self.message,
            "data": dict(self.data),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentEvent":
        return cls(
            event_id=str(value.get("event_id", "")),
            event_type=_enum(
                AgentEventType,
                str(value.get("event_type", "")),
                "event_type",
            ),
            session_id=str(value.get("session_id", "")),
            provider_id=str(value.get("provider_id", "")),
            sequence=int(value.get("sequence", -1)),
            message=str(value.get("message", "")),
            data=_json_object(value.get("data", {}), "data"),
            created_at=str(value.get("created_at", "")),
            schema=str(value.get("schema", AGENT_CONTRACT_SCHEMA)),
        )


class AgentAdapter(Protocol):
    provider_id: str

    async def detect(self) -> AgentProviderStatus:
        """Return install/auth/capability status without mutating project state."""

    async def list_capabilities(self) -> AgentCapabilities:
        """Return the adapter's currently available XACE-safe capabilities."""

    async def start_session(self, request: AgentStartRequest) -> AgentSessionHandle:
        """Start a provider-native session or local equivalent."""

    async def resume_session(self, handle: AgentSessionHandle) -> AgentSessionHandle:
        """Resume a provider-native session or fail closed."""

    def run_turn(self, request: AgentTurnRequest) -> AsyncIterator[AgentEvent]:
        """Stream provider events mapped into XACE's provider-neutral contract."""

    async def cancel_turn(self, handle: AgentSessionHandle) -> None:
        """Cancel a turn without committing any project mutation."""
