"""Deterministic, isolated context capsules for Agent Mode.

AG-004 gives provider agents enough project knowledge to be useful without
handing them the real project root. The initial capsule is written into
`.xace/agent_capsules/`, and deeper context is served through scoped,
read-only retrieval calls that can be logged by the AG-003 session store.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secret_redaction import redact_text, redact_value

from .contracts import (
    AGENT_CONTRACT_SCHEMA,
    AgentContractError,
    AgentProposalKind,
    AgentRiskLevel,
    JsonValue,
    normalize_json_value,
)
from .session_store import AgentSessionStore, AgentSessionStoreError, AgentToolCallRecord


AGENT_CONTEXT_CAPSULE_SCHEMA = "xace.agent_context_capsule.v1"
AGENT_CONTEXT_RETRIEVAL_SCHEMA = "xace.agent_context_retrieval.v1"
AGENT_CONTEXT_CAPSULE_DIRNAME = "agent_capsules"
CONTEXT_FILENAME = "context.json"
INSTRUCTIONS_FILENAME = "instructions.md"
RESPONSE_SCHEMA_FILENAME = "response_schema.json"
RETRIEVAL_INDEX_FILENAME = "retrieval_index.json"
MANIFEST_FILENAME = "manifest.json"

MAX_PROMPT_EXCERPT_CHARS = 500
MAX_SUMMARY_ITEMS = 24
MAX_RETRIEVAL_RESULTS = 25

READ_ONLY_RETRIEVAL_SCOPES = (
    "adapter",
    "cgs.actor",
    "cgs.asset",
    "cgs.binding",
    "cgs.component_schema",
    "cgs.metadata",
    "cgs.mode",
    "cgs.rule",
    "cgs.system",
    "diagnostics",
    "project",
    "prompt_history",
    "runtime_status",
    "search",
    "tool_docs",
)

DENIED_RETRIEVAL_SCOPES = (
    "credential",
    "file",
    "gde_commit",
    "project_write",
    "runtime_mutation",
    "shell",
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_:-]{2,}")
_SAFE_PATH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


class ContextCapsuleError(RuntimeError):
    """Raised when a context capsule cannot be built or served safely."""


@dataclass(frozen=True)
class ContextCapsuleRequest:
    """Input used to build one deterministic agent context capsule."""

    xace_session_id: str
    user_prompt: str
    cgs: Mapping[str, Any]
    cgs_hash: str = ""
    project_manifest: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    prompt_history_summaries: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    runtime_status: Mapping[str, Any] = field(default_factory=dict)
    adapter_context: Mapping[str, Any] = field(default_factory=dict)
    allowed_retrieval_scopes: Sequence[str] = READ_ONLY_RETRIEVAL_SCOPES
    schema: str = AGENT_CONTEXT_CAPSULE_SCHEMA

    def __post_init__(self) -> None:
        _require_schema(self.schema)
        _require_identifier(self.xace_session_id, "xace_session_id")
        clean_cgs = _json_object(self.cgs, "cgs")
        metadata = clean_cgs.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        declared_hash = str(metadata.get("cgs_hash") or "")
        resolved_hash = self.cgs_hash or declared_hash
        _require_cgs_hash(resolved_hash, "cgs_hash")
        if declared_hash and declared_hash != resolved_hash:
            raise ContextCapsuleError(
                "cgs_hash must match cgs.metadata.cgs_hash for capsule creation"
            )
        scopes = tuple(sorted({str(scope) for scope in self.allowed_retrieval_scopes}))
        for scope in scopes:
            if scope not in READ_ONLY_RETRIEVAL_SCOPES:
                raise ContextCapsuleError(f"unsupported retrieval scope {scope!r}")
        object.__setattr__(self, "user_prompt", redact_text(self.user_prompt))
        object.__setattr__(self, "cgs", clean_cgs)
        object.__setattr__(self, "cgs_hash", resolved_hash)
        object.__setattr__(
            self,
            "project_manifest",
            _json_object(self.project_manifest, "project_manifest"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_json_object(item, "diagnostic") for item in self.diagnostics),
        )
        object.__setattr__(
            self,
            "prompt_history_summaries",
            tuple(
                _json_object(item, "prompt_history_summary")
                for item in self.prompt_history_summaries
            ),
        )
        object.__setattr__(
            self,
            "runtime_status",
            _json_object(self.runtime_status, "runtime_status"),
        )
        object.__setattr__(
            self,
            "adapter_context",
            _json_object(self.adapter_context, "adapter_context"),
        )
        object.__setattr__(self, "allowed_retrieval_scopes", scopes)

    @property
    def prompt_hash(self) -> str:
        return _sha256_text(self.user_prompt)


@dataclass(frozen=True)
class ContextCapsuleBuildResult:
    """Metadata returned after writing a context capsule directory."""

    capsule_id: str
    capsule_dir: Path
    relative_path: str
    xace_session_id: str
    cgs_hash: str
    prompt_hash: str
    manifest: Mapping[str, Any]
    fingerprint: str
    files: tuple[Mapping[str, Any], ...]
    schema: str = AGENT_CONTEXT_CAPSULE_SCHEMA

    def __post_init__(self) -> None:
        _require_schema(self.schema)
        object.__setattr__(self, "manifest", _json_object(self.manifest, "manifest"))
        object.__setattr__(
            self,
            "files",
            tuple(_json_object(item, "file_record") for item in self.files),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "capsule_id": self.capsule_id,
            "capsule_dir": str(self.capsule_dir),
            "relative_path": self.relative_path,
            "xace_session_id": self.xace_session_id,
            "cgs_hash": self.cgs_hash,
            "prompt_hash": self.prompt_hash,
            "fingerprint": self.fingerprint,
            "files": [dict(item) for item in self.files],
            "manifest": dict(self.manifest),
        }


@dataclass(frozen=True)
class ContextRetrievalRequest:
    """A scoped read-only request for additional agent context."""

    xace_session_id: str
    cgs_hash: str
    scope: str
    item_id: str = ""
    query: str = ""
    provider_id: str = "xace"
    limit: int = 10
    schema: str = AGENT_CONTEXT_RETRIEVAL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_CONTEXT_RETRIEVAL_SCHEMA:
            raise ContextCapsuleError(
                f"schema must equal {AGENT_CONTEXT_RETRIEVAL_SCHEMA!r}"
            )
        _require_identifier(self.xace_session_id, "xace_session_id")
        _require_cgs_hash(self.cgs_hash, "cgs_hash")
        if self.scope not in READ_ONLY_RETRIEVAL_SCOPES and not self.scope:
            raise ContextCapsuleError("scope must not be empty")
        if self.item_id:
            _require_item_id(self.item_id, "item_id")
        _require_identifier(self.provider_id, "provider_id")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise ContextCapsuleError("limit must be an integer")
        if self.limit < 1 or self.limit > MAX_RETRIEVAL_RESULTS:
            raise ContextCapsuleError(
                f"limit must be between 1 and {MAX_RETRIEVAL_RESULTS}"
            )
        object.__setattr__(self, "query", redact_text(self.query))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "xace_session_id": self.xace_session_id,
            "cgs_hash": self.cgs_hash,
            "scope": self.scope,
            "item_id": self.item_id,
            "query": self.query,
            "provider_id": self.provider_id,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class ContextRetrievalResult:
    """Sanitized result returned by a controlled read-only retrieval call."""

    request: ContextRetrievalRequest
    status: str
    data: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    logged: bool = False
    schema: str = AGENT_CONTEXT_RETRIEVAL_SCHEMA

    def __post_init__(self) -> None:
        if self.status not in {"completed", "denied", "not_found"}:
            raise ContextCapsuleError("retrieval status must be completed, denied, or not_found")
        object.__setattr__(self, "data", _json_object(self.data, "retrieval data"))
        object.__setattr__(self, "reason", redact_text(self.reason))

    @property
    def allowed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "status": self.status,
            "reason": self.reason,
            "logged": self.logged,
            "read_only": True,
            "request": self.request.to_dict(),
            "data": dict(self.data),
        }


class AgentContextCapsuleBuilder:
    """Writes deterministic, isolated agent context capsules."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.capsules_root = (
            self.project_root / ".xace" / AGENT_CONTEXT_CAPSULE_DIRNAME
        )

    def build(self, request: ContextCapsuleRequest) -> ContextCapsuleBuildResult:
        if request.schema != AGENT_CONTEXT_CAPSULE_SCHEMA:
            raise ContextCapsuleError("invalid context capsule request")
        capsule_id = _capsule_id(request)
        relative_path = _relative_capsule_path(request)
        capsule_dir = self.project_root / relative_path
        capsule_dir.mkdir(parents=True, exist_ok=True)

        source = ContextRetrievalSource.from_request(request)
        context_payload = _initial_context_payload(request, source, capsule_id)
        response_schema = agent_proposal_response_schema()
        retrieval_index = source.retrieval_index(
            allowed_scopes=request.allowed_retrieval_scopes,
            capsule_id=capsule_id,
        )
        instructions = _instructions_text(request, capsule_id)

        payloads: dict[str, str] = {
            CONTEXT_FILENAME: _canonical_json(context_payload),
            RESPONSE_SCHEMA_FILENAME: _canonical_json(response_schema),
            RETRIEVAL_INDEX_FILENAME: _canonical_json(retrieval_index),
            INSTRUCTIONS_FILENAME: instructions,
        }

        file_records = tuple(
            {
                "path": name,
                "sha256": _sha256_text(payload),
                "bytes": len(payload.encode("utf-8")),
            }
            for name, payload in sorted(payloads.items())
        )
        manifest = _manifest_payload(
            request=request,
            capsule_id=capsule_id,
            relative_path=relative_path,
            files=file_records,
        )
        payloads[MANIFEST_FILENAME] = _canonical_json(manifest)

        for filename, payload in sorted(payloads.items()):
            _write_text(capsule_dir / filename, payload)

        all_records = tuple(
            {
                "path": name,
                "sha256": _sha256_text(payload),
                "bytes": len(payload.encode("utf-8")),
            }
            for name, payload in sorted(payloads.items())
        )
        fingerprint = _sha256_text(
            _canonical_json(
                {
                    "schema": AGENT_CONTEXT_CAPSULE_SCHEMA,
                    "capsule_id": capsule_id,
                    "files": [dict(item) for item in all_records],
                }
            )
        )
        result_manifest = dict(manifest)
        result_manifest["fingerprint"] = fingerprint
        _write_text(capsule_dir / MANIFEST_FILENAME, _canonical_json(result_manifest))
        all_records = tuple(
            {
                "path": name,
                "sha256": _sha256_text(
                    _canonical_json(result_manifest)
                    if name == MANIFEST_FILENAME
                    else payloads[name]
                ),
                "bytes": len(
                    (
                        _canonical_json(result_manifest)
                        if name == MANIFEST_FILENAME
                        else payloads[name]
                    ).encode("utf-8")
                ),
            }
            for name in sorted(payloads)
        )
        return ContextCapsuleBuildResult(
            capsule_id=capsule_id,
            capsule_dir=capsule_dir,
            relative_path=relative_path.as_posix(),
            xace_session_id=request.xace_session_id,
            cgs_hash=request.cgs_hash,
            prompt_hash=request.prompt_hash,
            manifest=result_manifest,
            fingerprint=fingerprint,
            files=all_records,
        )


@dataclass(frozen=True)
class ContextRetrievalSource:
    """Sanitized source data used by progressive context retrieval."""

    cgs: Mapping[str, Any]
    cgs_hash: str
    project_manifest: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    prompt_history_summaries: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    runtime_status: Mapping[str, Any] = field(default_factory=dict)
    adapter_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_cgs_hash(self.cgs_hash, "cgs_hash")
        object.__setattr__(self, "cgs", _json_object(self.cgs, "cgs"))
        object.__setattr__(
            self,
            "project_manifest",
            _json_object(self.project_manifest, "project_manifest"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_json_object(item, "diagnostic") for item in self.diagnostics),
        )
        object.__setattr__(
            self,
            "prompt_history_summaries",
            tuple(
                _json_object(item, "prompt_history_summary")
                for item in self.prompt_history_summaries
            ),
        )
        object.__setattr__(
            self,
            "runtime_status",
            _json_object(self.runtime_status, "runtime_status"),
        )
        object.__setattr__(
            self,
            "adapter_context",
            _json_object(self.adapter_context, "adapter_context"),
        )

    @classmethod
    def from_request(cls, request: ContextCapsuleRequest) -> "ContextRetrievalSource":
        return cls(
            cgs=request.cgs,
            cgs_hash=request.cgs_hash,
            project_manifest=request.project_manifest,
            diagnostics=tuple(request.diagnostics),
            prompt_history_summaries=tuple(request.prompt_history_summaries),
            runtime_status=request.runtime_status,
            adapter_context=request.adapter_context,
        )

    def retrieval_index(
        self,
        *,
        allowed_scopes: Sequence[str],
        capsule_id: str,
    ) -> dict[str, JsonValue]:
        ids = _source_ids(self.cgs)
        return {
            "schema": AGENT_CONTEXT_CAPSULE_SCHEMA,
            "capsule_id": capsule_id,
            "cgs_hash": self.cgs_hash,
            "read_only": True,
            "allowed_scopes": list(sorted(allowed_scopes)),
            "ids": ids,
            "denied_scopes": list(DENIED_RETRIEVAL_SCOPES),
        }


class AgentContextRetriever:
    """Serves controlled progressive read-only context retrieval."""

    def __init__(self, session_store: AgentSessionStore | None = None) -> None:
        self.session_store = session_store

    def retrieve(
        self,
        source: ContextRetrievalSource,
        request: ContextRetrievalRequest,
    ) -> ContextRetrievalResult:
        if request.cgs_hash != source.cgs_hash:
            result = ContextRetrievalResult(
                request=request,
                status="denied",
                reason="request cgs_hash does not match the context source",
                data=_result_payload(source, {}),
            )
            return self._log_and_return(result)
        if request.scope not in READ_ONLY_RETRIEVAL_SCOPES:
            result = ContextRetrievalResult(
                request=request,
                status="denied",
                reason=f"scope {request.scope!r} is not an allowlisted read-only context scope",
                data=_result_payload(source, {}),
            )
            return self._log_and_return(result)

        data = _retrieve_from_source(source, request)
        status = "completed" if data.get("items") or data.get("value") else "not_found"
        result = ContextRetrievalResult(
            request=request,
            status=status,
            data=_result_payload(source, data),
            reason="" if status == "completed" else "no matching context found",
        )
        return self._log_and_return(result)

    def _log_and_return(self, result: ContextRetrievalResult) -> ContextRetrievalResult:
        if self.session_store is None:
            return result
        try:
            self.session_store.record_tool_call(
                AgentToolCallRecord(
                    tool_call_id=_retrieval_tool_call_id(result.request),
                    xace_session_id=result.request.xace_session_id,
                    provider_id=result.request.provider_id,
                    tool_name="xace.retrieve_context",
                    permission="read_only",
                    transport="internal",
                    status=result.status,
                    cgs_hash=result.request.cgs_hash,
                    request=result.request.to_dict(),
                    response=result.to_dict(),
                )
            )
        except AgentSessionStoreError as exc:
            raise ContextCapsuleError(
                f"context retrieval could not be logged: {redact_text(exc)}"
            ) from exc
        return ContextRetrievalResult(
            request=result.request,
            status=result.status,
            data=result.data,
            reason=result.reason,
            logged=True,
        )


def agent_proposal_response_schema() -> dict[str, JsonValue]:
    """Return the required response schema agents must use for mutations."""

    return {
        "schema": AGENT_CONTRACT_SCHEMA,
        "title": "AgentProposalEnvelope",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "proposal_id",
            "session_id",
            "provider_id",
            "base_cgs_hash",
            "intent",
            "summary",
            "operations",
            "required_assets",
            "validation_claims",
            "risk_level",
            "proposal_kind",
            "requires_structural_regeneration",
            "metadata",
        ],
        "properties": {
            "schema": {"const": AGENT_CONTRACT_SCHEMA},
            "proposal_id": {"type": "string"},
            "session_id": {"type": "string"},
            "provider_id": {"type": "string"},
            "base_cgs_hash": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
            "intent": {"type": "string"},
            "summary": {"type": "string"},
            "operations": {"type": "array", "items": {"type": "object"}},
            "required_assets": {"type": "array", "items": {"type": "object"}},
            "validation_claims": {"type": "array", "items": {"type": "object"}},
            "risk_level": {
                "enum": [level.value for level in AgentRiskLevel],
            },
            "proposal_kind": {
                "enum": [kind.value for kind in AgentProposalKind],
            },
            "requires_structural_regeneration": {"type": "boolean"},
            "metadata": {"type": "object"},
        },
    }


def _initial_context_payload(
    request: ContextCapsuleRequest,
    source: ContextRetrievalSource,
    capsule_id: str,
) -> dict[str, JsonValue]:
    relevant = _relevant_cgs_fragments(request.cgs, request.user_prompt)
    return {
        "schema": AGENT_CONTEXT_CAPSULE_SCHEMA,
        "capsule_id": capsule_id,
        "xace_session_id": request.xace_session_id,
        "cgs_hash": request.cgs_hash,
        "prompt": {
            "sha256": request.prompt_hash,
            "redacted_excerpt": request.user_prompt[:MAX_PROMPT_EXCERPT_CHARS],
        },
        "project_summary": _project_summary(source),
        "cgs_fragments": relevant,
        "diagnostics": list(source.diagnostics[:MAX_SUMMARY_ITEMS]),
        "prompt_history_summaries": list(
            source.prompt_history_summaries[:MAX_SUMMARY_ITEMS]
        ),
        "runtime_status": source.runtime_status,
        "tool_docs": _tool_docs(request.allowed_retrieval_scopes),
        "retrieval": {
            "read_only": True,
            "allowed_scopes": list(request.allowed_retrieval_scopes),
            "denied_scopes": list(DENIED_RETRIEVAL_SCOPES),
            "note": (
                "Use xace.retrieve_context for additional scoped read-only "
                "XACE/project/system/world/binding/asset/adapter context."
            ),
        },
        "security_boundary": _security_boundary(),
    }


def _manifest_payload(
    *,
    request: ContextCapsuleRequest,
    capsule_id: str,
    relative_path: Path,
    files: Sequence[Mapping[str, Any]],
) -> dict[str, JsonValue]:
    metadata = request.cgs.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "schema": AGENT_CONTEXT_CAPSULE_SCHEMA,
        "capsule_id": capsule_id,
        "relative_path": relative_path.as_posix(),
        "xace_session_id": request.xace_session_id,
        "cgs_hash": request.cgs_hash,
        "prompt_hash": request.prompt_hash,
        "project": {
            "name": str(metadata.get("name") or ""),
            "version": str(metadata.get("version") or ""),
            "schema_version": str(metadata.get("schema_version") or ""),
        },
        "deterministic_inputs": {
            "cgs_hash": request.cgs_hash,
            "prompt_hash": request.prompt_hash,
            "retrieval_scopes": list(request.allowed_retrieval_scopes),
        },
        "files": [dict(item) for item in files],
        "read_only": True,
    }


def _instructions_text(request: ContextCapsuleRequest, capsule_id: str) -> str:
    lines = [
        "# XACE Agent Context Capsule",
        "",
        f"Capsule ID: `{capsule_id}`",
        f"CGS hash: `{request.cgs_hash}`",
        "",
        "You are operating in Builder Agent Mode from an isolated context capsule.",
        "Treat the real XACE project as read-only unless XACE explicitly approves a typed proposal.",
        "",
        "Required boundary:",
        "",
    ]
    lines.extend(f"- {item}" for item in _security_boundary())
    lines.extend(
        [
            "",
            "All project changes must be returned as `AgentProposalEnvelope` data.",
            "Do not request raw shell access, arbitrary project file writes, credential reads, direct GDE commits, or runtime mutations.",
            "",
            "For more knowledge, call the controlled read-only retrieval tool using one of these scopes:",
            "",
        ]
    )
    lines.extend(f"- `{scope}`" for scope in request.allowed_retrieval_scopes)
    lines.append("")
    return "\n".join(lines)


def _security_boundary() -> tuple[str, ...]:
    return (
        "agent -> XACE tools -> typed proposal -> preview -> user/XACE approval -> GDE -> SGC -> runtime",
        "No raw shell in normal Builder Agent Mode.",
        "No arbitrary writes against the real project.",
        "No direct GDE commit or direct runtime mutation.",
        "No credential access or credential readback.",
    )


def _tool_docs(allowed_scopes: Sequence[str]) -> tuple[dict[str, JsonValue], ...]:
    return (
        {
            "name": "xace.retrieve_context",
            "description": "Retrieve additional scoped read-only XACE context.",
            "permission": "read_only",
            "transport_preference": "mcp",
            "allowed_scopes": list(allowed_scopes),
        },
        {
            "name": "xace.submit_proposal",
            "description": (
                "Submit an AgentProposalEnvelope for preview. Submission is not "
                "authority to mutate the project."
            ),
            "permission": "proposal_write_preview_only",
            "transport_preference": "mcp",
        },
    )


def _project_summary(source: ContextRetrievalSource) -> dict[str, JsonValue]:
    metadata = source.cgs.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    manifest = source.project_manifest
    return {
        "name": str(metadata.get("name") or manifest.get("name") or ""),
        "version": str(metadata.get("version") or manifest.get("version") or ""),
        "schema_version": str(metadata.get("schema_version") or ""),
        "cgs_hash": source.cgs_hash,
        "manifest": _compact_mapping(manifest, ("name", "version", "engine", "engines", "adapters")),
    }


def _relevant_cgs_fragments(
    cgs: Mapping[str, Any],
    user_prompt: str,
) -> dict[str, JsonValue]:
    tokens = _tokens(user_prompt)
    metadata = cgs.get("metadata") if isinstance(cgs.get("metadata"), dict) else {}
    ids = _source_ids(cgs)
    return {
        "metadata": _compact_mapping(
            metadata,
            ("name", "version", "schema_version", "cgs_hash"),
        ),
        "catalog": ids,
        "actors": _select_items(_all_actors(cgs), tokens, limit=8),
        "systems": _select_items(_all_systems(cgs), tokens, limit=12),
        "rules": _select_items(_all_rules(cgs), tokens, limit=8),
        "component_schemas": _component_schema_summaries(cgs),
        "assets": _asset_summaries(cgs, limit=8),
        "semantic_bindings": _binding_summaries(cgs, limit=8),
    }


def _retrieve_from_source(
    source: ContextRetrievalSource,
    request: ContextRetrievalRequest,
) -> dict[str, JsonValue]:
    if request.scope == "project":
        return {"value": _project_summary(source)}
    if request.scope == "cgs.metadata":
        metadata = source.cgs.get("metadata")
        return {"value": metadata if isinstance(metadata, dict) else {}}
    if request.scope == "diagnostics":
        return {"items": list(source.diagnostics[: request.limit])}
    if request.scope == "prompt_history":
        return {"items": list(source.prompt_history_summaries[: request.limit])}
    if request.scope == "runtime_status":
        return {"value": source.runtime_status}
    if request.scope == "adapter":
        return {"value": source.adapter_context}
    if request.scope == "tool_docs":
        return {"items": list(_tool_docs(READ_ONLY_RETRIEVAL_SCOPES))}
    if request.scope == "search":
        return {"items": _search_source(source, request.query, limit=request.limit)}
    if request.scope == "cgs.actor":
        return _retrieve_item(_all_actors(source.cgs), request)
    if request.scope == "cgs.system":
        return _retrieve_item(_all_systems(source.cgs), request)
    if request.scope == "cgs.rule":
        return _retrieve_item(_all_rules(source.cgs), request)
    if request.scope == "cgs.mode":
        return _retrieve_item(_all_modes(source.cgs), request)
    if request.scope == "cgs.component_schema":
        return _retrieve_item(_component_schema_summaries(source.cgs), request)
    if request.scope == "cgs.asset":
        return _retrieve_item(_asset_summaries(source.cgs, limit=MAX_RETRIEVAL_RESULTS), request)
    if request.scope == "cgs.binding":
        return _retrieve_item(_binding_summaries(source.cgs, limit=MAX_RETRIEVAL_RESULTS), request)
    return {}


def _retrieve_item(
    items: Sequence[Mapping[str, Any]],
    request: ContextRetrievalRequest,
) -> dict[str, JsonValue]:
    if request.item_id:
        for item in items:
            if _item_identifier(item) == request.item_id:
                return {"value": dict(item)}
        return {}
    tokens = _tokens(request.query)
    if tokens:
        return {"items": _select_items(items, tokens, limit=request.limit)}
    return {"items": [dict(item) for item in items[: request.limit]]}


def _search_source(
    source: ContextRetrievalSource,
    query: str,
    *,
    limit: int,
) -> list[dict[str, JsonValue]]:
    tokens = _tokens(query)
    if not tokens:
        return []
    candidates: list[dict[str, JsonValue]] = []
    for scope, items in (
        ("cgs.actor", _all_actors(source.cgs)),
        ("cgs.system", _all_systems(source.cgs)),
        ("cgs.rule", _all_rules(source.cgs)),
        ("cgs.asset", _asset_summaries(source.cgs, limit=MAX_RETRIEVAL_RESULTS)),
        ("cgs.binding", _binding_summaries(source.cgs, limit=MAX_RETRIEVAL_RESULTS)),
    ):
        for item in _select_items(items, tokens, limit=limit):
            candidates.append(
                {
                    "scope": scope,
                    "item_id": _item_identifier(item),
                    "item": dict(item),
                    "score": _score_item(item, tokens),
                }
            )
    candidates.sort(key=lambda item: (-int(item["score"]), str(item["scope"]), str(item["item_id"])))
    return candidates[:limit]


def _result_payload(
    source: ContextRetrievalSource,
    data: Mapping[str, Any],
) -> dict[str, JsonValue]:
    payload = {
        "schema": AGENT_CONTEXT_RETRIEVAL_SCHEMA,
        "read_only": True,
        "source_cgs_hash": source.cgs_hash,
        **dict(data),
    }
    return _json_object(payload, "retrieval payload")


def _source_ids(cgs: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {
        "modes": [_item_identifier(item) for item in _all_modes(cgs)],
        "actors": [_item_identifier(item) for item in _all_actors(cgs)],
        "systems": [_item_identifier(item) for item in _all_systems(cgs)],
        "rules": [_item_identifier(item) for item in _all_rules(cgs)],
        "component_schemas": [
            _item_identifier(item) for item in _component_schema_summaries(cgs)
        ],
        "assets": [
            _item_identifier(item)
            for item in _asset_summaries(cgs, limit=MAX_RETRIEVAL_RESULTS)
        ],
        "bindings": [
            _item_identifier(item)
            for item in _binding_summaries(cgs, limit=MAX_RETRIEVAL_RESULTS)
        ],
    }


def _all_modes(cgs: Mapping[str, Any]) -> tuple[dict[str, JsonValue], ...]:
    result: list[dict[str, JsonValue]] = []
    for mode in _as_list(cgs.get("modes")):
        if not isinstance(mode, dict):
            continue
        result.append(
            {
                "id": str(mode.get("id") or ""),
                "is_default": bool(mode.get("is_default", False)),
                "actor_ids": [
                    str(actor.get("id") or "")
                    for actor in _as_list(mode.get("actors"))
                    if isinstance(actor, dict)
                ],
                "system_ids": [
                    str(system.get("id") or "")
                    for system in _as_list(mode.get("systems"))
                    if isinstance(system, dict)
                ],
                "rule_ids": [
                    str(rule.get("id") or "")
                    for rule in _as_list(mode.get("rules"))
                    if isinstance(rule, dict)
                ],
            }
        )
    result.sort(key=lambda item: str(item.get("id") or ""))
    return tuple(result)


def _all_actors(cgs: Mapping[str, Any]) -> tuple[dict[str, JsonValue], ...]:
    actors: list[dict[str, JsonValue]] = []
    for mode in _as_list(cgs.get("modes")):
        if not isinstance(mode, dict):
            continue
        mode_id = str(mode.get("id") or "")
        for actor in _as_list(mode.get("actors")):
            if not isinstance(actor, dict):
                continue
            actors.append(
                {
                    "id": str(actor.get("id") or ""),
                    "mode_id": mode_id,
                    "actor_type": str(actor.get("actor_type") or ""),
                    "control_type": str(actor.get("control_type") or ""),
                    "components": [
                        _component_summary(component)
                        for component in _as_list(actor.get("components"))
                        if isinstance(component, dict)
                    ],
                    "description": str(actor.get("description") or ""),
                }
            )
    actors.sort(key=lambda item: (str(item.get("mode_id") or ""), str(item.get("id") or "")))
    return tuple(actors)


def _all_systems(cgs: Mapping[str, Any]) -> tuple[dict[str, JsonValue], ...]:
    systems: list[dict[str, JsonValue]] = []
    for system in _as_list(cgs.get("global_systems")):
        if isinstance(system, dict):
            systems.append(_system_summary(system, mode_id=""))
    for mode in _as_list(cgs.get("modes")):
        if not isinstance(mode, dict):
            continue
        mode_id = str(mode.get("id") or "")
        for system in _as_list(mode.get("systems")):
            if isinstance(system, dict):
                systems.append(_system_summary(system, mode_id=mode_id))
    systems.sort(key=lambda item: (str(item.get("mode_id") or ""), str(item.get("id") or "")))
    return tuple(systems)


def _all_rules(cgs: Mapping[str, Any]) -> tuple[dict[str, JsonValue], ...]:
    rules: list[dict[str, JsonValue]] = []
    for mode in _as_list(cgs.get("modes")):
        if not isinstance(mode, dict):
            continue
        mode_id = str(mode.get("id") or "")
        for rule in _as_list(mode.get("rules")):
            if not isinstance(rule, dict):
                continue
            rules.append(
                {
                    "id": str(rule.get("id") or ""),
                    "mode_id": mode_id,
                    "condition": str(rule.get("condition") or ""),
                    "effect": str(rule.get("effect") or ""),
                    "priority": int(rule.get("priority") or 0),
                    "is_active": bool(rule.get("is_active", True)),
                }
            )
    rules.sort(key=lambda item: (str(item.get("mode_id") or ""), str(item.get("id") or "")))
    return tuple(rules)


def _system_summary(system: Mapping[str, Any], *, mode_id: str) -> dict[str, JsonValue]:
    return {
        "id": str(system.get("id") or ""),
        "mode_id": mode_id,
        "phase": str(system.get("phase") or ""),
        "reads": _int_list(system.get("reads")),
        "writes": _int_list(system.get("writes")),
        "depends_on": sorted({str(item) for item in _as_list(system.get("depends_on")) if str(item)}),
        "deterministic": bool(system.get("deterministic", True)),
        "description": str(system.get("description") or ""),
    }


def _component_summary(component: Mapping[str, Any]) -> dict[str, JsonValue]:
    defaults = component.get("defaults")
    defaults = defaults if isinstance(defaults, dict) else {}
    return {
        "type_id": int(component.get("type_id") or 0),
        "name": str(component.get("name") or ""),
        "default_keys": sorted(str(key) for key in defaults),
        "defaults": _compact_mapping(defaults, sorted(defaults)[:8]),
    }


def _component_schema_summaries(cgs: Mapping[str, Any]) -> tuple[dict[str, JsonValue], ...]:
    raw = cgs.get("component_schemas")
    components = raw if isinstance(raw, list) else []
    summaries: list[dict[str, JsonValue]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        summaries.append(
            {
                "id": str(component.get("id") or component.get("name") or component.get("type_id") or ""),
                "type_id": int(component.get("type_id") or 0),
                "name": str(component.get("name") or ""),
                "fields": [
                    str(field.get("name") or field)
                    for field in _as_list(component.get("fields"))
                ],
            }
        )
    summaries.sort(key=lambda item: (int(item.get("type_id") or 0), str(item.get("id") or "")))
    return tuple(summaries)


def _asset_summaries(
    cgs: Mapping[str, Any],
    *,
    limit: int,
) -> tuple[dict[str, JsonValue], ...]:
    assets = cgs.get("assets")
    raw_items: list[Any] = []
    if isinstance(assets, list):
        raw_items = list(assets)
    elif isinstance(assets, dict):
        raw_items = _as_list(assets.get("items"))
    metadata = cgs.get("metadata") if isinstance(cgs.get("metadata"), dict) else {}
    metadata_assets = metadata.get("assets")
    if isinstance(metadata_assets, list):
        raw_items.extend(metadata_assets)
    elif isinstance(metadata_assets, dict):
        raw_items.extend(_as_list(metadata_assets.get("items")))
    summaries: list[dict[str, JsonValue]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        summaries.append(
            {
                "id": str(item.get("id") or item.get("name") or item.get("path") or ""),
                "asset_type": str(item.get("asset_type") or item.get("type") or ""),
                "status": str(item.get("status") or ""),
                "path_ref": _safe_reference(item.get("path") or item.get("source_path") or ""),
            }
        )
    summaries.sort(key=lambda item: (str(item.get("asset_type") or ""), str(item.get("id") or "")))
    return tuple(summaries[:limit])


def _binding_summaries(
    cgs: Mapping[str, Any],
    *,
    limit: int,
) -> tuple[dict[str, JsonValue], ...]:
    raw = cgs.get("semantic_bindings")
    entries: list[dict[str, JsonValue]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                entries.append(
                    {
                        "id": str(key),
                        "binding_type": str(value.get("type") or value.get("binding_type") or ""),
                        "target": str(value.get("target") or value.get("asset_id") or ""),
                        "summary": str(value.get("summary") or ""),
                    }
                )
            else:
                entries.append({"id": str(key), "value": str(value)})
    entries.sort(key=lambda item: str(item.get("id") or ""))
    return tuple(entries[:limit])


def _select_items(
    items: Sequence[Mapping[str, Any]],
    tokens: set[str],
    *,
    limit: int,
) -> list[dict[str, JsonValue]]:
    if not tokens:
        return [dict(item) for item in items[:limit]]
    scored = [
        (_score_item(item, tokens), index, item)
        for index, item in enumerate(items)
    ]
    selected = [
        item
        for score, _index, item in sorted(
            scored,
            key=lambda part: (-part[0], part[1], _item_identifier(part[2])),
        )
        if score > 0
    ]
    if not selected:
        selected = list(items[: min(limit, 3)])
    return [dict(item) for item in selected[:limit]]


def _score_item(item: Mapping[str, Any], tokens: set[str]) -> int:
    haystack = _canonical_json(item).lower()
    return sum(1 for token in tokens if token in haystack)


def _tokens(value: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _TOKEN_RE.finditer(redact_text(value))
        if len(match.group(0)) > 1
    }


def _item_identifier(item: Mapping[str, Any]) -> str:
    for key in ("id", "system_id", "actor_id", "rule_id", "name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    value = item.get("type_id")
    return str(value or "")


def _compact_mapping(value: Any, keys: Sequence[str]) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): normalize_json_value(value[key], str(key))
        for key in keys
        if key in value
    }


def _safe_reference(value: Any) -> str:
    text = redact_text(value).replace("\\", "/")
    if not text:
        return ""
    if "://" in text:
        return text
    parts = [part for part in text.split("/") if part and part not in {".", ".."}]
    return "/".join(parts[-3:])


def _int_list(value: Any) -> list[int]:
    items = []
    for item in _as_list(value):
        try:
            items.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(items))


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _capsule_id(request: ContextCapsuleRequest) -> str:
    return f"{request.xace_session_id}:{request.cgs_hash}:{request.prompt_hash[:16]}"


def _relative_capsule_path(request: ContextCapsuleRequest) -> Path:
    return (
        Path(".xace")
        / AGENT_CONTEXT_CAPSULE_DIRNAME
        / request.xace_session_id
        / request.cgs_hash
        / request.prompt_hash[:16]
    )


def _retrieval_tool_call_id(request: ContextRetrievalRequest) -> str:
    return "ctx-" + _sha256_text(_canonical_json(request.to_dict()))[:40]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(value, encoding="utf-8", newline="\n")
    tmp.replace(path)


def _canonical_json(value: Any) -> str:
    redacted = redact_value(normalize_json_value(value))
    return json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: Mapping[str, Any] | None, label: str) -> dict[str, JsonValue]:
    try:
        normalized = normalize_json_value(redact_value(dict(value or {})), label)
    except (AgentContractError, ValueError, TypeError) as exc:
        raise ContextCapsuleError(f"{label} must be a JSON object") from exc
    if not isinstance(normalized, dict):
        raise ContextCapsuleError(f"{label} must be a JSON object")
    return normalized


def _require_schema(schema: str) -> None:
    if schema != AGENT_CONTEXT_CAPSULE_SCHEMA:
        raise ContextCapsuleError(
            f"schema must equal {AGENT_CONTEXT_CAPSULE_SCHEMA!r}"
        )


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_PATH_RE.fullmatch(value):
        raise ContextCapsuleError(
            f"{label} must be a stable identifier; got {value!r}"
        )


def _require_item_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ContextCapsuleError(f"{label} must be a non-empty short string")
    if any(part in value for part in ("..", "/", "\\", "\x00")):
        raise ContextCapsuleError(f"{label} must not be a filesystem path")


def _require_cgs_hash(value: str, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value):
        raise ContextCapsuleError(f"{label} must be a 64-character CGS hash")
