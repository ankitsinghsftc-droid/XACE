"""Strict parser, registry, provider schema, and deterministic fragment plan."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .operation_model import (
    MAX_OPERATIONS_PER_BATCH,
    TYPED_OPERATION_BATCH_SCHEMA,
    AddAssetOperation,
    AddComponentOperation,
    AddEventOperation,
    AddGeneratedSystemOperation,
    AddRuleOperation,
    AddSystemOperation,
    AssetStatus,
    AssetType,
    ComponentField,
    DeclareComponentOperation,
    DefaultAssignment,
    EventPayloadField,
    FieldType,
    GeneratedSystemBehaviorKind,
    IncrementNumericFieldBehavior,
    OperationKind,
    SetDefaultsOperation,
    SystemPhase,
    SystemScope,
    TypedCgsOperation,
    TypedCgsOperationBatch,
    TypedOperationError,
)


Parser = Callable[[Mapping[str, Any]], TypedCgsOperation]


@dataclass(frozen=True)
class OperationDefinition:
    kind: OperationKind
    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    parser: Parser


_COMMON_REQUIRED = frozenset({"operation_id", "kind", "explanation"})


def _definition(
    kind: OperationKind,
    required: set[str],
    optional: set[str],
    parser: Parser,
) -> OperationDefinition:
    return OperationDefinition(
        kind=kind,
        required_fields=_COMMON_REQUIRED | frozenset(required),
        optional_fields=frozenset(optional),
        parser=parser,
    )


OPERATION_REGISTRY: dict[OperationKind, OperationDefinition] = {
    OperationKind.DECLARE_COMPONENT: _definition(
        OperationKind.DECLARE_COMPONENT,
        {"component_type_id", "component_name", "version", "fields"},
        {"source"},
        lambda raw: DeclareComponentOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            component_type_id=_integer(raw, "component_type_id"),
            component_name=_string(raw, "component_name"),
            version=_string(raw, "version"),
            fields=tuple(
                _parse_component_field(item, index)
                for index, item in enumerate(_list(raw, "fields"))
            ),
            source=_string(raw, "source", default="generated"),
        ),
    ),
    OperationKind.ADD_COMPONENT: _definition(
        OperationKind.ADD_COMPONENT,
        {"mode_id", "actor_id", "component_type_id", "component_name"},
        {"defaults", "use_schema_defaults"},
        lambda raw: AddComponentOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            mode_id=_string(raw, "mode_id"),
            actor_id=_string(raw, "actor_id"),
            component_type_id=_integer(raw, "component_type_id"),
            component_name=_string(raw, "component_name"),
            defaults=tuple(
                _parse_default_assignment(item, index)
                for index, item in enumerate(_list(raw, "defaults", default=[]))
            ),
            use_schema_defaults=_boolean(
                raw, "use_schema_defaults", default=True
            ),
        ),
    ),
    OperationKind.ADD_SYSTEM: _definition(
        OperationKind.ADD_SYSTEM,
        {
            "system_id",
            "phase",
            "reads",
            "writes",
            "depends_on",
            "implementation_ref",
        },
        {"scope", "mode_id", "version", "deterministic", "parallel"},
        lambda raw: AddSystemOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            system_id=_string(raw, "system_id"),
            phase=_enum(raw, "phase", SystemPhase),
            reads=tuple(_integer_list(raw, "reads")),
            writes=tuple(_integer_list(raw, "writes")),
            depends_on=tuple(_string_list(raw, "depends_on")),
            implementation_ref=_string(raw, "implementation_ref"),
            scope=_enum(raw, "scope", SystemScope, default=SystemScope.GLOBAL),
            mode_id=_string(raw, "mode_id", default=""),
            version=_string(raw, "version", default="1.0.0"),
            deterministic=_boolean(raw, "deterministic", default=True),
            parallel=_boolean(raw, "parallel", default=False),
        ),
    ),
    OperationKind.ADD_GENERATED_SYSTEM: _definition(
        OperationKind.ADD_GENERATED_SYSTEM,
        {
            "system_id",
            "phase",
            "reads",
            "writes",
            "depends_on",
            "behavior",
        },
        {
            "scope",
            "mode_id",
            "version",
            "deterministic",
            "parallel",
            "runtime_executor",
        },
        lambda raw: AddGeneratedSystemOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            system_id=_string(raw, "system_id"),
            phase=_enum(raw, "phase", SystemPhase),
            reads=tuple(_integer_list(raw, "reads")),
            writes=tuple(_integer_list(raw, "writes")),
            depends_on=tuple(_string_list(raw, "depends_on")),
            behavior=_parse_generated_system_behavior(raw.get("behavior")),
            scope=_enum(raw, "scope", SystemScope, default=SystemScope.GLOBAL),
            mode_id=_string(raw, "mode_id", default=""),
            version=_string(raw, "version", default="1.0.0"),
            deterministic=_boolean(raw, "deterministic", default=True),
            parallel=_boolean(raw, "parallel", default=False),
            runtime_executor=_optional_mapping(raw, "runtime_executor"),
        ),
    ),
    OperationKind.ADD_EVENT: _definition(
        OperationKind.ADD_EVENT,
        {"event_name", "payload_fields"},
        {"version"},
        lambda raw: AddEventOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            event_name=_string(raw, "event_name"),
            payload_fields=tuple(
                _parse_event_payload_field(item, index)
                for index, item in enumerate(_list(raw, "payload_fields"))
            ),
            version=_string(raw, "version", default="1.0.0"),
        ),
    ),
    OperationKind.ADD_RULE: _definition(
        OperationKind.ADD_RULE,
        {"mode_id", "rule_id", "condition", "effect", "priority"},
        {"is_active"},
        lambda raw: AddRuleOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            mode_id=_string(raw, "mode_id"),
            rule_id=_string(raw, "rule_id"),
            condition=_string(raw, "condition"),
            effect=_string(raw, "effect"),
            priority=_integer(raw, "priority"),
            is_active=_boolean(raw, "is_active", default=True),
        ),
    ),
    OperationKind.ADD_ASSET: _definition(
        OperationKind.ADD_ASSET,
        {"asset_id", "asset_type", "status"},
        {"source"},
        lambda raw: AddAssetOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            asset_id=_string(raw, "asset_id"),
            asset_type=_enum(raw, "asset_type", AssetType),
            status=_enum(raw, "status", AssetStatus),
            source=_string(raw, "source", default=""),
        ),
    ),
    OperationKind.SET_DEFAULTS: _definition(
        OperationKind.SET_DEFAULTS,
        {
            "mode_id",
            "actor_id",
            "component_type_id",
            "assignments",
        },
        set(),
        lambda raw: SetDefaultsOperation(
            operation_id=_string(raw, "operation_id"),
            explanation=_string(raw, "explanation"),
            mode_id=_string(raw, "mode_id"),
            actor_id=_string(raw, "actor_id"),
            component_type_id=_integer(raw, "component_type_id"),
            assignments=tuple(
                _parse_default_assignment(item, index)
                for index, item in enumerate(_list(raw, "assignments"))
            ),
        ),
    ),
}


def parse_typed_operation_batch(
    value: str | bytes | Mapping[str, Any],
    *,
    allow_materialized_generated_systems: bool = False,
) -> TypedCgsOperationBatch:
    """Parse provider output without coercion or unknown-key tolerance.

    ``runtime_executor`` is never provider-authored. Trusted local code may
    round-trip an already materialized generated system only by explicitly
    enabling ``allow_materialized_generated_systems``.
    """

    if not isinstance(allow_materialized_generated_systems, bool):
        raise TypedOperationError(
            "allow_materialized_generated_systems must be boolean"
        )

    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TypedOperationError(f"typed operation batch is not UTF-8: {exc}") from exc
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise TypedOperationError(
                f"typed operation batch is not valid JSON: {exc}"
            ) from exc
    else:
        parsed = value

    root = _mapping_value(parsed, "typed operation batch")
    _check_keys(
        root,
        required={"schema", "request_id", "prompt_id", "operations", "summary"},
        optional=set(),
        label="typed operation batch",
    )
    schema = _string(root, "schema")
    if schema != TYPED_OPERATION_BATCH_SCHEMA:
        raise TypedOperationError(
            f"unsupported typed operation batch schema {schema!r}"
        )

    raw_operations = _list(root, "operations")
    operations: list[TypedCgsOperation] = []
    for index, item in enumerate(raw_operations):
        raw = _mapping_value(item, f"operations[{index}]")
        raw_kind = _string(raw, "kind")
        try:
            kind = OperationKind(raw_kind)
        except ValueError as exc:
            raise TypedOperationError(
                f"operations[{index}].kind {raw_kind!r} is not registered"
            ) from exc
        if (
            kind is OperationKind.ADD_GENERATED_SYSTEM
            and "runtime_executor" in raw
            and not allow_materialized_generated_systems
        ):
            raise TypedOperationError(
                f"operations[{index}].runtime_executor is internal-only; "
                "provider output cannot materialize generated systems"
            )
        definition = OPERATION_REGISTRY[kind]
        _check_keys(
            raw,
            required=set(definition.required_fields),
            optional=set(definition.optional_fields),
            label=f"operations[{index}]",
        )
        operations.append(definition.parser(raw))

    return TypedCgsOperationBatch(
        schema=schema,
        request_id=_string(root, "request_id"),
        prompt_id=_string(root, "prompt_id"),
        operations=tuple(operations),
        summary=_string(root, "summary"),
    )


@dataclass(frozen=True)
class TypedCgsFragmentPlan:
    """Deterministic, path-free fragments for the transactional CGS layer.

    The plan is not itself a commit mechanism.  It separates typed provider
    output from the future GDE operation-family extension, and prevents the
    prompt model from selecting arbitrary CGS paths.
    """

    component_schemas: tuple[dict[str, Any], ...] = ()
    actor_components: tuple[
        tuple[str, str, int, str, dict[str, Any], bool], ...
    ] = ()
    global_systems: tuple[dict[str, Any], ...] = ()
    mode_systems: tuple[tuple[str, dict[str, Any]], ...] = ()
    semantic_events: tuple[dict[str, Any], ...] = ()
    mode_rules: tuple[tuple[str, dict[str, Any]], ...] = ()
    assets: tuple[dict[str, Any], ...] = ()
    default_updates: tuple[tuple[str, str, int, str, Any], ...] = ()

    def canonical_json(self) -> str:
        return json.dumps(
            {
                "component_schemas": self.component_schemas,
                "actor_components": self.actor_components,
                "global_systems": self.global_systems,
                "mode_systems": self.mode_systems,
                "semantic_events": self.semantic_events,
                "mode_rules": self.mode_rules,
                "assets": self.assets,
                "default_updates": self.default_updates,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )


def compile_typed_operation_batch(
    batch: TypedCgsOperationBatch,
) -> TypedCgsFragmentPlan:
    """Compile typed operations into deterministic CGS fragments.

    No input operation supplies a CGS path.  Ordering follows the batch and
    all mutable JSON values are copied so caller mutation cannot alter proof
    inputs after compilation.
    """

    component_schemas: list[dict[str, Any]] = []
    actor_components: list[
        tuple[str, str, int, str, dict[str, Any], bool]
    ] = []
    global_systems: list[dict[str, Any]] = []
    mode_systems: list[tuple[str, dict[str, Any]]] = []
    semantic_events: list[dict[str, Any]] = []
    mode_rules: list[tuple[str, dict[str, Any]]] = []
    assets: list[dict[str, Any]] = []
    default_updates: list[tuple[str, str, int, str, Any]] = []

    for operation in batch.operations:
        if isinstance(operation, DeclareComponentOperation):
            component_schemas.append(copy.deepcopy(operation.component_schema_record()))
        elif isinstance(operation, AddComponentOperation):
            actor_components.append(
                (
                    operation.mode_id,
                    operation.actor_id,
                    operation.component_type_id,
                    operation.component_name,
                    {
                        assignment.field_name: copy.deepcopy(assignment.value)
                        for assignment in operation.defaults
                    },
                    operation.use_schema_defaults,
                )
            )
        elif isinstance(
            operation,
            (AddSystemOperation, AddGeneratedSystemOperation),
        ):
            record = copy.deepcopy(operation.system_record())
            if operation.scope is SystemScope.GLOBAL:
                global_systems.append(record)
            else:
                mode_systems.append((operation.mode_id, record))
        elif isinstance(operation, AddEventOperation):
            semantic_events.append(copy.deepcopy(operation.event_record()))
        elif isinstance(operation, AddRuleOperation):
            mode_rules.append(
                (operation.mode_id, copy.deepcopy(operation.rule_record()))
            )
        elif isinstance(operation, AddAssetOperation):
            assets.append(copy.deepcopy(operation.asset_record()))
        elif isinstance(operation, SetDefaultsOperation):
            for assignment in operation.assignments:
                default_updates.append(
                    (
                        operation.mode_id,
                        operation.actor_id,
                        operation.component_type_id,
                        assignment.field_name,
                        copy.deepcopy(assignment.value),
                    )
                )
        else:  # pragma: no cover - union and registry are closed.
            raise TypedOperationError(
                f"unregistered operation instance {type(operation).__name__}"
            )

    return TypedCgsFragmentPlan(
        component_schemas=tuple(component_schemas),
        actor_components=tuple(actor_components),
        global_systems=tuple(global_systems),
        mode_systems=tuple(mode_systems),
        semantic_events=tuple(semantic_events),
        mode_rules=tuple(mode_rules),
        assets=tuple(assets),
        default_updates=tuple(default_updates),
    )


def normalized_typed_operation_batch(
    batch: TypedCgsOperationBatch,
) -> dict[str, Any]:
    """Return the canonical, path-free wire representation of a batch.

    Optional operation fields are materialized with their validated defaults so
    downstream consumers never need to reinterpret omitted provider values.
    Mutable values are copied to keep the normalized payload independent from
    both the provider input and the frozen operation model.
    """

    operations: list[dict[str, Any]] = []
    for operation in batch.operations:
        record: dict[str, Any] = {
            "operation_id": operation.operation_id,
            "kind": operation.kind.value,
            "explanation": operation.explanation,
        }
        if isinstance(operation, DeclareComponentOperation):
            record.update({
                "component_type_id": operation.component_type_id,
                "component_name": operation.component_name,
                "version": operation.version,
                "fields": [copy.deepcopy(field.to_dict()) for field in operation.fields],
                "source": operation.source,
            })
        elif isinstance(operation, AddComponentOperation):
            record.update({
                "mode_id": operation.mode_id,
                "actor_id": operation.actor_id,
                "component_type_id": operation.component_type_id,
                "component_name": operation.component_name,
                "defaults": [
                    copy.deepcopy(assignment.to_dict())
                    for assignment in operation.defaults
                ],
                "use_schema_defaults": operation.use_schema_defaults,
            })
        elif isinstance(operation, AddSystemOperation):
            record.update({
                "system_id": operation.system_id,
                "phase": operation.phase.value,
                "reads": list(operation.reads),
                "writes": list(operation.writes),
                "depends_on": list(operation.depends_on),
                "implementation_ref": operation.implementation_ref,
                "scope": operation.scope.value,
                "mode_id": operation.mode_id,
                "version": operation.version,
                "deterministic": operation.deterministic,
                "parallel": operation.parallel,
            })
        elif isinstance(operation, AddGeneratedSystemOperation):
            record.update({
                "system_id": operation.system_id,
                "phase": operation.phase.value,
                "reads": list(operation.reads),
                "writes": list(operation.writes),
                "depends_on": list(operation.depends_on),
                "behavior": copy.deepcopy(operation.behavior.to_dict()),
                "scope": operation.scope.value,
                "mode_id": operation.mode_id,
                "version": operation.version,
                "deterministic": operation.deterministic,
                "parallel": operation.parallel,
            })
            if operation.runtime_executor is not None:
                record["runtime_executor"] = copy.deepcopy(
                    dict(operation.runtime_executor)
                )
        elif isinstance(operation, AddEventOperation):
            record.update({
                "event_name": operation.event_name,
                "payload_fields": [
                    copy.deepcopy(field.to_dict())
                    for field in operation.payload_fields
                ],
                "version": operation.version,
            })
        elif isinstance(operation, AddRuleOperation):
            record.update({
                "mode_id": operation.mode_id,
                "rule_id": operation.rule_id,
                "condition": operation.condition,
                "effect": operation.effect,
                "priority": operation.priority,
                "is_active": operation.is_active,
            })
        elif isinstance(operation, AddAssetOperation):
            record.update({
                "asset_id": operation.asset_id,
                "asset_type": operation.asset_type.value,
                "status": operation.status.value,
                "source": operation.source,
            })
        elif isinstance(operation, SetDefaultsOperation):
            record.update({
                "mode_id": operation.mode_id,
                "actor_id": operation.actor_id,
                "component_type_id": operation.component_type_id,
                "assignments": [
                    copy.deepcopy(assignment.to_dict())
                    for assignment in operation.assignments
                ],
            })
        else:  # pragma: no cover - union and registry are closed.
            raise TypedOperationError(
                f"unregistered operation instance {type(operation).__name__}"
            )
        operations.append(record)

    return {
        "schema": batch.schema,
        "request_id": batch.request_id,
        "prompt_id": batch.prompt_id,
        "operations": operations,
        "summary": batch.summary,
    }


def serialize_typed_operation_batch(batch: TypedCgsOperationBatch) -> str:
    """Serialize a typed batch deterministically for the GDE boundary."""

    return json.dumps(
        normalized_typed_operation_batch(batch),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def typed_operation_batch_json_schema() -> dict[str, Any]:
    """Return the provider-facing JSON Schema for this closed grammar.

    Native strict-output providers require every property of an object schema
    to appear in that object's ``required`` list.  The parser intentionally
    continues to accept omitted optional fields and materializes them during
    canonical normalization, but the provider contract exposes that normalized
    shape directly.  ``anyOf`` is used for discriminated variants because it is
    supported by the strict provider subset while ``oneOf`` is not.
    """

    operation_variants = [
        _operation_json_schema(definition)
        for definition in OPERATION_REGISTRY.values()
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "request_id", "prompt_id", "operations", "summary"],
        "properties": {
            "schema": {
                "type": "string",
                "const": TYPED_OPERATION_BATCH_SCHEMA,
            },
            "request_id": _identifier_schema(),
            "prompt_id": _identifier_schema(),
            "operations": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_OPERATIONS_PER_BATCH,
                "items": {"anyOf": operation_variants},
            },
            "summary": {"type": "string", "minLength": 1, "maxLength": 240},
        },
    }


def _operation_json_schema(definition: OperationDefinition) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "operation_id": _identifier_schema(),
        "kind": {"type": "string", "const": definition.kind.value},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 240},
    }
    kind_properties = {
        OperationKind.DECLARE_COMPONENT: {
            "component_type_id": _generated_component_id_schema(),
            "component_name": {
                "type": "string",
                "pattern": r"^COMP_[A-Z][A-Z0-9_]*_V[1-9][0-9]*$",
            },
            "version": _semver_schema(),
            "fields": {
                "type": "array",
                "minItems": 1,
                "items": _component_field_schema(),
            },
            "source": {"type": "string", "const": "generated"},
        },
        OperationKind.ADD_COMPONENT: {
            "mode_id": _identifier_schema(),
            "actor_id": _identifier_schema(),
            "component_type_id": _positive_int_schema(),
            "component_name": {
                "type": "string",
                "pattern": r"^COMP_[A-Z][A-Z0-9_]*_V[1-9][0-9]*$",
            },
            "defaults": {
                "type": "array",
                "items": _default_assignment_schema(),
            },
            "use_schema_defaults": {"type": "boolean"},
        },
        OperationKind.ADD_SYSTEM: {
            "system_id": _identifier_schema(),
            "phase": {"type": "string", "enum": [item.value for item in SystemPhase]},
            "reads": _component_id_array_schema(),
            "writes": _component_id_array_schema(),
            "depends_on": {
                "type": "array",
                "items": _identifier_schema(),
            },
            "implementation_ref": _identifier_schema(),
            "scope": {"type": "string", "enum": [item.value for item in SystemScope]},
            "mode_id": {
                "anyOf": [
                    {"type": "string", "const": ""},
                    _identifier_schema(),
                ]
            },
            "version": _semver_schema(),
            "deterministic": {"type": "boolean", "const": True},
            "parallel": {"type": "boolean"},
        },
        OperationKind.ADD_GENERATED_SYSTEM: {
            "system_id": _identifier_schema(),
            "phase": {"type": "string", "enum": [item.value for item in SystemPhase]},
            "reads": _component_id_array_schema(),
            "writes": _component_id_array_schema(),
            "depends_on": {
                "type": "array",
                "items": _identifier_schema(),
            },
            "behavior": _generated_system_behavior_schema(),
            "scope": {"type": "string", "enum": [item.value for item in SystemScope]},
            "mode_id": {
                "anyOf": [
                    {"type": "string", "const": ""},
                    _identifier_schema(),
                ]
            },
            "version": _semver_schema(),
            "deterministic": {"type": "boolean", "const": True},
            "parallel": {"type": "boolean"},
        },
        OperationKind.ADD_EVENT: {
            "event_name": _identifier_schema(),
            "payload_fields": {
                "type": "array",
                "items": _event_payload_field_schema(),
            },
            "version": _semver_schema(),
        },
        OperationKind.ADD_RULE: {
            "mode_id": _identifier_schema(),
            "rule_id": _identifier_schema(),
            "condition": {"type": "string", "minLength": 1},
            "effect": {"type": "string", "minLength": 1},
            "priority": {"type": "integer"},
            "is_active": {"type": "boolean"},
        },
        OperationKind.ADD_ASSET: {
            "asset_id": _identifier_schema(),
            "asset_type": {"type": "string", "enum": [item.value for item in AssetType]},
            "status": {"type": "string", "enum": [item.value for item in AssetStatus]},
            "source": {
                "type": "string",
                "pattern": (
                    r"^(?!/)(?![A-Za-z]:[\\/])"
                    r"(?!.*(?:^|[\\/])\.\.(?:[\\/]|$))[^\r\n]*$"
                ),
            },
        },
        OperationKind.SET_DEFAULTS: {
            "mode_id": _identifier_schema(),
            "actor_id": _identifier_schema(),
            "component_type_id": _positive_int_schema(),
            "assignments": {
                "type": "array",
                "minItems": 1,
                "items": _default_assignment_schema(),
            },
        },
    }[definition.kind]
    properties.update(kind_properties)
    return _strict_object_schema(properties)


def _strict_object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    """Build an OpenAI-strict-compatible closed object schema."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(properties),
        "properties": properties,
    }


def _component_field_schema() -> dict[str, Any]:
    return {
        "anyOf": [
            _typed_value_object_schema(
                name_key="name",
                value_key="default",
                field_type=field_type,
                extra_properties={"description": {"type": "string"}},
            )
            for field_type in FieldType
        ]
    }


def _default_assignment_schema() -> dict[str, Any]:
    return {
        "anyOf": [
            _typed_value_object_schema(
                name_key="field_name",
                value_key="value",
                field_type=field_type,
            )
            for field_type in FieldType
        ]
    }


def _event_payload_field_schema() -> dict[str, Any]:
    return _strict_object_schema({
        "name": _identifier_schema(),
        "field_type": _field_type_schema(),
        "required": {"type": "boolean"},
    })


def _generated_system_behavior_schema() -> dict[str, Any]:
    return _strict_object_schema({
        "kind": {
            "type": "string",
            "const": GeneratedSystemBehaviorKind.INCREMENT_NUMERIC_FIELD.value,
        },
        "component_type_id": _positive_int_schema(),
        "field": _identifier_schema(),
        "amount": {"type": "integer"},
    })


def _typed_value_object_schema(
    *,
    name_key: str,
    value_key: str,
    field_type: FieldType,
    extra_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        name_key: _identifier_schema(),
        "field_type": {"type": "string", "const": field_type.value},
        value_key: _value_schema_for(field_type),
    }
    if extra_properties:
        properties.update(extra_properties)
    return _strict_object_schema(properties)


def _value_schema_for(field_type: FieldType) -> dict[str, Any]:
    if field_type in {FieldType.FIXED, FieldType.INT}:
        return {"type": "integer"}
    if field_type in {FieldType.UINT, FieldType.ENTITY_ID}:
        return {"type": "integer", "minimum": 0}
    if field_type is FieldType.BOOL:
        return {"type": "boolean"}
    if field_type is FieldType.STRING:
        return {"type": "string"}
    if field_type is FieldType.STRING_LIST:
        return {
            "type": "array",
            "maxItems": MAX_OPERATIONS_PER_BATCH,
            "items": {"type": "string"},
        }
    if field_type is FieldType.INT_LIST:
        return {
            "type": "array",
            "maxItems": MAX_OPERATIONS_PER_BATCH,
            "items": {"type": "integer"},
        }
    if field_type is FieldType.OBJECT:
        # Strict providers cannot describe arbitrary object keys while also
        # requiring ``additionalProperties: false``.  The native schema keeps
        # this branch closed by permitting an empty object; richer deterministic
        # object defaults remain accepted by the fail-closed parser boundary.
        return _strict_object_schema({})
    raise TypedOperationError(f"unsupported field type {field_type!r}")


def _field_type_schema() -> dict[str, Any]:
    return {"type": "string", "enum": [item.value for item in FieldType]}


def _identifier_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$",
    }


def _positive_int_schema() -> dict[str, Any]:
    return {"type": "integer", "minimum": 1}


def _generated_component_id_schema() -> dict[str, Any]:
    return {"type": "integer", "minimum": 10_000}


def _semver_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$",
    }


def _component_id_array_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": _positive_int_schema(),
    }


def _parse_component_field(value: Any, index: int) -> ComponentField:
    raw = _mapping_value(value, f"fields[{index}]")
    _check_keys(
        raw,
        required={"name", "field_type", "default"},
        optional={"description"},
        label=f"fields[{index}]",
    )
    return ComponentField(
        name=_string(raw, "name"),
        field_type=_enum(raw, "field_type", FieldType),
        default=copy.deepcopy(raw["default"]),
        description=_string(raw, "description", default=""),
    )


def _parse_default_assignment(value: Any, index: int) -> DefaultAssignment:
    raw = _mapping_value(value, f"default assignment[{index}]")
    _check_keys(
        raw,
        required={"field_name", "field_type", "value"},
        optional=set(),
        label=f"default assignment[{index}]",
    )
    return DefaultAssignment(
        field_name=_string(raw, "field_name"),
        field_type=_enum(raw, "field_type", FieldType),
        value=copy.deepcopy(raw["value"]),
    )


def _parse_event_payload_field(value: Any, index: int) -> EventPayloadField:
    raw = _mapping_value(value, f"payload_fields[{index}]")
    _check_keys(
        raw,
        required={"name", "field_type"},
        optional={"required"},
        label=f"payload_fields[{index}]",
    )
    return EventPayloadField(
        name=_string(raw, "name"),
        field_type=_enum(raw, "field_type", FieldType),
        required=_boolean(raw, "required", default=True),
    )


def _parse_generated_system_behavior(value: Any) -> IncrementNumericFieldBehavior:
    raw = _mapping_value(value, "generated system behavior")
    _check_keys(
        raw,
        required={"kind", "component_type_id", "field", "amount"},
        optional=set(),
        label="generated system behavior",
    )
    return IncrementNumericFieldBehavior(
        kind=_enum(raw, "kind", GeneratedSystemBehaviorKind),
        component_type_id=_integer(raw, "component_type_id"),
        field=_string(raw, "field"),
        amount=_integer(raw, "amount"),
    )


def _mapping_value(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypedOperationError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise TypedOperationError(f"{label} keys must be strings")
    return value


def _optional_mapping(
    value: Mapping[str, Any],
    key: str,
) -> Mapping[str, Any] | None:
    if key not in value:
        return None
    candidate = _mapping_value(value[key], key)
    return copy.deepcopy(dict(candidate))


def _check_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    if missing:
        raise TypedOperationError(f"{label} missing required fields {missing}")
    if extra:
        raise TypedOperationError(f"{label} contains unknown fields {extra}")


_MISSING = object()


def _string(
    value: Mapping[str, Any],
    key: str,
    *,
    default: Any = _MISSING,
) -> str:
    candidate = value.get(key, default)
    if candidate is _MISSING:
        raise TypedOperationError(f"missing required string field {key!r}")
    if not isinstance(candidate, str):
        raise TypedOperationError(f"{key} must be a string")
    return candidate


def _integer(value: Mapping[str, Any], key: str) -> int:
    candidate = value.get(key, _MISSING)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise TypedOperationError(f"{key} must be an integer")
    return candidate


def _boolean(
    value: Mapping[str, Any],
    key: str,
    *,
    default: Any = _MISSING,
) -> bool:
    candidate = value.get(key, default)
    if candidate is _MISSING or not isinstance(candidate, bool):
        raise TypedOperationError(f"{key} must be a boolean")
    return candidate


def _list(
    value: Mapping[str, Any],
    key: str,
    *,
    default: Any = _MISSING,
) -> list[Any]:
    candidate = value.get(key, default)
    if candidate is _MISSING or not isinstance(candidate, list):
        raise TypedOperationError(f"{key} must be an array")
    return candidate


def _integer_list(value: Mapping[str, Any], key: str) -> list[int]:
    result = _list(value, key)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in result):
        raise TypedOperationError(f"{key} must contain only integers")
    return result


def _string_list(value: Mapping[str, Any], key: str) -> list[str]:
    result = _list(value, key)
    if any(not isinstance(item, str) for item in result):
        raise TypedOperationError(f"{key} must contain only strings")
    return result


def _enum(
    value: Mapping[str, Any],
    key: str,
    enum_type: type[Any],
    *,
    default: Any = _MISSING,
) -> Any:
    candidate = value.get(key, default)
    if candidate is _MISSING:
        raise TypedOperationError(f"missing required enum field {key!r}")
    if isinstance(candidate, enum_type):
        return candidate
    if not isinstance(candidate, str):
        raise TypedOperationError(f"{key} must be a string enum")
    try:
        return enum_type(candidate)
    except ValueError as exc:
        allowed = [item.value for item in enum_type]
        raise TypedOperationError(
            f"{key} must be one of {allowed}; got {candidate!r}"
        ) from exc
