"""Atomic executor for the closed, path-free prompt CGS operation grammar.

This module is deliberately independent from prompt-intelligence.  The prompt
parser and this GDE trust boundary both validate the wire batch, so callers
cannot bypass the typed grammar by invoking GDE directly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


TYPED_OPERATION_BATCH_SCHEMA = "xace.typed_cgs_operation_batch.v1"
MAX_OPERATIONS_PER_BATCH = 128
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_COMPONENT_NAME = re.compile(r"^COMP_[A-Z][A-Z0-9_]*_V[1-9][0-9]*$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

_FIELD_TYPES = {
    "fixed", "int", "uint", "bool", "string", "entity_id",
    "string_list", "int_list", "object",
}
_PHASES = {
    "Initialization", "Input", "Simulation", "PostSimulation", "Cleanup",
}
_ASSET_TYPES = {
    "MESH", "TEXTURE", "MATERIAL", "ANIMATION_CONTROLLER",
    "ANIMATION_CLIP", "AUDIO_CLIP", "AUDIO_MUSIC", "SPRITE", "PARTICLE",
    "PREFAB", "FONT",
}
_ASSET_STATUSES = {"PLACEHOLDER", "LINKED", "MISSING"}

GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND = (
    "generated.increment_numeric_field"
)
GENERATED_SYSTEM_ABI_SCHEMA = "xace.generated_system_abi.v1"
GENERATED_SYSTEM_ABI_VERSION = 1
_GENERATED_ROLLBACK_HOOKS = {
    "mutation_hook": "mutation_gate_deferred",
    "event_hook": "event_bus_phase_buffered",
    "rng_hook": "rng_windowed",
}

# Only runtime implementations that exist today may be selected by X10-030.
# X10-031 owns prompt-generated executor definitions and their ABI contracts.
BUILTIN_SYSTEM_CONTRACTS: dict[str, tuple[str, tuple[int, ...], tuple[int, ...]]] = {
    "InputSystem": ("Input", (5, 6), (5,)),
    "MovementIntentSystem": ("Input", (6, 120), (120,)),
    "PlatformerMotionSystem": ("Simulation", (5, 120, 125), (5, 125)),
    "MovementSystem": ("Simulation", (1, 5), (1,)),
    "InteractionSystem": ("Simulation", (1, 2, 6, 260), (6, 260)),
    "InventorySystem": ("Simulation", (1, 6, 201, 205, 260), (1, 201, 205, 260)),
    "AISystem": ("Simulation", (1, 2, 160), (5, 101)),
    "DamageSystem": ("Simulation", (100, 101), (100, 101)),
    "DeathSystem": ("Simulation", (100,), ()),
}

_OPERATION_KEYS: dict[str, tuple[set[str], set[str]]] = {
    "declare_component": (
        {"operation_id", "kind", "explanation", "component_type_id", "component_name", "version", "fields"},
        {"source"},
    ),
    "add_component": (
        {"operation_id", "kind", "explanation", "mode_id", "actor_id", "component_type_id", "component_name"},
        {"defaults", "use_schema_defaults"},
    ),
    "add_system": (
        {"operation_id", "kind", "explanation", "system_id", "phase", "reads", "writes", "depends_on", "implementation_ref"},
        {"scope", "mode_id", "version", "deterministic", "parallel"},
    ),
    "add_generated_system": (
        {
            "operation_id", "kind", "explanation", "system_id", "phase",
            "reads", "writes", "depends_on", "behavior", "runtime_executor",
        },
        {"scope", "mode_id", "version", "deterministic", "parallel"},
    ),
    "add_event": (
        {"operation_id", "kind", "explanation", "event_name", "payload_fields"},
        {"version"},
    ),
    "add_rule": (
        {"operation_id", "kind", "explanation", "mode_id", "rule_id", "condition", "effect", "priority"},
        {"is_active"},
    ),
    "add_asset": (
        {"operation_id", "kind", "explanation", "asset_id", "asset_type", "status"},
        {"source"},
    ),
    "set_defaults": (
        {"operation_id", "kind", "explanation", "mode_id", "actor_id", "component_type_id", "assignments"},
        set(),
    ),
}


class TypedOperationExecutionError(ValueError):
    """A typed batch is invalid for the current CGS and was not applied."""


@dataclass(frozen=True)
class TypedOperationExecutionResult:
    proposed_cgs: dict[str, Any]
    batch_hash: str
    request_id: str
    prompt_id: str
    operation_ids: tuple[str, ...]
    operation_kinds: tuple[str, ...]


class TypedOperationExecutor:
    """Validate and apply all operations to one isolated CGS copy."""

    def execute(
        self,
        batch: Mapping[str, Any],
        current_cgs: Mapping[str, Any],
    ) -> TypedOperationExecutionResult:
        root = _mapping(batch, "typed operation batch")
        _exact_keys(
            root,
            {"schema", "request_id", "prompt_id", "operations", "summary"},
            set(),
            "typed operation batch",
        )
        if root.get("schema") != TYPED_OPERATION_BATCH_SCHEMA:
            raise TypedOperationExecutionError(
                f"schema must equal {TYPED_OPERATION_BATCH_SCHEMA!r}"
            )
        request_id = _identifier(root.get("request_id"), "request_id")
        prompt_id = _identifier(root.get("prompt_id"), "prompt_id")
        summary = _nonempty_string(root.get("summary"), "summary", maximum=240)
        del summary
        operations = _list(root.get("operations"), "operations")
        if not operations or len(operations) > MAX_OPERATIONS_PER_BATCH:
            raise TypedOperationExecutionError(
                f"operations must contain 1..{MAX_OPERATIONS_PER_BATCH} items"
            )
        _json_value(root, "typed operation batch")

        proposed = copy.deepcopy(dict(current_cgs))
        operation_ids: list[str] = []
        operation_kinds: list[str] = []
        for index, raw_value in enumerate(operations):
            raw = _mapping(raw_value, f"operations[{index}]")
            kind = _nonempty_string(raw.get("kind"), f"operations[{index}].kind")
            key_contract = _OPERATION_KEYS.get(kind)
            if key_contract is None:
                raise TypedOperationExecutionError(
                    f"operations[{index}].kind {kind!r} is not registered"
                )
            _exact_keys(raw, key_contract[0], key_contract[1], f"operations[{index}]")
            operation_id = _identifier(
                raw.get("operation_id"), f"operations[{index}].operation_id"
            )
            if operation_id in operation_ids:
                raise TypedOperationExecutionError(
                    f"duplicate operation_id {operation_id!r}"
                )
            _nonempty_string(
                raw.get("explanation"), f"operations[{index}].explanation", maximum=240
            )
            getattr(self, f"_apply_{kind}")(proposed, raw)
            operation_ids.append(operation_id)
            operation_kinds.append(kind)

        canonical = json.dumps(
            root, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return TypedOperationExecutionResult(
            proposed_cgs=proposed,
            batch_hash=hashlib.sha256(canonical).hexdigest(),
            request_id=request_id,
            prompt_id=prompt_id,
            operation_ids=tuple(operation_ids),
            operation_kinds=tuple(operation_kinds),
        )

    def _apply_declare_component(self, cgs: dict[str, Any], op: Mapping[str, Any]) -> None:
        type_id = _positive_int(op.get("component_type_id"), "component_type_id")
        if type_id < 10_000:
            raise TypedOperationExecutionError(
                "prompt-declared components must use type IDs >= 10000"
            )
        name = _component_name(op.get("component_name"), "component_name")
        version = _semver(op.get("version"), "component version")
        source = op.get("source", "generated")
        if source != "generated":
            raise TypedOperationExecutionError("declared component source must be 'generated'")
        schemas = _object_list(cgs, "component_schemas")
        for schema in schemas:
            if schema.get("type_id") == type_id or schema.get("name") == name:
                raise TypedOperationExecutionError(
                    f"component {name!r}/{type_id} is already declared"
                )
        raw_fields = _list(op.get("fields"), "fields")
        if not raw_fields:
            raise TypedOperationExecutionError("declared component must contain fields")
        fields: list[dict[str, Any]] = []
        defaults: dict[str, Any] = {}
        for index, raw_field in enumerate(raw_fields):
            field = _mapping(raw_field, f"fields[{index}]")
            _exact_keys(
                field, {"name", "field_type", "default"}, {"description"},
                f"fields[{index}]",
            )
            field_name = _identifier(field.get("name"), f"fields[{index}].name")
            if field_name in defaults:
                raise TypedOperationExecutionError(f"duplicate component field {field_name!r}")
            field_type = _field_type(field.get("field_type"), f"fields[{index}].field_type")
            value = copy.deepcopy(field.get("default"))
            _typed_value(value, field_type, f"fields[{index}].default")
            description = field.get("description", "")
            if not isinstance(description, str):
                raise TypedOperationExecutionError("field description must be a string")
            fields.append({
                "name": field_name,
                "field_type": field_type,
                "default": value,
                "description": description,
            })
            defaults[field_name] = copy.deepcopy(value)
        schemas.append({
            "type_id": type_id,
            "name": name,
            "version": version,
            "fields": fields,
            "defaults": defaults,
            "source": "generated",
        })

    def _apply_add_component(self, cgs: dict[str, Any], op: Mapping[str, Any]) -> None:
        mode = _find_mode(cgs, _identifier(op.get("mode_id"), "mode_id"))
        actor = _find_actor(mode, _identifier(op.get("actor_id"), "actor_id"))
        type_id = _positive_int(op.get("component_type_id"), "component_type_id")
        name = _component_name(op.get("component_name"), "component_name")
        schema = _find_component_schema(cgs, type_id)
        if schema.get("name") != name:
            raise TypedOperationExecutionError(
                f"component name {name!r} does not match type {type_id}"
            )
        components = _object_list(actor, "components")
        if any(component.get("type_id") == type_id for component in components):
            raise TypedOperationExecutionError(
                f"actor {actor.get('id')!r} already has component type {type_id}"
            )
        use_schema_defaults = op.get("use_schema_defaults", True)
        if not isinstance(use_schema_defaults, bool):
            raise TypedOperationExecutionError("use_schema_defaults must be boolean")
        schema_defaults = schema.get("defaults")
        if not isinstance(schema_defaults, dict):
            raise TypedOperationExecutionError(f"component schema {type_id} has invalid defaults")
        defaults = copy.deepcopy(schema_defaults) if use_schema_defaults else {}
        assignments = _parse_assignments(op.get("defaults", []), schema, "defaults")
        defaults.update(assignments)
        if not use_schema_defaults and set(defaults) != set(schema_defaults):
            missing = sorted(set(schema_defaults) - set(defaults))
            raise TypedOperationExecutionError(
                f"explicit component defaults are missing schema fields {missing}"
            )
        components.append({"type_id": type_id, "name": name, "defaults": defaults})

    def _apply_add_system(self, cgs: dict[str, Any], op: Mapping[str, Any]) -> None:
        system_id = _identifier(op.get("system_id"), "system_id")
        implementation_ref = _identifier(op.get("implementation_ref"), "implementation_ref")
        if implementation_ref != f'builtin.{system_id}.v1':
            raise TypedOperationExecutionError(
                "implementation_ref must name the registered system_id"
            )
        contract = BUILTIN_SYSTEM_CONTRACTS.get(system_id)
        if contract is None:
            raise TypedOperationExecutionError(
                f"no registered runtime implementation exists for {implementation_ref!r}; "
                "generated executors are introduced by X10-031"
            )
        phase = op.get("phase")
        if phase not in _PHASES:
            raise TypedOperationExecutionError(f"invalid system phase {phase!r}")
        reads = _sorted_positive_ids(op.get("reads"), "reads")
        writes = _sorted_positive_ids(op.get("writes"), "writes")
        if (phase, tuple(reads), tuple(writes)) != contract:
            raise TypedOperationExecutionError(
                f"system {system_id!r} does not match registered phase/read/write contract"
            )
        declared_ids = {
            schema.get("type_id") for schema in _object_list(cgs, "component_schemas")
        }
        missing_types = sorted(set(reads + writes) - declared_ids)
        if missing_types:
            raise TypedOperationExecutionError(
                f"system {system_id!r} references undeclared component IDs {missing_types}"
            )
        existing_systems = _all_systems(cgs)
        if any(system.get("id") == system_id for system in existing_systems):
            raise TypedOperationExecutionError(f"system {system_id!r} already exists")
        depends_on = _identifier_list(op.get("depends_on"), "depends_on")
        known_system_ids = {system.get("id") for system in existing_systems}
        unknown_dependencies = [item for item in depends_on if item not in known_system_ids]
        if unknown_dependencies:
            raise TypedOperationExecutionError(
                f"system {system_id!r} has unknown or forward dependencies {unknown_dependencies}"
            )
        scope = op.get("scope", "global")
        if scope not in {"global", "mode"}:
            raise TypedOperationExecutionError("system scope must be 'global' or 'mode'")
        mode_id = op.get("mode_id", "")
        if scope == "global" and mode_id:
            raise TypedOperationExecutionError("global system must not set mode_id")
        version = _semver(op.get("version", "1.0.0"), "system version")
        deterministic = op.get("deterministic", True)
        parallel = op.get("parallel", False)
        if deterministic is not True or not isinstance(parallel, bool):
            raise TypedOperationExecutionError(
                "typed authoritative systems require deterministic=true and boolean parallel"
            )
        record = {
            "id": system_id,
            "phase": phase,
            "reads": reads,
            "writes": writes,
            "depends_on": depends_on,
            "deterministic": True,
            "parallel": parallel,
            "version": version,
            "implementation_ref": implementation_ref,
        }
        if scope == "global":
            _object_list(cgs, "global_systems").append(record)
        else:
            mode = _find_mode(cgs, _identifier(mode_id, "mode_id"))
            _object_list(mode, "systems").append(record)

    def _apply_add_generated_system(
        self, cgs: dict[str, Any], op: Mapping[str, Any]
    ) -> None:
        system_id = _identifier(op.get("system_id"), "system_id")
        phase = op.get("phase")
        if phase not in _PHASES:
            raise TypedOperationExecutionError(f"invalid system phase {phase!r}")
        reads = _sorted_positive_ids(op.get("reads"), "reads")
        writes = _sorted_positive_ids(op.get("writes"), "writes")
        if any(type_id > 0xFFFF_FFFF for type_id in reads + writes):
            raise TypedOperationExecutionError(
                "generated system reads and writes must contain positive u32 component IDs"
            )

        declared_ids = {
            schema.get("type_id") for schema in _object_list(cgs, "component_schemas")
        }
        missing_types = sorted(set(reads + writes) - declared_ids)
        if missing_types:
            raise TypedOperationExecutionError(
                f"system {system_id!r} references undeclared component IDs {missing_types}"
            )

        existing_systems = _all_systems(cgs)
        if any(system.get("id") == system_id for system in existing_systems):
            raise TypedOperationExecutionError(f"system {system_id!r} already exists")
        depends_on = _identifier_list(op.get("depends_on"), "depends_on")
        known_system_ids = {system.get("id") for system in existing_systems}
        unknown_dependencies = [
            dependency for dependency in depends_on if dependency not in known_system_ids
        ]
        if unknown_dependencies:
            raise TypedOperationExecutionError(
                f"system {system_id!r} has unknown or forward dependencies "
                f"{unknown_dependencies}"
            )

        scope = op.get("scope", "global")
        if scope not in {"global", "mode"}:
            raise TypedOperationExecutionError("system scope must be 'global' or 'mode'")
        mode_id = op.get("mode_id", "")
        if not isinstance(mode_id, str):
            raise TypedOperationExecutionError("mode_id must be a string")
        if scope == "global" and mode_id:
            raise TypedOperationExecutionError("global system must not set mode_id")
        if scope == "mode" and not mode_id:
            raise TypedOperationExecutionError("mode system must set mode_id")

        version = _semver(op.get("version", "1.0.0"), "system version")
        deterministic = op.get("deterministic", True)
        parallel = op.get("parallel", False)
        if deterministic is not True or not isinstance(parallel, bool):
            raise TypedOperationExecutionError(
                "typed authoritative systems require deterministic=true and boolean parallel"
            )

        behavior = _mapping(op.get("behavior"), "behavior")
        _exact_keys(
            behavior,
            {"kind", "component_type_id", "field", "amount"},
            set(),
            "behavior",
        )
        if behavior.get("kind") != "increment_numeric_field":
            raise TypedOperationExecutionError(
                "behavior.kind must be 'increment_numeric_field'"
            )
        component_type_id = _positive_u32(
            behavior.get("component_type_id"), "behavior.component_type_id"
        )
        field = _top_level_field_name(behavior.get("field"), "behavior.field")
        amount = _fixed_amount(behavior.get("amount"), "behavior.amount")
        if component_type_id not in reads or component_type_id not in writes:
            raise TypedOperationExecutionError(
                "increment behavior component_type_id must appear in both reads and writes"
            )
        schema = _find_component_schema(cgs, component_type_id)
        field_types = _schema_field_types(schema)
        field_type = field_types.get(field)
        if field_type is None:
            raise TypedOperationExecutionError(
                f"increment behavior field {field!r} is not declared on component "
                f"type {component_type_id}"
            )
        if field_type != "fixed":
            raise TypedOperationExecutionError(
                f"increment behavior field {field!r} must have exact type 'fixed'"
            )

        runtime_executor = _mapping(op.get("runtime_executor"), "runtime_executor")
        _exact_keys(
            runtime_executor,
            {"kind", "component_type_id", "field", "amount", "abi", "compile_artifact"},
            set(),
            "runtime_executor",
        )
        if runtime_executor.get("kind") != GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND:
            raise TypedOperationExecutionError(
                "runtime_executor.kind must be 'generated.increment_numeric_field'"
            )
        executor_component_type_id = _positive_u32(
            runtime_executor.get("component_type_id"),
            "runtime_executor.component_type_id",
        )
        executor_field = _top_level_field_name(
            runtime_executor.get("field"), "runtime_executor.field"
        )
        executor_amount = _fixed_amount(
            runtime_executor.get("amount"), "runtime_executor.amount"
        )
        if (
            executor_component_type_id != component_type_id
            or executor_field != field
            or executor_amount != amount
        ):
            raise TypedOperationExecutionError(
                "runtime_executor must exactly match the declared increment behavior"
            )
        _validate_generated_increment_abi(runtime_executor.get("abi"), component_type_id)
        compile_artifact = _mapping(
            runtime_executor.get("compile_artifact"),
            "runtime_executor.compile_artifact",
        )
        if not compile_artifact:
            raise TypedOperationExecutionError(
                "runtime_executor.compile_artifact must contain a signed compile artifact"
            )

        record = {
            "id": system_id,
            "phase": phase,
            "reads": reads,
            "writes": writes,
            "depends_on": depends_on,
            "deterministic": True,
            "parallel": parallel,
            "version": version,
            "source": "generated",
            "description": _nonempty_string(
                op.get("explanation"), "explanation", maximum=240
            ),
            "runtime_executor": copy.deepcopy(dict(runtime_executor)),
        }
        if scope == "global":
            _object_list(cgs, "global_systems").append(record)
        else:
            mode = _find_mode(cgs, _identifier(mode_id, "mode_id"))
            _object_list(mode, "systems").append(record)

    def _apply_add_event(self, cgs: dict[str, Any], op: Mapping[str, Any]) -> None:
        name = _identifier(op.get("event_name"), "event_name")
        events = _object_list(cgs, "semantic_events")
        if any(event.get("name") == name for event in events):
            raise TypedOperationExecutionError(f"event {name!r} already exists")
        version = _semver(op.get("version", "1.0.0"), "event version")
        raw_fields = _list(op.get("payload_fields"), "payload_fields")
        fields: list[dict[str, Any]] = []
        field_names: set[str] = set()
        for index, raw_field in enumerate(raw_fields):
            field = _mapping(raw_field, f"payload_fields[{index}]")
            _exact_keys(
                field, {"name", "field_type"}, {"required"},
                f"payload_fields[{index}]",
            )
            field_name = _identifier(field.get("name"), f"payload_fields[{index}].name")
            if field_name in field_names:
                raise TypedOperationExecutionError(f"duplicate event field {field_name!r}")
            field_names.add(field_name)
            field_type = _field_type(field.get("field_type"), "event field_type")
            required = field.get("required", True)
            if not isinstance(required, bool):
                raise TypedOperationExecutionError("event field required must be boolean")
            fields.append({"name": field_name, "field_type": field_type, "required": required})
        events.append({
            "name": name,
            "version": version,
            "payload_fields": fields,
            "required_payload_keys": [field["name"] for field in fields if field["required"]],
        })

    def _apply_add_rule(self, cgs: dict[str, Any], op: Mapping[str, Any]) -> None:
        mode = _find_mode(cgs, _identifier(op.get("mode_id"), "mode_id"))
        rule_id = _identifier(op.get("rule_id"), "rule_id")
        rules = _object_list(mode, "rules")
        if any(rule.get("id") == rule_id for rule in rules):
            raise TypedOperationExecutionError(f"rule {rule_id!r} already exists")
        priority = op.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise TypedOperationExecutionError("rule priority must be an integer")
        is_active = op.get("is_active", True)
        if not isinstance(is_active, bool):
            raise TypedOperationExecutionError("rule is_active must be boolean")
        rules.append({
            "id": rule_id,
            "condition": _nonempty_string(op.get("condition"), "rule condition"),
            "effect": _nonempty_string(op.get("effect"), "rule effect"),
            "priority": priority,
            "is_active": is_active,
        })

    def _apply_add_asset(self, cgs: dict[str, Any], op: Mapping[str, Any]) -> None:
        asset_id = _identifier(op.get("asset_id"), "asset_id")
        assets = _object_list(cgs, "assets")
        if any(asset.get("id") == asset_id for asset in assets):
            raise TypedOperationExecutionError(f"asset {asset_id!r} already exists")
        asset_type = op.get("asset_type")
        status = op.get("status")
        if asset_type not in _ASSET_TYPES or status not in _ASSET_STATUSES:
            raise TypedOperationExecutionError("invalid asset_type or status")
        source = op.get("source", "")
        if not isinstance(source, str):
            raise TypedOperationExecutionError("asset source must be a string")
        normalized = source.replace("\\", "/")
        if normalized and (
            normalized.startswith("/")
            or re.match(r"^[A-Za-z]:/", normalized)
            or ".." in normalized.split("/")
        ):
            raise TypedOperationExecutionError(
                "asset source must be project-relative and traversal-free"
            )
        if status == "LINKED" and not normalized:
            raise TypedOperationExecutionError("linked asset requires source")
        record = {"id": asset_id, "asset_type": asset_type, "status": status}
        if normalized:
            record["source"] = normalized
        assets.append(record)

    def _apply_set_defaults(self, cgs: dict[str, Any], op: Mapping[str, Any]) -> None:
        mode = _find_mode(cgs, _identifier(op.get("mode_id"), "mode_id"))
        actor = _find_actor(mode, _identifier(op.get("actor_id"), "actor_id"))
        type_id = _positive_int(op.get("component_type_id"), "component_type_id")
        schema = _find_component_schema(cgs, type_id)
        component = next(
            (item for item in _object_list(actor, "components") if item.get("type_id") == type_id),
            None,
        )
        if component is None:
            raise TypedOperationExecutionError(
                f"actor {actor.get('id')!r} has no component type {type_id}"
            )
        assignments = _parse_assignments(op.get("assignments"), schema, "assignments")
        defaults = component.get("defaults")
        if not isinstance(defaults, dict):
            raise TypedOperationExecutionError("actor component defaults must be an object")
        field_types = _schema_field_types(schema)
        for field_name in assignments:
            if field_name not in defaults:
                raise TypedOperationExecutionError(
                    f"actor component default {field_name!r} does not exist"
                )
            _typed_value(
                defaults[field_name],
                field_types[field_name],
                f"actor component default {field_name}",
            )
        defaults.update(assignments)


def _exact_keys(
    value: Mapping[str, Any], required: set[str], optional: set[str], label: str
) -> None:
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    if missing:
        raise TypedOperationExecutionError(f"{label} missing fields {missing}")
    if extra:
        raise TypedOperationExecutionError(f"{label} contains unknown fields {extra}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypedOperationExecutionError(f"{label} must be an object with string keys")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypedOperationExecutionError(f"{label} must be an array")
    return value


def _object_list(container: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = container.setdefault(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise TypedOperationExecutionError(f"CGS {key} must be an array of objects")
    return value


def _nonempty_string(value: Any, label: str, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypedOperationExecutionError(f"{label} must be a non-empty string")
    if maximum is not None and len(value) > maximum:
        raise TypedOperationExecutionError(f"{label} exceeds {maximum} characters")
    return value


def _identifier(value: Any, label: str) -> str:
    text = _nonempty_string(value, label)
    if not _IDENTIFIER.fullmatch(text):
        raise TypedOperationExecutionError(f"{label} is not a valid identifier")
    return text


def _component_name(value: Any, label: str) -> str:
    text = _nonempty_string(value, label)
    if not _COMPONENT_NAME.fullmatch(text):
        raise TypedOperationExecutionError(f"{label} must use COMP_<NAME>_V<N>")
    return text


def _semver(value: Any, label: str) -> str:
    text = _nonempty_string(value, label)
    if not _SEMVER.fullmatch(text):
        raise TypedOperationExecutionError(f"{label} must be MAJOR.MINOR.PATCH")
    return text


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TypedOperationExecutionError(f"{label} must be a positive integer")
    return value


def _positive_u32(value: Any, label: str) -> int:
    parsed = _positive_int(value, label)
    if parsed > 0xFFFF_FFFF:
        raise TypedOperationExecutionError(f"{label} must be a positive u32")
    return parsed


def _fixed_amount(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypedOperationExecutionError(
            f"{label} must be an integer fixed-point whole-unit amount"
        )
    return value


def _top_level_field_name(value: Any, label: str) -> str:
    field = _identifier(value, label)
    if "." in field:
        raise TypedOperationExecutionError(f"{label} must name a top-level field")
    return field


def _validate_generated_increment_abi(value: Any, component_type_id: int) -> None:
    abi = _mapping(value, "runtime_executor.abi")
    _exact_keys(
        abi,
        {"schema", "version", "inputs", "events", "rng", "errors", "rollback"},
        set(),
        "runtime_executor.abi",
    )
    if abi.get("schema") != GENERATED_SYSTEM_ABI_SCHEMA:
        raise TypedOperationExecutionError(
            f"runtime_executor.abi.schema must be {GENERATED_SYSTEM_ABI_SCHEMA!r}"
        )
    version = abi.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != GENERATED_SYSTEM_ABI_VERSION
    ):
        raise TypedOperationExecutionError(
            f"runtime_executor.abi.version must be {GENERATED_SYSTEM_ABI_VERSION}"
        )

    inputs = _mapping(abi.get("inputs"), "runtime_executor.abi.inputs")
    _exact_keys(
        inputs,
        {"query_components", "component_reads", "current_tick"},
        set(),
        "runtime_executor.abi.inputs",
    )
    query_components = _sorted_positive_ids(
        inputs.get("query_components"),
        "runtime_executor.abi.inputs.query_components",
    )
    component_reads = _sorted_positive_ids(
        inputs.get("component_reads"),
        "runtime_executor.abi.inputs.component_reads",
    )
    if (
        query_components != [component_type_id]
        or component_reads != [component_type_id]
        or inputs.get("current_tick") is not False
    ):
        raise TypedOperationExecutionError(
            "runtime_executor.abi.inputs must query and read only the behavior "
            "component without current_tick"
        )

    events = _mapping(abi.get("events"), "runtime_executor.abi.events")
    _exact_keys(events, {"emits"}, set(), "runtime_executor.abi.events")
    emits = _list(events.get("emits"), "runtime_executor.abi.events.emits")
    if emits:
        raise TypedOperationExecutionError(
            "increment runtime_executor.abi.events.emits must be empty"
        )

    rng = _mapping(abi.get("rng"), "runtime_executor.abi.rng")
    _exact_keys(
        rng,
        {"allowed", "max_calls_per_entity"},
        set(),
        "runtime_executor.abi.rng",
    )
    max_calls = rng.get("max_calls_per_entity")
    if (
        rng.get("allowed") is not False
        or isinstance(max_calls, bool)
        or not isinstance(max_calls, int)
        or max_calls != 0
    ):
        raise TypedOperationExecutionError(
            "increment runtime_executor.abi.rng must disable RNG with zero calls"
        )

    errors = _mapping(abi.get("errors"), "runtime_executor.abi.errors")
    _exact_keys(errors, {"policy"}, set(), "runtime_executor.abi.errors")
    if errors.get("policy") != "halt_and_rollback":
        raise TypedOperationExecutionError(
            "runtime_executor.abi.errors.policy must be 'halt_and_rollback'"
        )

    rollback = _mapping(abi.get("rollback"), "runtime_executor.abi.rollback")
    _exact_keys(
        rollback,
        set(_GENERATED_ROLLBACK_HOOKS),
        set(),
        "runtime_executor.abi.rollback",
    )
    if dict(rollback) != _GENERATED_ROLLBACK_HOOKS:
        raise TypedOperationExecutionError(
            "runtime_executor.abi.rollback must declare the required deterministic hooks"
        )


def _field_type(value: Any, label: str) -> str:
    if value not in _FIELD_TYPES:
        raise TypedOperationExecutionError(f"{label} must be one of {sorted(_FIELD_TYPES)}")
    return str(value)


def _identifier_list(value: Any, label: str) -> list[str]:
    items = _list(value, label)
    parsed = [_identifier(item, f"{label}[{index}]") for index, item in enumerate(items)]
    if len(parsed) != len(set(parsed)):
        raise TypedOperationExecutionError(f"{label} must be unique")
    return parsed


def _sorted_positive_ids(value: Any, label: str) -> list[int]:
    items = _list(value, label)
    parsed = [_positive_int(item, f"{label}[{index}]") for index, item in enumerate(items)]
    if parsed != sorted(set(parsed)):
        raise TypedOperationExecutionError(f"{label} must be sorted and unique")
    return parsed


def _json_value(value: Any, label: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_value(item, f"{label}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypedOperationExecutionError(f"{label} keys must be strings")
            _json_value(item, f"{label}.{key}")
        return
    raise TypedOperationExecutionError(
        f"{label} must contain deterministic JSON values without floats"
    )


def _typed_value(value: Any, field_type: str, label: str) -> None:
    _json_value(value, label)
    if field_type in {"fixed", "int"}:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif field_type in {"uint", "entity_id"}:
        valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    elif field_type == "bool":
        valid = isinstance(value, bool)
    elif field_type == "string":
        valid = isinstance(value, str)
    elif field_type == "string_list":
        valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif field_type == "int_list":
        valid = isinstance(value, list) and all(
            isinstance(item, int) and not isinstance(item, bool) for item in value
        )
    else:
        valid = isinstance(value, dict)
    if not valid:
        raise TypedOperationExecutionError(f"{label} does not match type {field_type!r}")


def _find_mode(cgs: dict[str, Any], mode_id: str) -> dict[str, Any]:
    for mode in _object_list(cgs, "modes"):
        if mode.get("id") == mode_id:
            return mode
    raise TypedOperationExecutionError(f"mode {mode_id!r} does not exist")


def _find_actor(mode: dict[str, Any], actor_id: str) -> dict[str, Any]:
    for actor in _object_list(mode, "actors"):
        if actor.get("id") == actor_id:
            return actor
    raise TypedOperationExecutionError(
        f"actor {actor_id!r} does not exist in mode {mode.get('id')!r}"
    )


def _find_component_schema(cgs: dict[str, Any], type_id: int) -> dict[str, Any]:
    for schema in _object_list(cgs, "component_schemas"):
        if schema.get("type_id") == type_id:
            return schema
    raise TypedOperationExecutionError(f"component type {type_id} is not declared")


def _all_systems(cgs: dict[str, Any]) -> list[dict[str, Any]]:
    systems = list(_object_list(cgs, "global_systems"))
    for mode in _object_list(cgs, "modes"):
        systems.extend(_object_list(mode, "systems"))
    return systems


def _schema_field_types(schema: Mapping[str, Any]) -> dict[str, str]:
    fields = schema.get("fields")
    if not isinstance(fields, list) or not fields:
        raise TypedOperationExecutionError(
            "component schema requires non-empty exact field type metadata"
        )
    defaults = schema.get("defaults")
    if not isinstance(defaults, dict):
        raise TypedOperationExecutionError("component schema defaults must be an object")
    result: dict[str, str] = {}
    for index, raw in enumerate(fields):
        field = _mapping(raw, f"component schema fields[{index}]")
        name = _identifier(field.get("name"), "component schema field name")
        if name in result:
            raise TypedOperationExecutionError(
                f"duplicate component schema field metadata {name!r}"
            )
        result[name] = _field_type(
            field.get("field_type"), "component schema field_type"
        )
    if set(defaults) != set(result):
        raise TypedOperationExecutionError(
            "component schema defaults and exact field metadata must name the same fields"
        )
    for name, field_type in result.items():
        _typed_value(
            defaults[name],
            field_type,
            f"component schema default {name}",
        )
    return result


def _parse_assignments(
    value: Any, schema: Mapping[str, Any], label: str
) -> dict[str, Any]:
    items = _list(value, label)
    field_types = _schema_field_types(schema)
    result: dict[str, Any] = {}
    for index, raw in enumerate(items):
        assignment = _mapping(raw, f"{label}[{index}]")
        _exact_keys(
            assignment, {"field_name", "field_type", "value"}, set(),
            f"{label}[{index}]",
        )
        field_name = _identifier(assignment.get("field_name"), "field_name")
        if field_name in result:
            raise TypedOperationExecutionError(f"duplicate assignment {field_name!r}")
        expected = field_types.get(field_name)
        if expected is None:
            raise TypedOperationExecutionError(f"unknown component field {field_name!r}")
        declared = _field_type(assignment.get("field_type"), "field_type")
        if declared != expected:
            raise TypedOperationExecutionError(
                f"field {field_name!r} type {declared!r} does not match schema type {expected!r}"
            )
        assignment_value = copy.deepcopy(assignment.get("value"))
        _typed_value(assignment_value, declared, f"assignment {field_name}")
        result[field_name] = assignment_value
    return result
