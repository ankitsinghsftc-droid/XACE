"""CGS-aware validation and trusted local application for typed operations.

Provider output never selects a CGS path in this module. Stable typed IDs are
resolved locally, operation families are applied in schema-safe order, and a
deep-copied proposed CGS is returned only when every semantic check passes.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .operation_model import (
    AddAssetOperation,
    AddComponentOperation,
    AddEventOperation,
    AddGeneratedSystemOperation,
    AddRuleOperation,
    AddSystemOperation,
    DeclareComponentOperation,
    FieldType,
    SetDefaultsOperation,
    SystemScope,
    TypedCgsOperationBatch,
    TypedOperationError,
    require_identifier,
)
from .operation_registry import TypedCgsFragmentPlan, compile_typed_operation_batch


BUILTIN_COMPONENT_NAMES: dict[int, str] = {
    1: "COMP_TRANSFORM_V1",
    2: "COMP_IDENTITY_V1",
    5: "COMP_VELOCITY_V1",
    6: "COMP_INPUT_V1",
    10: "COMP_AUTHORITY_V1",
    100: "COMP_HEALTH_V1",
    101: "COMP_DAMAGE_V1",
    102: "COMP_HITBOX_V1",
    103: "COMP_SHIELD_V1",
    104: "COMP_STATUS_EFFECT_V1",
    120: "COMP_MOVEMENT_INTENT_V1",
    125: "COMP_KINEMATIC_CHARACTER_V1",
    140: "COMP_RIGIDBODY_V1",
    160: "COMP_AI_V1",
    161: "COMP_PATROL_V1",
    200: "COMP_STATS_V1",
    201: "COMP_INVENTORY_V1",
    202: "COMP_ABILITY_V1",
    203: "COMP_PROGRESSION_V1",
    204: "COMP_ECONOMY_V1",
    205: "COMP_ITEM_V1",
    230: "COMP_SPAWNER_V1",
    231: "COMP_TRIGGERZONE_V1",
    232: "COMP_PERSISTENCE_V1",
    234: "COMP_ENVIRONMENT_V1",
    260: "COMP_INTERACTION_V1",
    262: "COMP_PUZZLE_V1",
    263: "COMP_USABLE_V1",
    320: "COMP_REPLICATION_V1",
    321: "COMP_NETWORK_TRANSFORM_V1",
    322: "COMP_PLAYER_SESSION_V1",
    360: "COMP_SAVE_SLOT_V1",
    361: "COMP_CHECKPOINT_V1",
    362: "COMP_PLAYER_PROFILE_V1",
}


# This mirrors the runtime builtin registry. Task 30 does not permit a prompt
# to invent an executable implementation reference.
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


@dataclass(frozen=True)
class TypedOperationValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypedCgsApplyResult:
    fragment_plan: TypedCgsFragmentPlan
    proposed_cgs: dict[str, Any] | None
    validation: TypedOperationValidationResult
    changed_targets: tuple[str, ...]


def validate_typed_operation_batch(
    batch: TypedCgsOperationBatch,
    current_cgs: Mapping[str, Any],
) -> TypedOperationValidationResult:
    """Validate a typed batch against stable IDs in the current CGS."""

    return apply_typed_operation_batch(batch, current_cgs).validation


def apply_typed_operation_batch(
    batch: TypedCgsOperationBatch,
    current_cgs: Mapping[str, Any],
) -> TypedCgsApplyResult:
    """Validate and apply a typed batch to a deep copy of the current CGS.

    Families are applied in the fixed order required for safe references:
    component declarations, actor components, systems, events, rules, assets,
    then default updates. Invalid input never exposes a partially applied CGS.
    """

    plan = compile_typed_operation_batch(batch)
    changed_targets = tuple(operation.operation_id for operation in batch.operations)
    errors: list[str] = []
    if not isinstance(current_cgs, Mapping):
        return _failed(plan, changed_targets, "current CGS must be an object")

    proposed = copy.deepcopy(dict(current_cgs))
    modes = _array(proposed, "modes", "modes", errors, required=True)
    global_systems = _array(
        proposed, "global_systems", "global_systems", errors, required=True
    )
    if modes is None or global_systems is None:
        return _failed_many(plan, changed_targets, errors)

    mode_index = _index_records(modes, "id", "mode", errors)
    actor_index: dict[tuple[str, str], dict[str, Any]] = {}
    for mode_id, mode in mode_index.items():
        actors = _array(mode, "actors", f"mode {mode_id!r}.actors", errors, required=True)
        if actors is None:
            continue
        for actor_id, actor in _index_records(
            actors, "id", f"mode {mode_id!r} actor", errors
        ).items():
            actor_index[(mode_id, actor_id)] = actor

    needs_schemas = any(
        isinstance(operation, DeclareComponentOperation)
        for operation in batch.operations
    )
    component_schemas = _array(
        proposed,
        "component_schemas",
        "component_schemas",
        errors,
        create=needs_schemas,
    )
    if component_schemas is None:
        return _failed_many(plan, changed_targets, errors)

    component_names = dict(BUILTIN_COMPONENT_NAMES)
    component_defaults: dict[int, dict[str, Any]] = {}
    component_schema_records: dict[int, Mapping[str, Any]] = {}
    component_field_types: dict[int, dict[str, FieldType]] = {}
    schema_type_ids: set[int] = set()
    schema_names: set[str] = set()
    for index, schema in enumerate(component_schemas):
        if not isinstance(schema, dict):
            errors.append(f"component_schemas[{index}] must be an object")
            continue
        type_id = schema.get("type_id")
        name = schema.get("name")
        defaults = schema.get("defaults")
        if isinstance(type_id, bool) or not isinstance(type_id, int) or type_id <= 0:
            errors.append(f"component_schemas[{index}].type_id must be positive")
            continue
        if type_id in schema_type_ids:
            errors.append(f"component schema type_id {type_id} is duplicated")
        schema_type_ids.add(type_id)
        if not isinstance(name, str) or not name:
            errors.append(f"component_schemas[{index}].name must be non-empty")
            continue
        if name in schema_names:
            errors.append(f"component schema name {name!r} is duplicated")
        schema_names.add(name)
        registered = component_names.get(type_id)
        if registered is not None and registered != name:
            errors.append(
                f"component type_id {type_id} name {name!r} conflicts with {registered!r}"
            )
        component_names[type_id] = name
        component_schema_records[type_id] = schema
        if not isinstance(defaults, dict):
            errors.append(f"component schema {name!r} defaults must be an object")
        else:
            component_defaults[type_id] = defaults

    actor_components: dict[tuple[str, str, int], dict[str, Any]] = {}
    for (mode_id, actor_id), actor in actor_index.items():
        components = _array(
            actor,
            "components",
            f"actor {actor_id!r}.components",
            errors,
            required=True,
        )
        if components is None:
            continue
        seen: set[int] = set()
        for index, component in enumerate(components):
            if not isinstance(component, dict):
                errors.append(
                    f"actor {actor_id!r}.components[{index}] must be an object"
                )
                continue
            type_id = component.get("type_id")
            name = component.get("name")
            defaults = component.get("defaults")
            if isinstance(type_id, bool) or not isinstance(type_id, int) or type_id <= 0:
                errors.append(
                    f"actor {actor_id!r}.components[{index}].type_id must be positive"
                )
                continue
            if type_id in seen:
                errors.append(
                    f"actor {actor_id!r} has duplicate component type_id {type_id}"
                )
            seen.add(type_id)
            registered = component_names.get(type_id)
            if not isinstance(name, str) or not name:
                errors.append(
                    f"actor {actor_id!r} component {type_id} name must be non-empty"
                )
            elif registered is not None and registered != name:
                errors.append(
                    f"actor {actor_id!r} component {type_id} name {name!r} "
                    f"conflicts with {registered!r}"
                )
            else:
                component_names[type_id] = name
            if not isinstance(defaults, dict):
                errors.append(
                    f"actor {actor_id!r} component {type_id} defaults must be an object"
                )
            actor_components[(mode_id, actor_id, type_id)] = component

    existing_system_ids = _collect_system_ids(
        global_systems, mode_index, errors
    )
    event_names = _existing_ids(
        proposed.get("semantic_events", []), "name", "semantic event", errors
    )
    asset_ids = _existing_ids(
        proposed.get("assets", []), "id", "asset", errors
    )
    rule_ids: set[tuple[str, str]] = set()
    for mode_id, mode in mode_index.items():
        rules = mode.get("rules", [])
        for rule_id in _existing_ids(rules, "id", f"mode {mode_id!r} rule", errors):
            rule_ids.add((mode_id, rule_id))

    # Stage 1: declarations establish schemas before any attachment or system.
    for operation in batch.operations:
        if not isinstance(operation, DeclareComponentOperation):
            continue
        if operation.component_type_id in component_names:
            errors.append(
                f"{operation.operation_id}: component type_id "
                f"{operation.component_type_id} already exists"
            )
            continue
        if operation.component_name in component_names.values():
            errors.append(
                f"{operation.operation_id}: component name "
                f"{operation.component_name!r} already exists"
            )
            continue
        record = copy.deepcopy(operation.component_schema_record())
        component_schemas.append(record)
        component_names[operation.component_type_id] = operation.component_name
        component_defaults[operation.component_type_id] = record["defaults"]
        component_schema_records[operation.component_type_id] = record
        component_field_types[operation.component_type_id] = {
            field.name: field.field_type for field in operation.fields
        }

    # Stage 2: actor attachments resolve mode, actor, schema, and typed defaults.
    for operation in batch.operations:
        if not isinstance(operation, AddComponentOperation):
            continue
        actor = actor_index.get((operation.mode_id, operation.actor_id))
        if actor is None:
            errors.append(
                f"{operation.operation_id}: actor {operation.actor_id!r} does not "
                f"exist in mode {operation.mode_id!r}"
            )
            continue
        target = (
            operation.mode_id,
            operation.actor_id,
            operation.component_type_id,
        )
        if target in actor_components:
            errors.append(
                f"{operation.operation_id}: actor already has component type_id "
                f"{operation.component_type_id}"
            )
            continue
        registered_name = component_names.get(operation.component_type_id)
        if registered_name is None:
            errors.append(
                f"{operation.operation_id}: component type_id "
                f"{operation.component_type_id} is not declared"
            )
            continue
        if registered_name != operation.component_name:
            errors.append(
                f"{operation.operation_id}: component name "
                f"{operation.component_name!r} conflicts with {registered_name!r}"
            )
            continue
        schema_defaults = component_defaults.get(operation.component_type_id)
        schema_record = component_schema_records.get(operation.component_type_id)
        if schema_record is None or schema_defaults is None:
            errors.append(
                f"{operation.operation_id}: explicit component schema is unavailable "
                f"for component type_id {operation.component_type_id}"
            )
            continue
        field_types = component_field_types.get(operation.component_type_id)
        if field_types is None:
            field_types = _exact_schema_field_types(
                schema_record,
                f"{operation.operation_id}: component schema "
                f"{operation.component_type_id}",
                errors,
            )
            if field_types is None:
                continue
            component_field_types[operation.component_type_id] = field_types
        defaults = copy.deepcopy(schema_defaults) if operation.use_schema_defaults else {}
        defaults = defaults or {}
        valid_defaults = True
        for assignment in operation.defaults:
            if assignment.field_name not in schema_defaults:
                errors.append(
                    f"{operation.operation_id}: default field "
                    f"{assignment.field_name!r} is not declared"
                )
                valid_defaults = False
                continue
            expected_type = field_types.get(assignment.field_name)
            if expected_type is None:
                errors.append(
                    f"{operation.operation_id}: exact type metadata is unavailable for "
                    f"default field {assignment.field_name!r}"
                )
                valid_defaults = False
                continue
            if expected_type is not assignment.field_type:
                errors.append(
                    f"{operation.operation_id}: default field "
                    f"{assignment.field_name!r} type does not match the schema"
                )
                valid_defaults = False
                continue
            if not _compatible_existing_value(
                schema_defaults.get(assignment.field_name), expected_type
            ):
                errors.append(
                    f"{operation.operation_id}: default field "
                    f"{assignment.field_name!r} type conflicts with current schema"
                )
                valid_defaults = False
                continue
            defaults[assignment.field_name] = copy.deepcopy(assignment.value)
        if not valid_defaults:
            continue
        if not operation.use_schema_defaults and set(defaults) != set(schema_defaults):
            missing = sorted(set(schema_defaults) - set(defaults))
            errors.append(
                f"{operation.operation_id}: explicit component defaults are missing "
                f"schema fields {missing}"
            )
            continue
        record = {
            "type_id": operation.component_type_id,
            "name": operation.component_name,
            "defaults": defaults,
        }
        components = actor.setdefault("components", [])
        components.append(record)
        actor_components[target] = record

    # Stage 3: builtin systems bind to registered implementations; generated
    # systems require trusted local materialization and an exact component ABI.
    known_system_ids = set(existing_system_ids)
    for operation in batch.operations:
        if not isinstance(
            operation,
            (AddSystemOperation, AddGeneratedSystemOperation),
        ):
            continue
        if isinstance(operation, AddSystemOperation):
            contract = BUILTIN_SYSTEM_CONTRACTS.get(operation.system_id)
            expected_ref = f"builtin.{operation.system_id}.v1"
            if contract is None or operation.implementation_ref != expected_ref:
                errors.append(
                    f"{operation.operation_id}: unregistered runtime implementation "
                    f"{operation.implementation_ref!r} for system {operation.system_id!r}"
                )
                continue
            expected_phase, expected_reads, expected_writes = contract
            if (
                operation.phase.value != expected_phase
                or operation.reads != expected_reads
                or operation.writes != expected_writes
            ):
                errors.append(
                    f"{operation.operation_id}: system access contract does not match "
                    f"registered {operation.system_id}"
                )
                continue
        if operation.system_id in known_system_ids:
            errors.append(
                f"{operation.operation_id}: system {operation.system_id!r} already exists"
            )
            continue
        missing_components = [
            type_id
            for type_id in operation.reads + operation.writes
            if type_id not in component_names
        ]
        if missing_components:
            errors.append(
                f"{operation.operation_id}: system references undeclared component "
                f"type IDs {sorted(set(missing_components))}"
            )
            continue
        if isinstance(operation, AddGeneratedSystemOperation):
            if operation.runtime_executor is None:
                errors.append(
                    f"{operation.operation_id}: generated system must be locally "
                    "materialized before CGS application"
                )
                continue
            schema_record = component_schema_records.get(
                operation.behavior.component_type_id
            )
            if schema_record is None:
                errors.append(
                    f"{operation.operation_id}: generated behavior component "
                    f"type_id {operation.behavior.component_type_id} has no explicit schema"
                )
                continue
            field_types = component_field_types.get(
                operation.behavior.component_type_id
            )
            if field_types is None:
                field_types = _exact_schema_field_types(
                    schema_record,
                    f"{operation.operation_id}: generated behavior component "
                    f"{operation.behavior.component_type_id}",
                    errors,
                )
                if field_types is None:
                    continue
                component_field_types[
                    operation.behavior.component_type_id
                ] = field_types
            behavior_field_type = field_types.get(operation.behavior.field)
            if behavior_field_type is None:
                errors.append(
                    f"{operation.operation_id}: generated behavior field "
                    f"{operation.behavior.field!r} does not exist"
                )
                continue
            if behavior_field_type is not FieldType.FIXED:
                errors.append(
                    f"{operation.operation_id}: generated increment field "
                    f"{operation.behavior.field!r} must use exact type 'fixed'"
                )
                continue
            if not _validate_generated_increment_abi(operation, errors):
                continue
        missing_dependencies = [
            dependency
            for dependency in operation.depends_on
            if dependency not in known_system_ids
        ]
        if missing_dependencies:
            errors.append(
                f"{operation.operation_id}: system dependencies do not exist: "
                f"{missing_dependencies}"
            )
            continue
        destination: list[Any]
        if operation.scope is SystemScope.GLOBAL:
            destination = global_systems
        else:
            mode = mode_index.get(operation.mode_id)
            if mode is None:
                errors.append(
                    f"{operation.operation_id}: mode {operation.mode_id!r} does not exist"
                )
                continue
            mode_systems = _array(
                mode,
                "systems",
                f"mode {operation.mode_id!r}.systems",
                errors,
                create=True,
            )
            if mode_systems is None:
                continue
            destination = mode_systems
        if isinstance(operation, AddGeneratedSystemOperation):
            destination.append(copy.deepcopy(operation.system_record()))
        else:
            destination.append({
                "id": operation.system_id,
                "phase": operation.phase.value,
                "reads": list(operation.reads),
                "writes": list(operation.writes),
                "depends_on": list(operation.depends_on),
                "deterministic": True,
                "parallel": operation.parallel,
            })
        known_system_ids.add(operation.system_id)

    # Stage 4: semantic events.
    event_operations = [
        operation
        for operation in batch.operations
        if isinstance(operation, AddEventOperation)
    ]
    semantic_events = _array(
        proposed,
        "semantic_events",
        "semantic_events",
        errors,
        create=bool(event_operations),
    )
    if semantic_events is not None:
        for operation in event_operations:
            if operation.event_name in event_names:
                errors.append(
                    f"{operation.operation_id}: semantic event "
                    f"{operation.event_name!r} already exists"
                )
                continue
            semantic_events.append(copy.deepcopy(operation.event_record()))
            event_names.add(operation.event_name)

    # Stage 5: mode rules.
    for operation in batch.operations:
        if not isinstance(operation, AddRuleOperation):
            continue
        mode = mode_index.get(operation.mode_id)
        if mode is None:
            errors.append(
                f"{operation.operation_id}: mode {operation.mode_id!r} does not exist"
            )
            continue
        identity = (operation.mode_id, operation.rule_id)
        if identity in rule_ids:
            errors.append(
                f"{operation.operation_id}: rule {operation.rule_id!r} already exists "
                f"in mode {operation.mode_id!r}"
            )
            continue
        rules = _array(
            mode,
            "rules",
            f"mode {operation.mode_id!r}.rules",
            errors,
            create=True,
        )
        if rules is None:
            continue
        rules.append(copy.deepcopy(operation.rule_record()))
        rule_ids.add(identity)

    # Stage 6: assets.
    asset_operations = [
        operation
        for operation in batch.operations
        if isinstance(operation, AddAssetOperation)
    ]
    assets = _array(
        proposed, "assets", "assets", errors, create=bool(asset_operations)
    )
    if assets is not None:
        for operation in asset_operations:
            if operation.asset_id in asset_ids:
                errors.append(
                    f"{operation.operation_id}: asset {operation.asset_id!r} already exists"
                )
                continue
            assets.append(copy.deepcopy(operation.asset_record()))
            asset_ids.add(operation.asset_id)

    # Stage 7: defaults update only fields already owned by the target component.
    for operation in batch.operations:
        if not isinstance(operation, SetDefaultsOperation):
            continue
        component = actor_components.get(
            (operation.mode_id, operation.actor_id, operation.component_type_id)
        )
        if component is None:
            errors.append(
                f"{operation.operation_id}: target component type_id "
                f"{operation.component_type_id} is not attached to actor "
                f"{operation.actor_id!r} in mode {operation.mode_id!r}"
            )
            continue
        defaults = component.get("defaults")
        if not isinstance(defaults, dict):
            errors.append(
                f"{operation.operation_id}: target component defaults are malformed"
            )
            continue
        schema_record = component_schema_records.get(operation.component_type_id)
        if schema_record is None:
            errors.append(
                f"{operation.operation_id}: explicit component schema is unavailable "
                f"for component type_id {operation.component_type_id}"
            )
            continue
        field_types = component_field_types.get(operation.component_type_id)
        if field_types is None:
            field_types = _exact_schema_field_types(
                schema_record,
                f"{operation.operation_id}: component schema "
                f"{operation.component_type_id}",
                errors,
            )
            if field_types is None:
                continue
            component_field_types[operation.component_type_id] = field_types
        valid_assignments = True
        for assignment in operation.assignments:
            if assignment.field_name not in defaults:
                errors.append(
                    f"{operation.operation_id}: default field "
                    f"{assignment.field_name!r} does not exist"
                )
                valid_assignments = False
                continue
            expected_type = field_types.get(assignment.field_name)
            if expected_type is None:
                errors.append(
                    f"{operation.operation_id}: exact type metadata is unavailable for "
                    f"default field {assignment.field_name!r}"
                )
                valid_assignments = False
                continue
            if expected_type is not assignment.field_type:
                errors.append(
                    f"{operation.operation_id}: default field "
                    f"{assignment.field_name!r} type does not match the schema"
                )
                valid_assignments = False
                continue
            if not _compatible_existing_value(
                defaults[assignment.field_name], expected_type
            ):
                errors.append(
                    f"{operation.operation_id}: default field "
                    f"{assignment.field_name!r} type conflicts with current value"
                )
                valid_assignments = False
        if not valid_assignments:
            continue
        for assignment in operation.assignments:
            defaults[assignment.field_name] = copy.deepcopy(assignment.value)

    if errors:
        return _failed_many(plan, changed_targets, errors)
    return TypedCgsApplyResult(
        fragment_plan=plan,
        proposed_cgs=proposed,
        validation=TypedOperationValidationResult(valid=True),
        changed_targets=changed_targets,
    )


def _validate_generated_increment_abi(
    operation: AddGeneratedSystemOperation,
    errors: list[str],
) -> bool:
    executor = operation.runtime_executor
    if not isinstance(executor, Mapping):
        errors.append(
            f"{operation.operation_id}: runtime_executor must be an object"
        )
        return False
    expected_keys = {
        "kind",
        "component_type_id",
        "field",
        "amount",
        "abi",
        "compile_artifact",
    }
    if set(executor) != expected_keys:
        errors.append(
            f"{operation.operation_id}: materialized runtime_executor fields "
            f"must equal {sorted(expected_keys)}"
        )
        return False
    component_type_id = operation.behavior.component_type_id
    expected_abi = {
        "schema": "xace.generated_system_abi.v1",
        "version": 1,
        "inputs": {
            "query_components": [component_type_id],
            "component_reads": [component_type_id],
            "current_tick": False,
        },
        "events": {"emits": []},
        "rng": {"allowed": False, "max_calls_per_entity": 0},
        "errors": {"policy": "halt_and_rollback"},
        "rollback": {
            "mutation_hook": "mutation_gate_deferred",
            "event_hook": "event_bus_phase_buffered",
            "rng_hook": "rng_windowed",
        },
    }
    if executor.get("abi") != expected_abi:
        errors.append(
            f"{operation.operation_id}: runtime_executor.abi does not match the "
            "deterministic increment/rollback contract"
        )
        return False
    artifact = executor.get("compile_artifact")
    if not isinstance(artifact, Mapping):
        errors.append(
            f"{operation.operation_id}: runtime_executor.compile_artifact must "
            "be a signed local artifact object"
        )
        return False
    if artifact.get("system_id") != operation.system_id:
        errors.append(
            f"{operation.operation_id}: compile artifact system_id does not "
            "match the generated system"
        )
        return False
    return True


def _array(
    owner: dict[str, Any],
    key: str,
    label: str,
    errors: list[str],
    *,
    required: bool = False,
    create: bool = False,
) -> list[Any] | None:
    value = owner.get(key)
    if value is None:
        if create:
            owner[key] = []
            return owner[key]
        if required:
            errors.append(f"{label} must be an array")
            return None
        return []
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return None
    return value


def _index_records(
    records: list[Any],
    id_key: str,
    label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"{label}[{index}] must be an object")
            continue
        identifier = record.get(id_key)
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{label}[{index}].{id_key} must be non-empty")
            continue
        if identifier in result:
            errors.append(f"{label} ID {identifier!r} is duplicated")
            continue
        result[identifier] = record
    return result


def _existing_ids(
    records: Any,
    id_key: str,
    label: str,
    errors: list[str],
) -> set[str]:
    if records is None:
        return set()
    if not isinstance(records, list):
        errors.append(f"{label}s must be an array")
        return set()
    return set(_index_records(records, id_key, label, errors))


def _collect_system_ids(
    global_systems: list[Any],
    modes: dict[str, dict[str, Any]],
    errors: list[str],
) -> set[str]:
    result = _existing_ids(global_systems, "id", "global system", errors)
    for mode_id, mode in modes.items():
        systems = mode.get("systems", [])
        mode_ids = _existing_ids(
            systems, "id", f"mode {mode_id!r} system", errors
        )
        duplicates = result.intersection(mode_ids)
        for system_id in sorted(duplicates):
            errors.append(f"system ID {system_id!r} is duplicated across scopes")
        result.update(mode_ids)
    return result


def _compatible_existing_value(value: Any, field_type: FieldType) -> bool:
    if field_type is FieldType.BOOL:
        return isinstance(value, bool)
    if field_type in {FieldType.FIXED, FieldType.INT}:
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type in {FieldType.UINT, FieldType.ENTITY_ID}:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        )
    if field_type is FieldType.STRING:
        return isinstance(value, str)
    if field_type is FieldType.STRING_LIST:
        return isinstance(value, list) and all(
            isinstance(item, str) for item in value
        )
    if field_type is FieldType.INT_LIST:
        return isinstance(value, list) and all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in value
        )
    if field_type is FieldType.OBJECT:
        return isinstance(value, dict) and _is_deterministic_json_value(value)
    return False


def _exact_schema_field_types(
    schema: Mapping[str, Any],
    label: str,
    errors: list[str],
) -> dict[str, FieldType] | None:
    """Read authoritative field types without inferring ambiguous numerics."""

    fields = schema.get("fields")
    defaults = schema.get("defaults")
    if not isinstance(fields, list) or not fields:
        errors.append(f"{label} requires non-empty exact field type metadata")
        return None
    if not isinstance(defaults, dict):
        errors.append(f"{label} defaults must be an object")
        return None

    result: dict[str, FieldType] = {}
    valid = True
    for index, raw_field in enumerate(fields):
        if not isinstance(raw_field, Mapping):
            errors.append(f"{label}.fields[{index}] must be an object")
            valid = False
            continue
        name = raw_field.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}.fields[{index}].name must be non-empty")
            valid = False
            continue
        try:
            require_identifier(name, f"{label}.fields[{index}].name")
        except TypedOperationError as error:
            errors.append(str(error))
            valid = False
            continue
        if name in result:
            errors.append(f"{label} has duplicate field metadata for {name!r}")
            valid = False
            continue
        try:
            field_type = FieldType(raw_field.get("field_type"))
        except (TypeError, ValueError):
            errors.append(
                f"{label}.fields[{index}].field_type is not registered"
            )
            valid = False
            continue
        result[name] = field_type

    if set(defaults) != set(result):
        errors.append(
            f"{label} defaults and exact field metadata must name the same fields"
        )
        valid = False
    for name, field_type in result.items():
        if name in defaults and not _compatible_existing_value(defaults[name], field_type):
            errors.append(
                f"{label} default {name!r} does not match exact type "
                f"{field_type.value!r}"
            )
            valid = False
    return result if valid else None


def _is_deterministic_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    if isinstance(value, list):
        return all(_is_deterministic_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_deterministic_json_value(item)
            for key, item in value.items()
        )
    return False


def _failed(
    plan: TypedCgsFragmentPlan,
    changed_targets: tuple[str, ...],
    error: str,
) -> TypedCgsApplyResult:
    return _failed_many(plan, changed_targets, [error])


def _failed_many(
    plan: TypedCgsFragmentPlan,
    changed_targets: tuple[str, ...],
    errors: list[str],
) -> TypedCgsApplyResult:
    unique_errors = tuple(dict.fromkeys(errors))
    return TypedCgsApplyResult(
        fragment_plan=plan,
        proposed_cgs=None,
        validation=TypedOperationValidationResult(
            valid=False,
            errors=unique_errors,
        ),
        changed_targets=changed_targets,
    )
