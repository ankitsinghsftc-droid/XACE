"""Closed, typed operation model for prompt-authored CGS schema changes.

The existing prompt pipeline represents a mutation as ``path + op + Any``.
That is suitable for editing an already-known scalar field, but it is not a
safe grammar for generating new schema.  This module defines the first
versioned grammar for structural prompt output.  It deliberately contains no
free-form CGS path and no untyped structural ``value`` object.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, TypeAlias


TYPED_OPERATION_BATCH_SCHEMA = "xace.typed_cgs_operation_batch.v1"
MAX_OPERATIONS_PER_BATCH = 128

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_COMPONENT_NAME_RE = re.compile(r"^COMP_[A-Z][A-Z0-9_]*_V[1-9][0-9]*$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class TypedOperationError(ValueError):
    """Raised when provider output violates the typed CGS operation grammar."""


class OperationKind(str, Enum):
    DECLARE_COMPONENT = "declare_component"
    ADD_COMPONENT = "add_component"
    ADD_SYSTEM = "add_system"
    ADD_GENERATED_SYSTEM = "add_generated_system"
    ADD_EVENT = "add_event"
    ADD_RULE = "add_rule"
    ADD_ASSET = "add_asset"
    SET_DEFAULTS = "set_defaults"


class FieldType(str, Enum):
    """Portable authoritative field vocabulary for generated schema."""

    FIXED = "fixed"
    INT = "int"
    UINT = "uint"
    BOOL = "bool"
    STRING = "string"
    ENTITY_ID = "entity_id"
    STRING_LIST = "string_list"
    INT_LIST = "int_list"
    OBJECT = "object"


class SystemPhase(str, Enum):
    INITIALIZATION = "Initialization"
    INPUT = "Input"
    SIMULATION = "Simulation"
    POST_SIMULATION = "PostSimulation"
    CLEANUP = "Cleanup"


class SystemScope(str, Enum):
    GLOBAL = "global"
    MODE = "mode"


class GeneratedSystemBehaviorKind(str, Enum):
    INCREMENT_NUMERIC_FIELD = "increment_numeric_field"


class AssetType(str, Enum):
    MESH = "MESH"
    TEXTURE = "TEXTURE"
    MATERIAL = "MATERIAL"
    ANIMATION_CONTROLLER = "ANIMATION_CONTROLLER"
    ANIMATION_CLIP = "ANIMATION_CLIP"
    AUDIO_CLIP = "AUDIO_CLIP"
    AUDIO_MUSIC = "AUDIO_MUSIC"
    SPRITE = "SPRITE"
    PARTICLE = "PARTICLE"
    PREFAB = "PREFAB"
    FONT = "FONT"


class AssetStatus(str, Enum):
    PLACEHOLDER = "PLACEHOLDER"
    LINKED = "LINKED"
    MISSING = "MISSING"


JsonValue: TypeAlias = (
    None | bool | int | str | list["JsonValue"] | dict[str, "JsonValue"]
)


def require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise TypedOperationError(
            f"{label} must match {_IDENTIFIER_RE.pattern!r}; got {value!r}"
        )


def require_component_name(value: str) -> None:
    if not isinstance(value, str) or not _COMPONENT_NAME_RE.fullmatch(value):
        raise TypedOperationError(
            "component_name must use COMP_<NAME>_V<NUMBER>; "
            f"got {value!r}"
        )


def require_semver(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SEMVER_RE.fullmatch(value):
        raise TypedOperationError(f"{label} must be a MAJOR.MINOR.PATCH version")


def require_positive_type_id(value: int, label: str = "component_type_id") -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TypedOperationError(f"{label} must be a positive integer")


def require_json_value(value: Any, label: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            require_json_value(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypedOperationError(f"{label} object keys must be strings")
            require_json_value(item, f"{label}.{key}")
        return
    raise TypedOperationError(
        f"{label} must contain deterministic typed JSON values without floats, "
        f"got {type(value).__name__}"
    )


def require_typed_value(value: Any, field_type: FieldType, label: str) -> None:
    """Validate one default/payload value without coercion."""

    require_json_value(value, label)
    if field_type in {FieldType.FIXED, FieldType.INT}:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif field_type in {FieldType.UINT, FieldType.ENTITY_ID}:
        valid = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        )
    elif field_type is FieldType.BOOL:
        valid = isinstance(value, bool)
    elif field_type is FieldType.STRING:
        valid = isinstance(value, str)
    elif field_type is FieldType.STRING_LIST:
        valid = isinstance(value, list) and all(
            isinstance(item, str) for item in value
        )
    elif field_type is FieldType.INT_LIST:
        valid = isinstance(value, list) and all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in value
        )
    elif field_type is FieldType.OBJECT:
        valid = isinstance(value, dict)
    else:  # pragma: no cover - closed Enum makes this defensive only.
        valid = False
    if not valid:
        raise TypedOperationError(
            f"{label} does not match declared type {field_type.value!r}"
        )


def require_unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise TypedOperationError(f"{label} must be unique")


def require_finite_number(value: Any, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise TypedOperationError(f"{label} must be a finite number")


def require_finite_json_value(value: Any, label: str) -> None:
    """Validate trusted materialized JSON, including finite numeric values."""

    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        require_finite_number(value, label)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            require_finite_json_value(item, f"{label}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypedOperationError(f"{label} object keys must be strings")
            require_finite_json_value(item, f"{label}.{key}")
        return
    raise TypedOperationError(
        f"{label} must contain deterministic finite JSON values, "
        f"got {type(value).__name__}"
    )


@dataclass(frozen=True)
class ComponentField:
    name: str
    field_type: FieldType
    default: JsonValue
    description: str = ""

    def __post_init__(self) -> None:
        require_identifier(self.name, "component field name")
        require_typed_value(self.default, self.field_type, f"field {self.name}")
        if not isinstance(self.description, str):
            raise TypedOperationError("component field description must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "field_type": self.field_type.value,
            "default": self.default,
            "description": self.description,
        }


@dataclass(frozen=True)
class DefaultAssignment:
    field_name: str
    field_type: FieldType
    value: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.field_name, "default field_name")
        require_typed_value(
            self.value, self.field_type, f"default {self.field_name}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "field_type": self.field_type.value,
            "value": self.value,
        }


@dataclass(frozen=True)
class EventPayloadField:
    name: str
    field_type: FieldType
    required: bool = True

    def __post_init__(self) -> None:
        require_identifier(self.name, "event payload field name")
        if not isinstance(self.required, bool):
            raise TypedOperationError("event payload required must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "field_type": self.field_type.value,
            "required": self.required,
        }


@dataclass(frozen=True)
class IncrementNumericFieldBehavior:
    component_type_id: int
    field: str
    amount: int
    kind: GeneratedSystemBehaviorKind = (
        GeneratedSystemBehaviorKind.INCREMENT_NUMERIC_FIELD
    )

    def __post_init__(self) -> None:
        require_positive_type_id(self.component_type_id)
        require_identifier(self.field, "generated behavior field")
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise TypedOperationError(
                "generated behavior amount must be an integer"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "component_type_id": self.component_type_id,
            "field": self.field,
            "amount": self.amount,
        }


@dataclass(frozen=True)
class _OperationBase:
    operation_id: str
    explanation: str

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, "operation_id")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise TypedOperationError("operation explanation must not be empty")
        if len(self.explanation) > 240:
            raise TypedOperationError("operation explanation exceeds 240 characters")


@dataclass(frozen=True)
class DeclareComponentOperation(_OperationBase):
    component_type_id: int
    component_name: str
    version: str
    fields: tuple[ComponentField, ...]
    source: str = "generated"
    kind: OperationKind = OperationKind.DECLARE_COMPONENT

    def __post_init__(self) -> None:
        super().__post_init__()
        require_positive_type_id(self.component_type_id)
        if self.component_type_id < 10_000:
            raise TypedOperationError(
                "prompt-declared components must use the GCL type-id range (>= 10000)"
            )
        require_component_name(self.component_name)
        require_semver(self.version, "component version")
        if not self.fields:
            raise TypedOperationError("declared component must contain fields")
        require_unique(tuple(field.name for field in self.fields), "component fields")
        if self.source != "generated":
            raise TypedOperationError(
                "prompt-declared component source must be 'generated'"
            )

    def component_schema_record(self) -> dict[str, Any]:
        return {
            "type_id": self.component_type_id,
            "name": self.component_name,
            "version": self.version,
            "fields": [copy.deepcopy(field.to_dict()) for field in self.fields],
            "defaults": {
                field.name: copy.deepcopy(field.default) for field in self.fields
            },
            "source": self.source,
        }


@dataclass(frozen=True)
class AddComponentOperation(_OperationBase):
    mode_id: str
    actor_id: str
    component_type_id: int
    component_name: str
    defaults: tuple[DefaultAssignment, ...] = ()
    use_schema_defaults: bool = True
    kind: OperationKind = OperationKind.ADD_COMPONENT

    def __post_init__(self) -> None:
        super().__post_init__()
        require_identifier(self.mode_id, "mode_id")
        require_identifier(self.actor_id, "actor_id")
        require_positive_type_id(self.component_type_id)
        require_component_name(self.component_name)
        require_unique(
            tuple(item.field_name for item in self.defaults),
            "component default assignments",
        )
        if not isinstance(self.use_schema_defaults, bool):
            raise TypedOperationError("use_schema_defaults must be boolean")
        if not self.use_schema_defaults and not self.defaults:
            raise TypedOperationError(
                "add_component needs typed defaults when schema defaults are disabled"
            )

    def component_record(self) -> dict[str, Any]:
        return {
            "type_id": self.component_type_id,
            "name": self.component_name,
            "defaults": {
                assignment.field_name: assignment.value
                for assignment in self.defaults
            },
        }


@dataclass(frozen=True)
class AddSystemOperation(_OperationBase):
    system_id: str
    phase: SystemPhase
    reads: tuple[int, ...]
    writes: tuple[int, ...]
    depends_on: tuple[str, ...]
    implementation_ref: str
    scope: SystemScope = SystemScope.GLOBAL
    mode_id: str = ""
    version: str = "1.0.0"
    deterministic: bool = True
    parallel: bool = False
    kind: OperationKind = OperationKind.ADD_SYSTEM

    def __post_init__(self) -> None:
        super().__post_init__()
        require_identifier(self.system_id, "system_id")
        require_identifier(self.implementation_ref, "implementation_ref")
        require_semver(self.version, "system version")
        for value in self.reads + self.writes:
            require_positive_type_id(value, "system component type_id")
        if tuple(sorted(set(self.reads))) != self.reads:
            raise TypedOperationError("system reads must be sorted and unique")
        if tuple(sorted(set(self.writes))) != self.writes:
            raise TypedOperationError("system writes must be sorted and unique")
        require_unique(self.depends_on, "system dependencies")
        for dependency in self.depends_on:
            require_identifier(dependency, "system dependency")
        if self.system_id in self.depends_on:
            raise TypedOperationError("system cannot depend on itself")
        if self.scope is SystemScope.MODE:
            require_identifier(self.mode_id, "mode_id")
        elif self.mode_id:
            raise TypedOperationError("global system operation must not set mode_id")
        if self.deterministic is not True:
            raise TypedOperationError("authoritative generated systems must be deterministic")
        if not isinstance(self.parallel, bool):
            raise TypedOperationError("system parallel must be boolean")

    def system_record(self) -> dict[str, Any]:
        return {
            "id": self.system_id,
            "phase": self.phase.value,
            "reads": list(self.reads),
            "writes": list(self.writes),
            "depends_on": list(self.depends_on),
            "deterministic": True,
            "parallel": self.parallel,
            "version": self.version,
            "implementation_ref": self.implementation_ref,
        }


@dataclass(frozen=True)
class AddGeneratedSystemOperation(_OperationBase):
    system_id: str
    phase: SystemPhase
    reads: tuple[int, ...]
    writes: tuple[int, ...]
    depends_on: tuple[str, ...]
    behavior: IncrementNumericFieldBehavior
    scope: SystemScope = SystemScope.GLOBAL
    mode_id: str = ""
    version: str = "1.0.0"
    deterministic: bool = True
    parallel: bool = False
    runtime_executor: Mapping[str, Any] | None = None
    kind: OperationKind = OperationKind.ADD_GENERATED_SYSTEM

    def __post_init__(self) -> None:
        super().__post_init__()
        require_identifier(self.system_id, "system_id")
        require_semver(self.version, "system version")
        for value in self.reads + self.writes:
            require_positive_type_id(value, "system component type_id")
        if tuple(sorted(set(self.reads))) != self.reads:
            raise TypedOperationError("system reads must be sorted and unique")
        if tuple(sorted(set(self.writes))) != self.writes:
            raise TypedOperationError("system writes must be sorted and unique")
        require_unique(self.depends_on, "system dependencies")
        for dependency in self.depends_on:
            require_identifier(dependency, "system dependency")
        if self.system_id in self.depends_on:
            raise TypedOperationError("system cannot depend on itself")
        if self.scope is SystemScope.MODE:
            require_identifier(self.mode_id, "mode_id")
        elif self.mode_id:
            raise TypedOperationError("global system operation must not set mode_id")
        if self.deterministic is not True:
            raise TypedOperationError(
                "authoritative generated systems must be deterministic"
            )
        if not isinstance(self.parallel, bool):
            raise TypedOperationError("system parallel must be boolean")
        if self.behavior.component_type_id not in self.reads:
            raise TypedOperationError(
                "generated behavior component_type_id must be declared in reads"
            )
        if self.behavior.component_type_id not in self.writes:
            raise TypedOperationError(
                "generated behavior component_type_id must be declared in writes"
            )
        if self.runtime_executor is not None:
            self._validate_runtime_executor(self.runtime_executor)

    def _validate_runtime_executor(self, executor: Mapping[str, Any]) -> None:
        if not isinstance(executor, Mapping):
            raise TypedOperationError("runtime_executor must be an object")
        require_finite_json_value(executor, "runtime_executor")
        required_keys = {"kind", "component_type_id", "field", "amount", "abi"}
        allowed_keys = required_keys | {"compile_artifact"}
        missing = sorted(required_keys - set(executor))
        extra = sorted(set(executor) - allowed_keys)
        if missing:
            raise TypedOperationError(
                f"runtime_executor missing required fields {missing}"
            )
        if extra:
            raise TypedOperationError(
                f"runtime_executor contains unknown fields {extra}"
            )
        expected = self.behavior
        if executor.get("kind") != "generated.increment_numeric_field":
            raise TypedOperationError(
                "runtime_executor.kind must be 'generated.increment_numeric_field'"
            )
        if executor.get("component_type_id") != expected.component_type_id:
            raise TypedOperationError(
                "runtime_executor component_type_id does not match behavior"
            )
        if executor.get("field") != expected.field:
            raise TypedOperationError("runtime_executor field does not match behavior")
        amount = executor.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypedOperationError("runtime_executor amount must be an integer")
        if amount != expected.amount:
            raise TypedOperationError("runtime_executor amount does not match behavior")
        if not isinstance(executor.get("abi"), Mapping):
            raise TypedOperationError("runtime_executor.abi must be an object")
        if "compile_artifact" in executor and not isinstance(
            executor.get("compile_artifact"), Mapping
        ):
            raise TypedOperationError(
                "runtime_executor.compile_artifact must be an object when present"
            )

    def system_record(self) -> dict[str, Any]:
        record = {
            "id": self.system_id,
            "phase": self.phase.value,
            "reads": list(self.reads),
            "writes": list(self.writes),
            "depends_on": list(self.depends_on),
            "deterministic": True,
            "parallel": self.parallel,
            "version": self.version,
            "source": "generated",
            "description": self.explanation,
        }
        if self.runtime_executor is not None:
            record["runtime_executor"] = copy.deepcopy(dict(self.runtime_executor))
        return record


@dataclass(frozen=True)
class AddEventOperation(_OperationBase):
    event_name: str
    payload_fields: tuple[EventPayloadField, ...]
    version: str = "1.0.0"
    kind: OperationKind = OperationKind.ADD_EVENT

    def __post_init__(self) -> None:
        super().__post_init__()
        require_identifier(self.event_name, "event_name")
        require_semver(self.version, "event version")
        require_unique(
            tuple(field.name for field in self.payload_fields),
            "event payload fields",
        )

    def event_record(self) -> dict[str, Any]:
        return {
            "name": self.event_name,
            "version": self.version,
            "payload_fields": [field.to_dict() for field in self.payload_fields],
            "required_payload_keys": [
                field.name for field in self.payload_fields if field.required
            ],
        }


@dataclass(frozen=True)
class AddRuleOperation(_OperationBase):
    mode_id: str
    rule_id: str
    condition: str
    effect: str
    priority: int
    is_active: bool = True
    kind: OperationKind = OperationKind.ADD_RULE

    def __post_init__(self) -> None:
        super().__post_init__()
        require_identifier(self.mode_id, "mode_id")
        require_identifier(self.rule_id, "rule_id")
        if not isinstance(self.condition, str) or not self.condition.strip():
            raise TypedOperationError("rule condition must not be empty")
        if not isinstance(self.effect, str) or not self.effect.strip():
            raise TypedOperationError("rule effect must not be empty")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypedOperationError("rule priority must be an integer")
        if not isinstance(self.is_active, bool):
            raise TypedOperationError("rule is_active must be boolean")

    def rule_record(self) -> dict[str, Any]:
        return {
            "id": self.rule_id,
            "condition": self.condition,
            "effect": self.effect,
            "priority": self.priority,
            "is_active": self.is_active,
        }


@dataclass(frozen=True)
class AddAssetOperation(_OperationBase):
    asset_id: str
    asset_type: AssetType
    status: AssetStatus
    source: str = ""
    kind: OperationKind = OperationKind.ADD_ASSET

    def __post_init__(self) -> None:
        super().__post_init__()
        require_identifier(self.asset_id, "asset_id")
        if not isinstance(self.source, str):
            raise TypedOperationError("asset source must be a string")
        if self.source:
            normalized = self.source.replace("\\", "/")
            if (
                normalized.startswith("/")
                or re.match(r"^[A-Za-z]:/", normalized)
                or ".." in normalized.split("/")
            ):
                raise TypedOperationError(
                    "asset source must be a project-relative traversal-free path"
                )
        if self.status is AssetStatus.LINKED and not self.source:
            raise TypedOperationError("linked asset requires a project-relative source")

    def asset_record(self) -> dict[str, Any]:
        record = {
            "id": self.asset_id,
            "asset_type": self.asset_type.value,
            "status": self.status.value,
        }
        if self.source:
            record["source"] = self.source.replace("\\", "/")
        return record


@dataclass(frozen=True)
class SetDefaultsOperation(_OperationBase):
    mode_id: str
    actor_id: str
    component_type_id: int
    assignments: tuple[DefaultAssignment, ...]
    kind: OperationKind = OperationKind.SET_DEFAULTS

    def __post_init__(self) -> None:
        super().__post_init__()
        require_identifier(self.mode_id, "mode_id")
        require_identifier(self.actor_id, "actor_id")
        require_positive_type_id(self.component_type_id)
        if not self.assignments:
            raise TypedOperationError("set_defaults needs at least one assignment")
        require_unique(
            tuple(item.field_name for item in self.assignments),
            "default assignments",
        )


TypedCgsOperation: TypeAlias = (
    DeclareComponentOperation
    | AddComponentOperation
    | AddSystemOperation
    | AddGeneratedSystemOperation
    | AddEventOperation
    | AddRuleOperation
    | AddAssetOperation
    | SetDefaultsOperation
)


@dataclass(frozen=True)
class TypedCgsOperationBatch:
    request_id: str
    prompt_id: str
    operations: tuple[TypedCgsOperation, ...]
    summary: str
    schema: str = TYPED_OPERATION_BATCH_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TYPED_OPERATION_BATCH_SCHEMA:
            raise TypedOperationError(
                f"schema must equal {TYPED_OPERATION_BATCH_SCHEMA!r}"
            )
        require_identifier(self.request_id, "request_id")
        require_identifier(self.prompt_id, "prompt_id")
        if not self.operations:
            raise TypedOperationError("typed operation batch must not be empty")
        if len(self.operations) > MAX_OPERATIONS_PER_BATCH:
            raise TypedOperationError(
                f"typed operation batch exceeds {MAX_OPERATIONS_PER_BATCH} operations"
            )
        require_unique(
            tuple(operation.operation_id for operation in self.operations),
            "operation IDs",
        )
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise TypedOperationError("batch summary must not be empty")
        if len(self.summary) > 240:
            raise TypedOperationError("batch summary exceeds 240 characters")
        self._validate_internal_references()

    def _validate_internal_references(self) -> None:
        component_declarations = [
            operation
            for operation in self.operations
            if isinstance(operation, DeclareComponentOperation)
        ]
        require_unique(
            tuple(operation.component_type_id for operation in component_declarations),
            "declared component type IDs",
        )
        require_unique(
            tuple(operation.component_name for operation in component_declarations),
            "declared component names",
        )
        systems = [
            operation
            for operation in self.operations
            if isinstance(
                operation,
                (AddSystemOperation, AddGeneratedSystemOperation),
            )
        ]
        require_unique(
            tuple(operation.system_id for operation in systems),
            "declared system IDs",
        )
        events = [
            operation
            for operation in self.operations
            if isinstance(operation, AddEventOperation)
        ]
        require_unique(
            tuple(operation.event_name for operation in events),
            "declared event names",
        )
        assets = [
            operation
            for operation in self.operations
            if isinstance(operation, AddAssetOperation)
        ]
        require_unique(
            tuple(operation.asset_id for operation in assets),
            "declared asset IDs",
        )
        rules = [
            operation
            for operation in self.operations
            if isinstance(operation, AddRuleOperation)
        ]
        require_unique(
            tuple((operation.mode_id, operation.rule_id) for operation in rules),
            "declared mode/rule IDs",
        )
        attachments = [
            operation
            for operation in self.operations
            if isinstance(operation, AddComponentOperation)
        ]
        require_unique(
            tuple(
                (
                    operation.mode_id,
                    operation.actor_id,
                    operation.component_type_id,
                )
                for operation in attachments
            ),
            "component attachment targets",
        )

        declared_components = {
            operation.component_type_id: operation
            for operation in component_declarations
        }
        declared_system_ids = {
            operation.system_id for operation in systems
        }

        for operation in self.operations:
            if isinstance(operation, AddComponentOperation):
                declaration = declared_components.get(operation.component_type_id)
                if declaration is not None:
                    if operation.component_name != declaration.component_name:
                        raise TypedOperationError(
                            f"{operation.operation_id}: component name does not "
                            "match its declaration"
                        )
                    field_types = {
                        field.name: field.field_type for field in declaration.fields
                    }
                    for assignment in operation.defaults:
                        expected = field_types.get(assignment.field_name)
                        if expected is None:
                            raise TypedOperationError(
                                f"{operation.operation_id}: unknown declared component "
                                f"field {assignment.field_name!r}"
                            )
                        if assignment.field_type is not expected:
                            raise TypedOperationError(
                                f"{operation.operation_id}: field "
                                f"{assignment.field_name!r} type does not match declaration"
                            )
            elif isinstance(operation, SetDefaultsOperation):
                declaration = declared_components.get(operation.component_type_id)
                if declaration is not None:
                    field_types = {
                        field.name: field.field_type for field in declaration.fields
                    }
                    for assignment in operation.assignments:
                        expected = field_types.get(assignment.field_name)
                        if expected is None or assignment.field_type is not expected:
                            raise TypedOperationError(
                                f"{operation.operation_id}: default assignment "
                                f"{assignment.field_name!r} does not match declaration"
                            )
            elif isinstance(
                operation,
                (AddSystemOperation, AddGeneratedSystemOperation),
            ):
                for dependency in operation.depends_on:
                    if dependency in declared_system_ids:
                        dependency_index = next(
                            index
                            for index, candidate in enumerate(self.operations)
                            if isinstance(
                                candidate,
                                (AddSystemOperation, AddGeneratedSystemOperation),
                            )
                            and candidate.system_id == dependency
                        )
                        operation_index = self.operations.index(operation)
                        if dependency_index >= operation_index:
                            raise TypedOperationError(
                                f"{operation.operation_id}: dependency {dependency!r} "
                                "must precede the dependent system in the batch"
                            )
            if isinstance(operation, AddGeneratedSystemOperation):
                declaration = declared_components.get(
                    operation.behavior.component_type_id
                )
                if declaration is not None:
                    fields = {
                        field.name: field.field_type
                        for field in declaration.fields
                    }
                    field_type = fields.get(operation.behavior.field)
                    if field_type is None:
                        raise TypedOperationError(
                            f"{operation.operation_id}: generated behavior field "
                            f"{operation.behavior.field!r} is not declared"
                        )
                    if field_type is not FieldType.FIXED:
                        raise TypedOperationError(
                            f"{operation.operation_id}: generated increment field "
                            "must use exact type 'fixed'"
                        )
