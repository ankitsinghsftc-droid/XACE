"""Composite prompt planning for ordered typed CGS operation batches.

X10-032 keeps provider output inside the existing closed
``xace.typed_cgs_operation_batch.v1`` grammar, then derives a deterministic
planning artifact locally.  The artifact records operation order, dependency
edges, save/network facets, and the rollback contract used by Builder/GDE.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .operation_model import (
    AddComponentOperation,
    AddGeneratedSystemOperation,
    AddSystemOperation,
    DeclareComponentOperation,
    OperationKind,
    SetDefaultsOperation,
    TypedCgsOperationBatch,
    TypedOperationError,
)
from .operation_registry import normalized_typed_operation_batch


COMPOSITE_PROMPT_PLAN_SCHEMA = "xace.composite_prompt_plan.v1"
COMPOSITE_DEPENDENCY_GRAPH_SCHEMA = "xace.composite_prompt_dependency_graph.v1"
COMPOSITE_ROLLBACK_PLAN_SCHEMA = "xace.composite_prompt_rollback_plan.v1"
SAVE_COMPONENT_TYPE_IDS = frozenset({232, 360, 361, 362})
NETWORK_COMPONENT_TYPE_IDS = frozenset({10, 320, 321, 322})
COMPOSITE_REQUIRED_FACETS = ("schema", "system", "asset", "save", "network")


@dataclass(frozen=True)
class CompositePromptPlan:
    """Deterministic plan derived from a typed operation batch."""

    request_id: str
    prompt_id: str
    batch_hash: str
    operation_order: tuple[str, ...]
    dependency_graph: dict[str, Any]
    facet_operations: dict[str, tuple[str, ...]]
    save_plan: dict[str, Any]
    network_plan: dict[str, Any]
    rollback_plan: dict[str, Any]
    warnings: tuple[str, ...] = ()
    schema: str = COMPOSITE_PROMPT_PLAN_SCHEMA

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "prompt_id": self.prompt_id,
            "batch_hash": self.batch_hash,
            "operation_count": len(self.operation_order),
            "operation_order": list(self.operation_order),
            "dependency_graph": copy.deepcopy(self.dependency_graph),
            "facet_operations": {
                key: list(value)
                for key, value in sorted(self.facet_operations.items())
            },
            "save_plan": copy.deepcopy(self.save_plan),
            "network_plan": copy.deepcopy(self.network_plan),
            "rollback_plan": copy.deepcopy(self.rollback_plan),
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload["plan_hash"] = _hash_json(payload)
        return payload

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class CompositePromptPlanValidation:
    valid: bool
    errors: tuple[str, ...] = ()


def build_composite_prompt_plan(
    batch: TypedCgsOperationBatch,
    current_cgs: Mapping[str, Any],
    proposed_cgs: Mapping[str, Any] | None = None,
) -> CompositePromptPlan:
    """Derive a deterministic composite plan from a parsed typed batch."""

    normalized = normalized_typed_operation_batch(batch)
    operations = [
        operation
        for operation in normalized.get("operations", [])
        if isinstance(operation, dict)
    ]
    batch_hash = _hash_json(normalized)
    op_ids = [str(operation.get("operation_id", "")) for operation in operations]
    op_index = {operation_id: index for index, operation_id in enumerate(op_ids)}
    system_to_operation = {
        str(operation.get("system_id", "")): str(operation.get("operation_id", ""))
        for operation in operations
        if operation.get("kind") in {
            OperationKind.ADD_SYSTEM.value,
            OperationKind.ADD_GENERATED_SYSTEM.value,
        }
        and operation.get("system_id")
    }
    declared_components = {
        int(operation.get("component_type_id")): str(operation.get("operation_id", ""))
        for operation in operations
        if operation.get("kind") == OperationKind.DECLARE_COMPONENT.value
        and _is_positive_int(operation.get("component_type_id"))
    }
    attached_components = {
        (
            str(operation.get("mode_id", "")),
            str(operation.get("actor_id", "")),
            int(operation.get("component_type_id")),
        ): str(operation.get("operation_id", ""))
        for operation in operations
        if operation.get("kind") == OperationKind.ADD_COMPONENT.value
        and _is_positive_int(operation.get("component_type_id"))
    }

    facet_ids: dict[str, list[str]] = {
        "schema": [],
        "system": [],
        "event": [],
        "rule": [],
        "asset": [],
        "save": [],
        "network": [],
        "defaults": [],
    }
    nodes: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        operation_id = str(operation.get("operation_id", ""))
        facets = _operation_facets(operation)
        for facet in facets:
            facet_ids.setdefault(facet, []).append(operation_id)
        component_ids = sorted(_operation_component_type_ids(operation))
        nodes.append({
            "id": operation_id,
            "index": index,
            "kind": str(operation.get("kind", "")),
            "facets": list(facets),
            "component_type_ids": component_ids,
            "summary": str(operation.get("explanation", ""))[:160],
        })

    edges: list[dict[str, str]] = []
    for previous, current in zip(op_ids, op_ids[1:]):
        _add_edge(edges, previous, current, "batch_order")

    for operation in operations:
        operation_id = str(operation.get("operation_id", ""))
        kind = operation.get("kind")
        for component_type_id in _operation_component_type_ids(operation):
            declaration_id = declared_components.get(component_type_id)
            if declaration_id and declaration_id != operation_id:
                _add_edge(
                    edges,
                    declaration_id,
                    operation_id,
                    f"component_schema:{component_type_id}",
                )
        if kind == OperationKind.SET_DEFAULTS.value:
            key = (
                str(operation.get("mode_id", "")),
                str(operation.get("actor_id", "")),
                int(operation.get("component_type_id", 0) or 0),
            )
            attach_id = attached_components.get(key)
            if attach_id and attach_id != operation_id:
                _add_edge(edges, attach_id, operation_id, "component_attachment")
        if kind in {
            OperationKind.ADD_SYSTEM.value,
            OperationKind.ADD_GENERATED_SYSTEM.value,
        }:
            for dependency in operation.get("depends_on", []):
                dependency_id = system_to_operation.get(str(dependency))
                if dependency_id and dependency_id != operation_id:
                    _add_edge(edges, dependency_id, operation_id, "system_depends_on")

    topological_order = _topological_order(op_ids, edges, op_index)
    graph = {
        "schema": COMPOSITE_DEPENDENCY_GRAPH_SCHEMA,
        "acyclic": len(topological_order) == len(op_ids),
        "nodes": nodes,
        "edges": edges,
        "topological_order": topological_order,
    }
    warnings = []
    if graph["acyclic"] is not True:
        warnings.append("dependency graph contains a cycle")
    if tuple(topological_order) != tuple(op_ids):
        warnings.append("topological order differs from provider batch order")

    save_plan = _facet_plan(
        facet="save",
        component_type_ids=SAVE_COMPONENT_TYPE_IDS,
        operation_ids=facet_ids.get("save", []),
        operations=operations,
        current_cgs=current_cgs,
        proposed_cgs=proposed_cgs,
    )
    network_plan = _facet_plan(
        facet="network",
        component_type_ids=NETWORK_COMPONENT_TYPE_IDS,
        operation_ids=facet_ids.get("network", []),
        operations=operations,
        current_cgs=current_cgs,
        proposed_cgs=proposed_cgs,
    )
    rollback_plan = {
        "schema": COMPOSITE_ROLLBACK_PLAN_SCHEMA,
        "pre_cgs_hash": _cgs_hash(current_cgs),
        "proposed_cgs_hash": (
            _cgs_hash(proposed_cgs)
            if isinstance(proposed_cgs, Mapping)
            else "computed_after_validation"
        ),
        "atomicity_model": "validate_typed_batch_on_copy_then_single_gde_commit",
        "restore_sequence": [
            "reject_invalid_batch_before_commit",
            "restore_pre_apply_cgs_hash",
            "restore_pre_apply_execution_plan",
            "restore_pending_prompt_preview",
            "reload_runtime_from_pre_apply_version_ids",
        ],
        "rollback_scope": [
            "cgs",
            "sgc_execution_plan",
            "runtime_reload_state",
            "prompt_preview_state",
            "audit_recovery_record",
        ],
        "operation_count": len(op_ids),
    }

    return CompositePromptPlan(
        request_id=batch.request_id,
        prompt_id=batch.prompt_id,
        batch_hash=batch_hash,
        operation_order=tuple(op_ids),
        dependency_graph=graph,
        facet_operations={
            key: tuple(value)
            for key, value in facet_ids.items()
            if value
        },
        save_plan=save_plan,
        network_plan=network_plan,
        rollback_plan=rollback_plan,
        warnings=tuple(warnings),
    )


def validate_composite_prompt_plan(
    plan: CompositePromptPlan | Mapping[str, Any],
    batch: TypedCgsOperationBatch | Mapping[str, Any],
) -> CompositePromptPlanValidation:
    """Validate that a composite plan still matches its typed batch."""

    errors: list[str] = []
    plan_dict = plan.to_dict() if isinstance(plan, CompositePromptPlan) else dict(plan)
    if plan_dict.get("schema") != COMPOSITE_PROMPT_PLAN_SCHEMA:
        errors.append("composite plan schema is not supported")
    expected_hash: str
    expected_order: list[str]
    expected_request_id: str
    expected_prompt_id: str
    if isinstance(batch, TypedCgsOperationBatch):
        normalized = normalized_typed_operation_batch(batch)
        expected_hash = _hash_json(normalized)
        expected_order = [
            str(operation.get("operation_id", ""))
            for operation in normalized.get("operations", [])
            if isinstance(operation, dict)
        ]
        expected_request_id = batch.request_id
        expected_prompt_id = batch.prompt_id
    else:
        normalized = dict(batch)
        expected_hash = _hash_json(normalized)
        raw_ops = normalized.get("operations", [])
        expected_order = [
            str(operation.get("operation_id", ""))
            for operation in raw_ops
            if isinstance(operation, Mapping)
        ]
        expected_request_id = str(normalized.get("request_id", ""))
        expected_prompt_id = str(normalized.get("prompt_id", ""))

    if plan_dict.get("request_id") != expected_request_id:
        errors.append("composite plan request_id does not match batch")
    if plan_dict.get("prompt_id") != expected_prompt_id:
        errors.append("composite plan prompt_id does not match batch")
    if plan_dict.get("batch_hash") != expected_hash:
        errors.append("composite plan batch_hash does not match batch")
    if plan_dict.get("operation_order") != expected_order:
        errors.append("composite plan operation_order does not match batch")
    graph = plan_dict.get("dependency_graph")
    if not isinstance(graph, Mapping):
        errors.append("composite plan dependency_graph must be an object")
    else:
        if graph.get("schema") != COMPOSITE_DEPENDENCY_GRAPH_SCHEMA:
            errors.append("dependency graph schema is not supported")
        if graph.get("acyclic") is not True:
            errors.append("dependency graph must be acyclic")
        if graph.get("topological_order") != expected_order:
            errors.append("dependency graph topological_order does not match batch")
    rollback = plan_dict.get("rollback_plan")
    if not isinstance(rollback, Mapping):
        errors.append("composite plan rollback_plan must be an object")
    elif rollback.get("schema") != COMPOSITE_ROLLBACK_PLAN_SCHEMA:
        errors.append("rollback plan schema is not supported")
    save_plan = plan_dict.get("save_plan")
    network_plan = plan_dict.get("network_plan")
    if not isinstance(save_plan, Mapping):
        errors.append("composite plan save_plan must be an object")
    if not isinstance(network_plan, Mapping):
        errors.append("composite plan network_plan must be an object")
    supplied_hash = plan_dict.get("plan_hash")
    if supplied_hash:
        payload = copy.deepcopy(plan_dict)
        payload.pop("plan_hash", None)
        if supplied_hash != _hash_json(payload):
            errors.append("composite plan_hash does not match canonical payload")
    return CompositePromptPlanValidation(
        valid=not errors,
        errors=tuple(dict.fromkeys(errors)),
    )


def composite_plan_has_required_facets(
    plan: CompositePromptPlan | Mapping[str, Any],
    *,
    min_system_operations: int = 2,
    required_facets: tuple[str, ...] = COMPOSITE_REQUIRED_FACETS,
) -> bool:
    """Return whether the plan satisfies the X10-032 feature-slice floor."""

    plan_dict = plan.to_dict() if isinstance(plan, CompositePromptPlan) else dict(plan)
    facets = plan_dict.get("facet_operations")
    if not isinstance(facets, Mapping):
        return False
    if any(not facets.get(facet) for facet in required_facets):
        return False
    system_ops = facets.get("system")
    return isinstance(system_ops, list) and len(system_ops) >= min_system_operations


def _operation_facets(operation: Mapping[str, Any]) -> tuple[str, ...]:
    kind = str(operation.get("kind", ""))
    facets: list[str] = []
    if kind in {
        OperationKind.DECLARE_COMPONENT.value,
        OperationKind.ADD_COMPONENT.value,
    }:
        facets.append("schema")
    elif kind == OperationKind.SET_DEFAULTS.value:
        facets.append("defaults")
    elif kind in {
        OperationKind.ADD_SYSTEM.value,
        OperationKind.ADD_GENERATED_SYSTEM.value,
    }:
        facets.append("system")
    elif kind == OperationKind.ADD_EVENT.value:
        facets.append("event")
    elif kind == OperationKind.ADD_RULE.value:
        facets.append("rule")
    elif kind == OperationKind.ADD_ASSET.value:
        facets.append("asset")

    component_ids = _operation_component_type_ids(operation)
    if component_ids & SAVE_COMPONENT_TYPE_IDS:
        facets.append("save")
    if component_ids & NETWORK_COMPONENT_TYPE_IDS:
        facets.append("network")
    return tuple(dict.fromkeys(facets))


def _operation_component_type_ids(operation: Mapping[str, Any]) -> set[int]:
    result: set[int] = set()
    for key in ("component_type_id",):
        value = operation.get(key)
        if _is_positive_int(value):
            result.add(int(value))
    for key in ("reads", "writes"):
        values = operation.get(key)
        if isinstance(values, list):
            result.update(int(item) for item in values if _is_positive_int(item))
    behavior = operation.get("behavior")
    if isinstance(behavior, Mapping):
        value = behavior.get("component_type_id")
        if _is_positive_int(value):
            result.add(int(value))
    return result


def _facet_plan(
    *,
    facet: str,
    component_type_ids: frozenset[int],
    operation_ids: list[str],
    operations: list[Mapping[str, Any]],
    current_cgs: Mapping[str, Any],
    proposed_cgs: Mapping[str, Any] | None,
) -> dict[str, Any]:
    touched_components = sorted({
        type_id
        for operation in operations
        for type_id in _operation_component_type_ids(operation)
        if type_id in component_type_ids
    })
    contract_key = "save_contract" if facet == "save" else "network_contract"
    current_contract = _mapping_or_empty(current_cgs.get(contract_key))
    proposed_contract = (
        _mapping_or_empty(proposed_cgs.get(contract_key))
        if isinstance(proposed_cgs, Mapping)
        else {}
    )
    policy: dict[str, Any] = {}
    if facet == "save":
        policy = {
            "strategy": str(
                proposed_contract.get("strategy")
                or current_contract.get("strategy")
                or "component_snapshot"
            ),
            "save_layer": str(
                _assigned_value(operations, component_type_ids, "save_layer")
                or proposed_contract.get("save_layer")
                or current_contract.get("save_layer")
                or "component_state"
            ),
        }
    else:
        policy = {
            "authority": str(
                _assigned_value(operations, component_type_ids, "authority_type")
                or proposed_contract.get("authority")
                or current_contract.get("authority")
                or "Local"
            ),
            "replication_mode": str(
                _assigned_value(operations, component_type_ids, "replication_mode")
                or proposed_contract.get("replication_mode")
                or current_contract.get("replication_mode")
                or "None"
            ),
            "prediction_enabled": bool(
                _assigned_value(operations, component_type_ids, "prediction_enabled")
                if _assigned_value(operations, component_type_ids, "prediction_enabled") is not None
                else proposed_contract.get("prediction_enabled")
                if "prediction_enabled" in proposed_contract
                else current_contract.get("prediction_enabled", False)
            ),
        }
    return {
        "schema": f"xace.composite_prompt_{facet}_plan.v1",
        "operation_ids": list(operation_ids),
        "component_type_ids": touched_components,
        "policy": policy,
        "status": "planned" if operation_ids else "not_touched",
    }


def _assigned_value(
    operations: list[Mapping[str, Any]],
    component_type_ids: frozenset[int],
    field_name: str,
) -> Any:
    for operation in reversed(operations):
        component_id = operation.get("component_type_id")
        if not _is_positive_int(component_id) or int(component_id) not in component_type_ids:
            continue
        assignments = operation.get("assignments")
        if not isinstance(assignments, list):
            assignments = operation.get("defaults")
        if not isinstance(assignments, list):
            continue
        for assignment in assignments:
            if (
                isinstance(assignment, Mapping)
                and assignment.get("field_name") == field_name
            ):
                return copy.deepcopy(assignment.get("value"))
    return None


def _topological_order(
    operation_ids: list[str],
    edges: list[Mapping[str, str]],
    op_index: Mapping[str, int],
) -> list[str]:
    outgoing: dict[str, list[str]] = {operation_id: [] for operation_id in operation_ids}
    incoming_count: dict[str, int] = {operation_id: 0 for operation_id in operation_ids}
    for edge in edges:
        source = str(edge.get("from", ""))
        target = str(edge.get("to", ""))
        if source not in outgoing or target not in incoming_count:
            continue
        if target not in outgoing[source]:
            outgoing[source].append(target)
            incoming_count[target] += 1
    ready = sorted(
        [operation_id for operation_id, count in incoming_count.items() if count == 0],
        key=lambda operation_id: op_index.get(operation_id, 0),
    )
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for target in sorted(outgoing[current], key=lambda item: op_index.get(item, 0)):
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                ready.append(target)
                ready.sort(key=lambda item: op_index.get(item, 0))
    return ordered


def _add_edge(edges: list[dict[str, str]], source: str, target: str, reason: str) -> None:
    if not source or not target or source == target:
        return
    edge = {"from": source, "to": target, "reason": reason}
    if edge not in edges:
        edges.append(edge)


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _cgs_hash(cgs: Mapping[str, Any] | None) -> str:
    if not isinstance(cgs, Mapping):
        return ""
    metadata = cgs.get("metadata")
    if isinstance(metadata, Mapping) and isinstance(metadata.get("cgs_hash"), str):
        value = str(metadata.get("cgs_hash") or "")
        if value:
            return value
    return _hash_json(cgs)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
