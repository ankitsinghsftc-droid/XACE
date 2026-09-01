"""AG-006 preview-only ingress for Agent Mode proposals.

Agents are allowed to propose typed CGS operations. They are not allowed to
commit, write files, run shell commands, mutate the runtime, or bypass the
existing Builder preview/approval/GDE/SGC path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from secret_redaction import redact_exception, redact_text, redact_value

from .contracts import (
    AgentContractError,
    AgentProposalEnvelope,
    AgentProposalKind,
    JsonValue,
    normalize_json_value,
)
from .session_store import AgentSessionStore, AgentSessionStoreError


AGENT_PROPOSAL_INGRESS_SCHEMA = "xace.agent_proposal_ingress.v1"
AGENT_PENDING_PREVIEW_SCHEMA = "xace.agent_pending_preview.v1"
PROMPT_DIFF_PREVIEW_SCHEMA = "xace.prompt_diff_preview.v1"
TYPED_OPERATION_FORMAT = "typed_cgs_v1"

PROPOSAL_STATUS_PREVIEW_CREATED = "preview_created"
PROPOSAL_STATUS_REJECTED = "rejected"
PROPOSAL_STATUS_NO_OP = "no_op"

DENIED_PROPOSAL_AUTHORITY_KEYS = frozenset(
    {
        "allow_credential_access",
        "allow_direct_gde_commit",
        "allow_direct_runtime_mutation",
        "allow_raw_shell",
        "allow_real_project_writes",
        "apply",
        "apply_to_project",
        "commit",
        "commit_directly",
        "credential",
        "direct_commit",
        "direct_gde_commit",
        "direct_runtime_mutation",
        "edit_project_file",
        "gde_commit",
        "raw_shell",
        "runtime_mutate",
        "shell",
        "shell_command",
        "write_file",
    }
)

TYPED_TARGET_KEYS = (
    "mode_id",
    "actor_id",
    "component_type_id",
    "component_name",
    "system_id",
    "event_name",
    "rule_id",
    "asset_id",
)


class AgentProposalIngressError(RuntimeError):
    """Raised when proposal ingress cannot fail closed safely."""


@dataclass(frozen=True)
class AgentProposalIngressResult:
    """Result of admitting or rejecting one agent proposal."""

    status: str
    accepted: bool
    code: str
    message: str
    proposal_id: str = ""
    session_id: str = ""
    provider_id: str = ""
    preview: Mapping[str, Any] = field(default_factory=dict)
    pending_txn: Mapping[str, Any] = field(default_factory=dict)
    proposed_cgs_hash: str = ""
    logged: bool = False
    installed_on_session: bool = False
    schema: str = AGENT_PROPOSAL_INGRESS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_PROPOSAL_INGRESS_SCHEMA:
            raise AgentProposalIngressError(
                f"schema must equal {AGENT_PROPOSAL_INGRESS_SCHEMA!r}"
            )
        if self.status not in {
            PROPOSAL_STATUS_PREVIEW_CREATED,
            PROPOSAL_STATUS_REJECTED,
            PROPOSAL_STATUS_NO_OP,
        }:
            raise AgentProposalIngressError(f"unsupported ingress status {self.status!r}")
        object.__setattr__(self, "message", redact_text(self.message))
        object.__setattr__(self, "preview", _json_object(self.preview, "preview"))
        object.__setattr__(
            self,
            "pending_txn",
            _json_object(self.pending_txn, "pending transaction"),
        )

    @property
    def preview_created(self) -> bool:
        return self.status == PROPOSAL_STATUS_PREVIEW_CREATED and self.accepted

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": self.schema,
            "status": self.status,
            "accepted": self.accepted,
            "code": self.code,
            "message": self.message,
            "proposal_id": self.proposal_id,
            "session_id": self.session_id,
            "provider_id": self.provider_id,
            "preview": dict(self.preview),
            "pending_txn": dict(self.pending_txn),
            "proposed_cgs_hash": self.proposed_cgs_hash,
            "logged": self.logged,
            "installed_on_session": self.installed_on_session,
        }


class AgentProposalIngressGate:
    """Validate AgentProposalEnvelope objects and produce pending previews."""

    def __init__(
        self,
        *,
        session_store: AgentSessionStore | None = None,
        clock: Any = time.time,
        token_factory: Any | None = None,
    ) -> None:
        self.session_store = session_store
        self.clock = clock
        self.token_factory = token_factory or (
            lambda: "apt-" + secrets.token_urlsafe(24)
        )

    def ingest(
        self,
        proposal: AgentProposalEnvelope | Mapping[str, Any],
        *,
        current_cgs: Mapping[str, Any],
        current_cgs_hash: str = "",
        xace_session_id: str = "",
        mode: str = "AGENT",
        session: Any | None = None,
    ) -> AgentProposalIngressResult:
        """Return a no-op, rejection, or preview-only pending transaction.

        The returned transaction is compatible with Builder's existing
        prompt-preview apply path, but this method never applies it.
        """

        clean_cgs = _json_object(current_cgs, "current CGS")
        hash_check = _resolve_current_cgs_hash(clean_cgs, current_cgs_hash)
        if not hash_check["accepted"]:
            return _reject(
                code=str(hash_check["code"]),
                message=str(hash_check["message"]),
            )
        resolved_hash = str(hash_check["cgs_hash"])

        parsed = _parse_proposal(proposal)
        if isinstance(parsed, AgentProposalIngressResult):
            return parsed
        parsed_proposal = parsed
        if xace_session_id and parsed_proposal.session_id != xace_session_id:
            return self._recorded_rejection(
                parsed_proposal,
                code="SESSION_MISMATCH",
                message=(
                    "Agent proposal session_id does not match the active XACE "
                    "session."
                ),
            )
        if parsed_proposal.base_cgs_hash != resolved_hash:
            return self._recorded_rejection(
                parsed_proposal,
                code="STALE_CGS_HASH",
                message=(
                    "Agent proposal was based on a stale CGS hash and must be "
                    "rebased before preview."
                ),
            )
        authority_reason = _denied_authority_reason(parsed_proposal)
        if authority_reason:
            return self._recorded_rejection(
                parsed_proposal,
                code="DIRECT_COMMIT_DENIED",
                message=authority_reason,
            )
        if parsed_proposal.proposal_kind is AgentProposalKind.NO_OP:
            logged = self._record_proposal(parsed_proposal, status="no_op")
            return AgentProposalIngressResult(
                status=PROPOSAL_STATUS_NO_OP,
                accepted=True,
                code="NO_OP",
                message="Agent proposal contains no mutation and no preview was created.",
                proposal_id=parsed_proposal.proposal_id,
                session_id=parsed_proposal.session_id,
                provider_id=parsed_proposal.provider_id,
                logged=logged,
            )

        typed = _parse_and_validate_typed_batch(parsed_proposal, clean_cgs)
        if not typed["accepted"]:
            return self._recorded_rejection(
                parsed_proposal,
                code=str(typed["code"]),
                message=str(typed["message"]),
            )

        normalized_batch = typed["normalized_batch"]
        proposed_cgs = typed["proposed_cgs"]
        assert isinstance(normalized_batch, dict)
        assert isinstance(proposed_cgs, dict)

        pending_txn = _build_pending_transaction(
            proposal=parsed_proposal,
            current_cgs=clean_cgs,
            current_cgs_hash=resolved_hash,
            normalized_batch=normalized_batch,
        )
        preview = _build_prompt_preview(
            proposal=parsed_proposal,
            current_cgs=clean_cgs,
            current_cgs_hash=resolved_hash,
            pending_txn=pending_txn,
            normalized_batch=normalized_batch,
            proposed_cgs=proposed_cgs,
            generated_at=float(self.clock()),
            approval_token=str(self.token_factory()),
            mode=mode,
            session=session,
        )
        logged = self._record_proposal(parsed_proposal, status="pending_preview")
        installed = False
        if session is not None:
            install_agent_proposal_preview(
                session,
                preview=preview,
                pending_txn=pending_txn,
                proposal=parsed_proposal,
            )
            installed = True

        return AgentProposalIngressResult(
            status=PROPOSAL_STATUS_PREVIEW_CREATED,
            accepted=True,
            code="PREVIEW_CREATED",
            message="Agent proposal was admitted as a pending preview only.",
            proposal_id=parsed_proposal.proposal_id,
            session_id=parsed_proposal.session_id,
            provider_id=parsed_proposal.provider_id,
            preview=preview,
            pending_txn=pending_txn,
            proposed_cgs_hash=str(_cgs_hash(proposed_cgs) or ""),
            logged=logged,
            installed_on_session=installed,
        )

    def _recorded_rejection(
        self,
        proposal: AgentProposalEnvelope,
        *,
        code: str,
        message: str,
    ) -> AgentProposalIngressResult:
        logged = self._record_proposal(proposal, status=f"rejected_{code.lower()}")
        return _reject(
            code=code,
            message=message,
            proposal_id=proposal.proposal_id,
            session_id=proposal.session_id,
            provider_id=proposal.provider_id,
            logged=logged,
        )

    def _record_proposal(
        self,
        proposal: AgentProposalEnvelope,
        *,
        status: str,
    ) -> bool:
        if self.session_store is None:
            return False
        try:
            self.session_store.record_proposal(proposal, status=status)
        except AgentSessionStoreError as exc:
            raise AgentProposalIngressError(
                f"agent proposal could not be logged: {redact_exception(exc)}"
            ) from exc
        return True


def install_agent_proposal_preview(
    session: Any,
    *,
    preview: Mapping[str, Any],
    pending_txn: Mapping[str, Any],
    proposal: AgentProposalEnvelope,
) -> None:
    """Install a preview on an in-memory BuilderSession-like object."""

    setattr(session, "pending_txn", copy.deepcopy(dict(pending_txn)))
    setattr(session, "pending_prompt_preview", copy.deepcopy(dict(preview)))
    setattr(
        session,
        "pending_prompt_result",
        {
            "kind": "mutation",
            "intent_category": "AgentProposal",
            "confidence": _proposal_confidence(proposal),
            "mode_profile_warnings": [],
            "transaction": copy.deepcopy(dict(pending_txn)),
            "preview": copy.deepcopy(dict(preview)),
            "approval_required": True,
            "auto_committed": False,
            "source": "agent_proposal",
            "proposal_id": proposal.proposal_id,
            "provider_id": proposal.provider_id,
        },
    )
    if hasattr(session, "pending_prompt_clarification"):
        setattr(session, "pending_prompt_clarification", None)
    if hasattr(session, "pending_clar_id"):
        setattr(session, "pending_clar_id", None)
    touch = getattr(session, "touch", None)
    if callable(touch):
        touch()


def _parse_proposal(
    value: AgentProposalEnvelope | Mapping[str, Any],
) -> AgentProposalEnvelope | AgentProposalIngressResult:
    if isinstance(value, AgentProposalEnvelope):
        return value
    if not isinstance(value, Mapping):
        return _reject(
            code="MALFORMED_PROPOSAL",
            message="Agent proposal must be a JSON object.",
        )
    try:
        return AgentProposalEnvelope.from_dict(value)
    except AgentContractError as exc:
        return _reject(
            code="MALFORMED_PROPOSAL",
            message=f"Agent proposal envelope is invalid: {redact_text(exc)}",
            proposal_id=str(value.get("proposal_id") or ""),
            session_id=str(value.get("session_id") or ""),
            provider_id=str(value.get("provider_id") or ""),
        )


def _parse_and_validate_typed_batch(
    proposal: AgentProposalEnvelope,
    current_cgs: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        typed = _typed_operations()
        batch_payload = {
            "schema": typed.TYPED_OPERATION_BATCH_SCHEMA,
            "request_id": proposal.proposal_id,
            "prompt_id": str(proposal.metadata.get("prompt_id") or proposal.proposal_id),
            "summary": _bounded_summary(proposal.summary),
            "operations": [copy.deepcopy(dict(op)) for op in proposal.operations],
        }
        batch = typed.parse_typed_operation_batch(batch_payload)
        normalized_batch = typed.normalized_typed_operation_batch(batch)
    except Exception as exc:
        return {
            "accepted": False,
            "code": "UNSUPPORTED_OPERATION",
            "message": (
                "Agent proposals must use the closed typed CGS operation "
                f"grammar: {redact_exception(exc)}"
            ),
        }
    try:
        apply_result = typed.apply_typed_operation_batch(batch, current_cgs)
    except Exception as exc:
        return {
            "accepted": False,
            "code": "VALIDATION_FAILED",
            "message": f"Typed CGS proposal validation failed: {redact_exception(exc)}",
        }
    if not getattr(apply_result.validation, "valid", False):
        errors = list(getattr(apply_result.validation, "errors", ()))
        return {
            "accepted": False,
            "code": "VALIDATION_FAILED",
            "message": "Typed CGS proposal is invalid for the current CGS: "
            + "; ".join(redact_text(error) for error in errors[:3]),
        }
    proposed_cgs = getattr(apply_result, "proposed_cgs", None)
    if not isinstance(proposed_cgs, dict):
        return {
            "accepted": False,
            "code": "VALIDATION_FAILED",
            "message": "Typed CGS proposal did not produce a previewable CGS.",
        }
    return {
        "accepted": True,
        "normalized_batch": _json_object(normalized_batch, "normalized typed batch"),
        "proposed_cgs": _json_object(proposed_cgs, "proposed CGS"),
    }


def _build_pending_transaction(
    *,
    proposal: AgentProposalEnvelope,
    current_cgs: Mapping[str, Any],
    current_cgs_hash: str,
    normalized_batch: Mapping[str, Any],
) -> dict[str, JsonValue]:
    operations = normalized_batch.get("operations")
    operation_records = list(operations) if isinstance(operations, list) else []
    operation_kinds = {
        str(operation.get("kind"))
        for operation in operation_records
        if isinstance(operation, dict)
    }
    structural = operation_kinds != {"set_defaults"}
    affected_systems = [
        str(operation.get("system_id"))
        for operation in operation_records
        if (
            isinstance(operation, dict)
            and operation.get("kind") in {"add_system", "add_generated_system"}
            and operation.get("system_id")
        )
    ]
    metadata = current_cgs.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    schema_version = str(metadata.get("schema_version") or metadata.get("version") or "")
    return _json_object(
        {
            "operation_format": TYPED_OPERATION_FORMAT,
            "typed_operation_batch": copy.deepcopy(dict(normalized_batch)),
            "operations": [],
            "schema_delta_type": "structural_add" if structural else "value_mutation",
            "confidence_score": _proposal_confidence(proposal),
            "risk_level": proposal.risk_level.value,
            "required_recompile": True,
            "affected_systems": sorted(set(affected_systems)),
            "mutation_summary": _bounded_summary(proposal.summary),
            "source": "prompt",
            "source_kind": "agent_proposal",
            "agent_proposal": {
                "schema": AGENT_PROPOSAL_INGRESS_SCHEMA,
                "proposal_id": proposal.proposal_id,
                "session_id": proposal.session_id,
                "provider_id": proposal.provider_id,
                "base_cgs_hash": proposal.base_cgs_hash,
            },
            "parent_cgs_hash": current_cgs_hash,
            "cgs_hash": current_cgs_hash,
            "version_ids": {
                "cgs_hash": current_cgs_hash,
                "schema_version": schema_version,
                "execution_plan_version": "unresolved",
                "runtime_world_hash": "unresolved",
                "runtime_tick": None,
                "engine_adapter_sequence": None,
            },
            "authority": _preview_authority_policy(),
        },
        "pending transaction",
    )


def _build_prompt_preview(
    *,
    proposal: AgentProposalEnvelope,
    current_cgs: Mapping[str, Any],
    current_cgs_hash: str,
    pending_txn: Mapping[str, Any],
    normalized_batch: Mapping[str, Any],
    proposed_cgs: Mapping[str, Any],
    generated_at: float,
    approval_token: str,
    mode: str,
    session: Any | None,
) -> dict[str, JsonValue]:
    operations = list(normalized_batch.get("operations") or [])
    transaction_fingerprint = _sha256_json(
        {
            "parent_cgs_hash": current_cgs_hash,
            "operation_format": pending_txn.get("operation_format"),
            "typed_operation_batch": normalized_batch,
            "summary": pending_txn.get("mutation_summary"),
            "schema_delta_type": pending_txn.get("schema_delta_type"),
            "proposal_id": proposal.proposal_id,
        }
    )
    preview_id = f"agent-preview-{transaction_fingerprint[:16]}"
    token_hash = hashlib.sha256(approval_token.encode("utf-8")).hexdigest()
    metadata = current_cgs.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    preview_core = {
        "schema": PROMPT_DIFF_PREVIEW_SCHEMA,
        "preview_id": preview_id,
        "prompt": redact_text(proposal.intent),
        "mode": str(mode or "AGENT"),
        "parent_cgs_hash": current_cgs_hash,
        "schema_version": str(metadata.get("schema_version") or metadata.get("version") or ""),
        "transaction_fingerprint": transaction_fingerprint,
        "mutation_summary": _bounded_summary(proposal.summary),
        "risk_level": proposal.risk_level.value,
        "confidence": _proposal_confidence(proposal),
        "approval_required": True,
        "generated_at": generated_at,
        "direct_commit_allowed": False,
        "preview_only": True,
        "source": "agent_proposal",
        "cgs_diff": {
            "schema": "xace.prompt_diff_preview.cgs.v1",
            "operation_count": len(operations),
            "operations": [
                _preview_typed_operation(operation, index)
                for index, operation in enumerate(operations)
            ],
        },
        "system_diff": _preview_system_diff(pending_txn, operations),
        "asset_diff": _preview_asset_diff(operations),
        "save_diff": _preview_composite_facet_diff(
            pending_txn,
            "save_plan",
            "xace.prompt_diff_preview.save.v1",
        ),
        "network_diff": _preview_composite_facet_diff(
            pending_txn,
            "network_plan",
            "xace.prompt_diff_preview.network.v1",
        ),
        "composite_prompt_plan": copy.deepcopy(
            pending_txn.get("composite_prompt_plan")
            if isinstance(pending_txn.get("composite_prompt_plan"), dict)
            else {}
        ),
        "sgc_diff": {
            "schema": "xace.prompt_diff_preview.sgc.v1",
            "required_recompile": True,
            "status": "required_before_persist",
            "compile_will_run_on_apply": True,
            "affected_systems": list(pending_txn.get("affected_systems", [])),
            "plan_hash_before": "unresolved",
            "plan_hash_after": "computed_on_apply",
        },
        "runtime_diff": _preview_runtime_diff(session),
        "cost_diff": {
            "schema": "xace.prompt_diff_preview.cost.v1",
            "provider": proposal.provider_id,
            "model": str(proposal.metadata.get("model") or ""),
            "observed_cost_cents": 0.0,
            "estimated_apply_cost_cents": 0.0,
            "token_count": 0,
            "source": "agent_proposal_ingress",
        },
        "agent_proposal": {
            "schema": AGENT_PENDING_PREVIEW_SCHEMA,
            "proposal_id": proposal.proposal_id,
            "session_id": proposal.session_id,
            "provider_id": proposal.provider_id,
            "base_cgs_hash": proposal.base_cgs_hash,
            "current_cgs_hash": current_cgs_hash,
            "proposed_cgs_hash": str(_cgs_hash(proposed_cgs) or ""),
            "required_assets": [dict(item) for item in proposal.required_assets],
            "validation_claims": [
                dict(item) for item in proposal.validation_claims
            ],
            "security_route": (
                "agent -> XACE tools -> typed proposal -> preview -> "
                "user/XACE approval -> GDE -> SGC -> runtime"
            ),
            "authority": _preview_authority_policy(),
        },
    }
    preview_core["approval_token"] = approval_token
    preview_core["approval_token_hash"] = token_hash
    return _json_object(preview_core, "prompt preview")


def _preview_typed_operation(operation: Any, index: int) -> dict[str, JsonValue]:
    if not isinstance(operation, Mapping):
        return {
            "index": index,
            "operation_format": TYPED_OPERATION_FORMAT,
            "operation_id": "",
            "kind": "invalid",
            "target": {},
            "explanation": "Invalid typed operation.",
            "typed_details": {},
        }
    return _json_object(
        {
            "index": index,
            "operation_format": TYPED_OPERATION_FORMAT,
            "operation_id": str(operation.get("operation_id", "")),
            "kind": str(operation.get("kind", "")),
            "target": {
                key: operation[key]
                for key in TYPED_TARGET_KEYS
                if key in operation
            },
            "explanation": str(operation.get("explanation", "")),
            "typed_details": {
                key: copy.deepcopy(value)
                for key, value in operation.items()
                if key not in {"operation_id", "kind", "explanation"}
            },
        },
        "typed operation preview",
    )


def _preview_system_diff(
    pending_txn: Mapping[str, Any],
    operations: list[Any],
) -> dict[str, JsonValue]:
    added: list[str] = []
    touched: list[str] = []
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        if operation.get("kind") not in {"add_system", "add_generated_system"}:
            continue
        system_id = str(operation.get("system_id") or "")
        if system_id and system_id not in touched:
            touched.append(system_id)
            added.append(system_id)
    return {
        "schema": "xace.prompt_diff_preview.system.v1",
        "affected_systems": list(pending_txn.get("affected_systems", [])),
        "touched_systems": touched,
        "added_systems": added,
        "removed_systems": [],
        "required_recompile": bool(pending_txn.get("required_recompile", True)),
        "schema_delta_type": str(pending_txn.get("schema_delta_type") or ""),
    }


def _preview_asset_diff(operations: list[Any]) -> dict[str, JsonValue]:
    touched: list[dict[str, JsonValue]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, Mapping):
            continue
        if operation.get("kind") != "add_asset":
            continue
        touched.append(
            {
                "index": index,
                "operation_format": TYPED_OPERATION_FORMAT,
                "operation_id": str(operation.get("operation_id", "")),
                "kind": "add_asset",
                "asset_id": str(operation.get("asset_id", "")),
                "asset_type": str(operation.get("asset_type", "")),
                "status": str(operation.get("status", "")),
            }
        )
    return {
        "schema": "xace.prompt_diff_preview.asset.v1",
        "operation_count": len(touched),
        "operations": touched,
        "status": "changed" if touched else "unchanged",
    }


def _preview_composite_facet_diff(
    pending_txn: Mapping[str, Any],
    plan_key: str,
    schema: str,
) -> dict[str, JsonValue]:
    composite = pending_txn.get("composite_prompt_plan")
    plan = composite.get(plan_key) if isinstance(composite, Mapping) else None
    if not isinstance(plan, Mapping):
        return {
            "schema": schema,
            "status": "unplanned",
            "operation_count": 0,
            "operation_ids": [],
            "component_type_ids": [],
            "policy": {},
        }
    operation_ids = list(plan.get("operation_ids") or [])
    return _json_object(
        {
            "schema": schema,
            "status": str(
                plan.get("status") or ("planned" if operation_ids else "not_touched")
            ),
            "operation_count": len(operation_ids),
            "operation_ids": operation_ids,
            "component_type_ids": list(plan.get("component_type_ids") or []),
            "policy": copy.deepcopy(
                plan.get("policy") if isinstance(plan.get("policy"), Mapping) else {}
            ),
        },
        "composite preview facet",
    )


def _preview_runtime_diff(session: Any | None) -> dict[str, JsonValue]:
    last_tick = getattr(session, "runtime_last_tick", None)
    last_tick = last_tick if isinstance(last_tick, Mapping) else {}
    return {
        "schema": "xace.prompt_diff_preview.runtime.v1",
        "status": "not_run_pre_apply",
        "runtime_connected": bool(getattr(session, "runtime_connected", False)),
        "runtime_adapter_type": str(getattr(session, "runtime_adapter_type", "") or ""),
        "runtime_world_hash_before": str(
            getattr(session, "runtime_last_hash", "") or "unresolved"
        ),
        "runtime_tick_before": last_tick.get("tick"),
        "will_require_runtime_reload": True,
        "runtime_validation": "deferred_until_apply_feedback",
    }


def _resolve_current_cgs_hash(
    current_cgs: Mapping[str, Any],
    current_cgs_hash: str,
) -> dict[str, Any]:
    metadata = current_cgs.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    declared_hash = str(metadata.get("cgs_hash") or "")
    resolved_hash = str(current_cgs_hash or declared_hash)
    if not _is_cgs_hash(resolved_hash):
        return {
            "accepted": False,
            "code": "CURRENT_CGS_HASH_REQUIRED",
            "message": "Current CGS hash is required before previewing an agent proposal.",
        }
    if current_cgs_hash and declared_hash and current_cgs_hash != declared_hash:
        return {
            "accepted": False,
            "code": "CURRENT_CGS_HASH_MISMATCH",
            "message": "Provided current CGS hash does not match cgs.metadata.cgs_hash.",
        }
    return {"accepted": True, "cgs_hash": resolved_hash}


def _denied_authority_reason(proposal: AgentProposalEnvelope) -> str:
    denied = sorted(
        key for key in proposal.metadata.keys()
        if str(key).lower() in DENIED_PROPOSAL_AUTHORITY_KEYS
    )
    if denied:
        return (
            "Agent proposal requested authority outside Builder Agent Mode: "
            + ", ".join(denied)
        )
    for index, operation in enumerate(proposal.operations):
        operation_keys = {str(key).lower() for key in operation.keys()}
        overlap = sorted(operation_keys.intersection(DENIED_PROPOSAL_AUTHORITY_KEYS))
        if overlap:
            return (
                f"Agent operation {index} requested denied authority keys: "
                + ", ".join(overlap)
            )
        if "op" in operation_keys or "path" in operation_keys:
            return (
                f"Agent operation {index} uses legacy path/op mutation fields; "
                "Agent Mode proposals must use typed CGS operations."
            )
    return ""


def _preview_authority_policy() -> dict[str, JsonValue]:
    return {
        "allow_raw_shell": False,
        "allow_real_project_writes": False,
        "allow_direct_gde_commit": False,
        "allow_direct_runtime_mutation": False,
        "allow_credential_access": False,
        "requires_preview_approval": True,
        "direct_commit_allowed": False,
    }


def _proposal_confidence(proposal: AgentProposalEnvelope) -> float:
    raw = proposal.metadata.get("confidence", 1.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _bounded_summary(value: str) -> str:
    text = redact_text(value).strip()
    return text[:240] if len(text) > 240 else text


def _cgs_hash(cgs: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(cgs).encode("utf-8")).hexdigest()


def _reject(
    *,
    code: str,
    message: str,
    proposal_id: str = "",
    session_id: str = "",
    provider_id: str = "",
    logged: bool = False,
) -> AgentProposalIngressResult:
    return AgentProposalIngressResult(
        status=PROPOSAL_STATUS_REJECTED,
        accepted=False,
        code=code,
        message=message,
        proposal_id=proposal_id,
        session_id=session_id,
        provider_id=provider_id,
        logged=logged,
    )


def _typed_operations() -> Any:
    try:
        import typed_operations  # type: ignore[import]

        return typed_operations
    except ImportError:
        _install_prompt_intelligence_src()
        import typed_operations  # type: ignore[import]

        return typed_operations


def _install_prompt_intelligence_src() -> None:
    candidate = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
    for _ in range(8):
        pil_src = os.path.join(candidate, "prompt-intelligence", "src")
        if os.path.isdir(pil_src):
            if pil_src not in sys.path:
                sys.path.insert(0, pil_src)
            return
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent


def _canonical_json(value: Any) -> str:
    redacted = redact_value(normalize_json_value(value))
    return json.dumps(
        redacted,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_object(value: Mapping[str, Any] | None, label: str) -> dict[str, JsonValue]:
    try:
        normalized = normalize_json_value(redact_value(dict(value or {})), label)
    except (AgentContractError, TypeError, ValueError) as exc:
        raise AgentProposalIngressError(f"{label} must be a JSON object") from exc
    if not isinstance(normalized, dict):
        raise AgentProposalIngressError(f"{label} must be a JSON object")
    return normalized


def _is_cgs_hash(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in value
    )


__all__ = [
    "AGENT_PENDING_PREVIEW_SCHEMA",
    "AGENT_PROPOSAL_INGRESS_SCHEMA",
    "AgentProposalIngressError",
    "AgentProposalIngressGate",
    "AgentProposalIngressResult",
    "PROPOSAL_STATUS_NO_OP",
    "PROPOSAL_STATUS_PREVIEW_CREATED",
    "PROPOSAL_STATUS_REJECTED",
    "PROMPT_DIFF_PREVIEW_SCHEMA",
    "TYPED_OPERATION_FORMAT",
    "install_agent_proposal_preview",
]

