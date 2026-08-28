"""Local trust bridge for prompt-authored generated gameplay systems.

Provider output may describe a closed generated-system behavior, but it may
never supply executable code, a runtime executor, an ABI, or a compile
artifact.  This bridge derives those trusted fields locally, stages the system
in an isolated proposed CGS, invokes the existing SGC-backed code-generation
engine, and returns a batch containing only the locally signed executor.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping

from generated_system_safe_compiler import (
    GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND,
    GENERATED_SYSTEM_ABI_SCHEMA,
    GENERATED_SYSTEM_ABI_VERSION,
    REQUIRED_VALIDATION_STEPS,
    validate_compile_artifact_signature,
)


CANONICAL_SYSTEM_PHASES = frozenset({
    "Initialization",
    "Input",
    "Simulation",
    "PostSimulation",
    "Cleanup",
})


class GeneratedSystemMaterializationError(RuntimeError):
    """Fail-closed generated-system materialization failure."""

    def __init__(self, code: str, stage: str, message: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(message)


@dataclass(frozen=True)
class GeneratedSystemMaterializationResult:
    normalized_batch: dict[str, Any]
    proposed_cgs: dict[str, Any]
    generated_system_ids: tuple[str, ...] = ()
    diff_text: str = ""
    compile_artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def materialized(self) -> bool:
        return bool(self.generated_system_ids)


class GeneratedSystemMaterializer:
    """Derive, compile, sign, and attach trusted generated executors locally."""

    def __init__(
        self,
        *,
        enabled: bool,
        sgc_bin_path: str = "",
        code_generation_engine: Any = None,
        sgc_path_checker: Callable[[str], bool] | None = None,
        signature_validator: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._sgc_bin_path = str(sgc_bin_path or "").strip()
        self._engine = code_generation_engine
        self._sgc_path_checker = sgc_path_checker or (
            lambda value: Path(value).is_file()
        )
        self._signature_validator = (
            signature_validator or validate_compile_artifact_signature
        )

    def materialize(
        self,
        batch: Mapping[str, Any],
        cgs: Mapping[str, Any],
        *,
        session_id: str = "",
    ) -> GeneratedSystemMaterializationResult:
        """Return a trusted copy; never mutate the provider batch or base CGS."""

        if not isinstance(batch, Mapping) or not all(
            isinstance(key, str) for key in batch
        ):
            self._fail("invalid_batch", "provider_batch", "typed batch must be an object")
        raw_operations = batch.get("operations")
        if not isinstance(raw_operations, list):
            self._fail(
                "invalid_batch",
                "provider_batch",
                "typed batch operations must be an array",
            )

        trusted_batch = copy.deepcopy(dict(batch))
        operations = trusted_batch["operations"]
        generated = [
            operation
            for operation in operations
            if isinstance(operation, dict)
            and operation.get("kind") == "add_generated_system"
        ]
        if not generated:
            return GeneratedSystemMaterializationResult(
                normalized_batch=trusted_batch,
                proposed_cgs=copy.deepcopy(dict(cgs)),
            )

        if not self._enabled:
            self._fail(
                "code_generation_disabled",
                "configuration",
                "generated-system materialization is disabled",
            )
        if not self._sgc_bin_path:
            self._fail(
                "sgc_path_required",
                "configuration",
                "an SGC binary path is required for generated systems",
            )
        if not self._sgc_path_checker(self._sgc_bin_path):
            self._fail(
                "sgc_binary_unavailable",
                "configuration",
                f"SGC binary is unavailable: {self._sgc_bin_path}",
            )
        if self._engine is None or not callable(
            getattr(self._engine, "generate_system", None)
        ):
            self._fail(
                "code_generation_engine_unavailable",
                "configuration",
                "the local code-generation engine is unavailable",
            )

        proposed_cgs = copy.deepcopy(dict(cgs))
        generated_ids: list[str] = []
        artifacts: list[dict[str, Any]] = []
        diffs: list[str] = []

        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                self._fail(
                    "invalid_operation",
                    "provider_batch",
                    f"operations[{index}] must be an object",
                )
            kind = operation.get("kind")
            if kind == "declare_component":
                _stage_component_declaration(proposed_cgs, operation)
                continue
            if kind == "add_system":
                _stage_system(proposed_cgs, operation, runtime_executor=None)
                continue
            if kind != "add_generated_system":
                continue
            if "runtime_executor" in operation:
                self._fail(
                    "provider_supplied_runtime_executor",
                    "provider_batch",
                    "provider output may not supply runtime_executor",
                )

            runtime_executor = _derive_increment_executor(operation, proposed_cgs)
            staged_system = _stage_system(
                proposed_cgs,
                operation,
                runtime_executor=runtime_executor,
            )
            system_id = str(operation.get("system_id") or "")
            scope = str(operation.get("scope") or "global")
            mode_id = str(operation.get("mode_id") or "") if scope == "mode" else ""
            try:
                generation = self._engine.generate_system(
                    system_id=system_id,
                    cgs=proposed_cgs,
                    mode_id=mode_id,
                    description=str(operation.get("explanation") or ""),
                    session_id=session_id,
                )
            except Exception as exc:  # noqa: BLE001 - convert to fail-closed result.
                self._fail(
                    "code_generation_raised",
                    "code_generation",
                    f"local code generation raised for {system_id!r}: {exc}",
                )

            if not bool(getattr(generation, "succeeded", False)):
                error = str(getattr(generation, "error", "") or "unknown failure")
                self._fail(
                    "code_generation_failed",
                    "code_generation",
                    f"local code generation failed for {system_id!r}: {error}",
                )
            safe_result = getattr(generation, "safe_compile_result", None)
            if safe_result is None or not bool(getattr(safe_result, "succeeded", False)):
                self._fail(
                    "safe_compile_missing",
                    "safe_compile",
                    f"generated system {system_id!r} has no successful safe compile",
                )

            signed_executor = copy.deepcopy(
                getattr(generation, "signed_runtime_executor", None)
            )
            artifact = _validate_signed_executor(
                system_id,
                runtime_executor,
                signed_executor,
                self._signature_validator,
            )
            operation["runtime_executor"] = signed_executor
            staged_system["runtime_executor"] = copy.deepcopy(signed_executor)
            generated_ids.append(system_id)
            artifacts.append(copy.deepcopy(artifact))
            diff_text = str(getattr(generation, "diff_text", "") or "").strip()
            if diff_text:
                diffs.append(diff_text)

        return GeneratedSystemMaterializationResult(
            normalized_batch=trusted_batch,
            proposed_cgs=proposed_cgs,
            generated_system_ids=tuple(generated_ids),
            diff_text="\n\n".join(diffs),
            compile_artifacts=tuple(artifacts),
        )

    @staticmethod
    def _fail(code: str, stage: str, message: str) -> None:
        raise GeneratedSystemMaterializationError(code, stage, message)


def _derive_increment_executor(
    operation: Mapping[str, Any],
    proposed_cgs: Mapping[str, Any],
) -> dict[str, Any]:
    behavior = operation.get("behavior")
    if not isinstance(behavior, Mapping):
        raise GeneratedSystemMaterializationError(
            "behavior_required", "behavior_validation", "behavior must be an object"
        )
    if behavior.get("kind") != "increment_numeric_field":
        raise GeneratedSystemMaterializationError(
            "behavior_unsupported",
            "behavior_validation",
            "only increment_numeric_field is supported by the local materializer",
        )
    component_type_id = behavior.get("component_type_id")
    if (
        isinstance(component_type_id, bool)
        or not isinstance(component_type_id, int)
        or component_type_id <= 0
    ):
        raise GeneratedSystemMaterializationError(
            "component_type_invalid",
            "behavior_validation",
            "behavior.component_type_id must be a positive integer",
        )
    field_name = behavior.get("field")
    if (
        not isinstance(field_name, str)
        or not field_name
        or "." in field_name
    ):
        raise GeneratedSystemMaterializationError(
            "field_invalid",
            "behavior_validation",
            "behavior.field must name one top-level component field",
        )
    amount = behavior.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise GeneratedSystemMaterializationError(
            "amount_must_be_integer",
            "behavior_validation",
            "behavior.amount must be an integer whole-unit Fixed64 delta",
        )

    reads = _positive_id_list(operation.get("reads"), "reads")
    writes = _positive_id_list(operation.get("writes"), "writes")
    if component_type_id not in reads or component_type_id not in writes:
        raise GeneratedSystemMaterializationError(
            "component_access_mismatch",
            "behavior_validation",
            "increment target component must be declared in both reads and writes",
        )
    _require_fixed_component_field(
        proposed_cgs,
        component_type_id,
        field_name,
    )

    return {
        "kind": GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND,
        "component_type_id": component_type_id,
        "field": field_name,
        "amount": amount,
        "abi": {
            "schema": GENERATED_SYSTEM_ABI_SCHEMA,
            "version": GENERATED_SYSTEM_ABI_VERSION,
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
        },
    }


def _require_fixed_component_field(
    cgs: Mapping[str, Any],
    component_type_id: int,
    field_name: str,
) -> None:
    schemas = cgs.get("component_schemas")
    if not isinstance(schemas, list):
        schemas = []
    schema = next(
        (
            item
            for item in schemas
            if isinstance(item, dict)
            and item.get("type_id") == component_type_id
        ),
        None,
    )
    if schema is None:
        raise GeneratedSystemMaterializationError(
            "component_schema_missing",
            "behavior_validation",
            f"component type {component_type_id} has no declared schema metadata",
        )
    fields = schema.get("fields")
    if not isinstance(fields, list):
        fields = []
    field = next(
        (
            item
            for item in fields
            if isinstance(item, dict) and item.get("name") == field_name
        ),
        None,
    )
    if field is None:
        raise GeneratedSystemMaterializationError(
            "component_field_missing",
            "behavior_validation",
            f"component type {component_type_id} has no field {field_name!r}",
        )
    if field.get("field_type") != "fixed":
        raise GeneratedSystemMaterializationError(
            "component_field_not_fixed",
            "behavior_validation",
            f"generated numeric increment requires fixed field {field_name!r}",
        )


def _stage_component_declaration(
    cgs: dict[str, Any],
    operation: Mapping[str, Any],
) -> None:
    type_id = operation.get("component_type_id")
    name = operation.get("component_name")
    if isinstance(type_id, bool) or not isinstance(type_id, int) or type_id <= 0:
        raise GeneratedSystemMaterializationError(
            "component_declaration_invalid",
            "staging",
            "declared component_type_id must be positive",
        )
    schemas = cgs.setdefault("component_schemas", [])
    if not isinstance(schemas, list):
        raise GeneratedSystemMaterializationError(
            "component_schemas_invalid", "staging", "CGS component_schemas must be an array"
        )
    if any(
        isinstance(item, dict)
        and (item.get("type_id") == type_id or item.get("name") == name)
        for item in schemas
    ):
        raise GeneratedSystemMaterializationError(
            "component_declaration_duplicate",
            "staging",
            f"component {name!r}/{type_id} already exists",
        )
    fields = copy.deepcopy(operation.get("fields"))
    if not isinstance(fields, list) or not fields:
        raise GeneratedSystemMaterializationError(
            "component_fields_invalid", "staging", "declared component fields are required"
        )
    defaults = {
        str(field.get("name")): copy.deepcopy(field.get("default"))
        for field in fields
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    }
    schemas.append({
        "type_id": type_id,
        "name": name,
        "version": operation.get("version", "1.0.0"),
        "fields": fields,
        "defaults": defaults,
        "source": operation.get("source", "generated"),
    })


def _stage_system(
    cgs: dict[str, Any],
    operation: Mapping[str, Any],
    *,
    runtime_executor: dict[str, Any] | None,
) -> dict[str, Any]:
    system_id = operation.get("system_id")
    if not isinstance(system_id, str) or not system_id:
        raise GeneratedSystemMaterializationError(
            "system_id_invalid", "staging", "generated system_id is required"
        )
    if system_id in _all_system_ids(cgs):
        raise GeneratedSystemMaterializationError(
            "system_duplicate", "staging", f"system {system_id!r} already exists"
        )
    phase = operation.get("phase")
    if phase not in CANONICAL_SYSTEM_PHASES:
        raise GeneratedSystemMaterializationError(
            "system_phase_invalid", "staging", f"system phase {phase!r} is not canonical"
        )
    reads = _positive_id_list(operation.get("reads"), "reads")
    writes = _positive_id_list(operation.get("writes"), "writes")
    dependencies = operation.get("depends_on")
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) and item for item in dependencies
    ):
        raise GeneratedSystemMaterializationError(
            "system_dependencies_invalid", "staging", "depends_on must contain system IDs"
        )
    unknown = sorted(set(dependencies) - _all_system_ids(cgs))
    if unknown:
        raise GeneratedSystemMaterializationError(
            "system_dependency_unknown",
            "staging",
            f"system {system_id!r} has unknown or forward dependencies {unknown}",
        )
    record = {
        "id": system_id,
        "phase": phase,
        "reads": reads,
        "writes": writes,
        "depends_on": list(dependencies),
        "deterministic": True,
        "parallel": bool(operation.get("parallel", False)),
        "version": operation.get("version", "1.0.0"),
    }
    if runtime_executor is not None:
        record["runtime_executor"] = copy.deepcopy(runtime_executor)
    elif operation.get("implementation_ref"):
        record["implementation_ref"] = operation["implementation_ref"]

    scope = operation.get("scope", "global")
    if scope == "global":
        systems = cgs.setdefault("global_systems", [])
    elif scope == "mode":
        mode_id = operation.get("mode_id")
        mode = next(
            (
                item
                for item in cgs.get("modes", [])
                if isinstance(item, dict) and item.get("id") == mode_id
            ),
            None,
        )
        if mode is None:
            raise GeneratedSystemMaterializationError(
                "system_mode_unknown", "staging", f"mode {mode_id!r} does not exist"
            )
        systems = mode.setdefault("systems", [])
    else:
        raise GeneratedSystemMaterializationError(
            "system_scope_invalid", "staging", f"system scope {scope!r} is invalid"
        )
    if not isinstance(systems, list):
        raise GeneratedSystemMaterializationError(
            "systems_invalid", "staging", "CGS systems collection must be an array"
        )
    systems.append(record)
    return record


def _validate_signed_executor(
    system_id: str,
    derived_executor: dict[str, Any],
    signed_executor: Any,
    signature_validator: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    if not isinstance(signed_executor, dict):
        raise GeneratedSystemMaterializationError(
            "signed_executor_missing",
            "safe_compile",
            f"generated system {system_id!r} returned no signed runtime executor",
        )
    _require_float_free(signed_executor, "signed_runtime_executor")
    unsigned = copy.deepcopy(signed_executor)
    artifact = unsigned.pop("compile_artifact", None)
    if unsigned != derived_executor:
        raise GeneratedSystemMaterializationError(
            "signed_executor_mismatch",
            "safe_compile",
            "signed runtime executor does not match the locally derived behavior/ABI",
        )
    if not isinstance(artifact, dict):
        raise GeneratedSystemMaterializationError(
            "compile_artifact_missing",
            "safe_compile",
            "signed runtime executor has no compile artifact",
        )
    if artifact.get("system_id") != system_id:
        raise GeneratedSystemMaterializationError(
            "compile_artifact_system_mismatch",
            "safe_compile",
            "compile artifact system_id does not match the operation",
        )
    if artifact.get("runtime_executor_hash") != _sha256_json(derived_executor):
        raise GeneratedSystemMaterializationError(
            "compile_artifact_executor_mismatch",
            "safe_compile",
            "compile artifact is not bound to the derived runtime executor",
        )
    steps = artifact.get("validation_steps")
    if steps != list(REQUIRED_VALIDATION_STEPS):
        raise GeneratedSystemMaterializationError(
            "compile_artifact_steps_invalid",
            "safe_compile",
            "compile artifact does not contain the exact required validation steps",
        )
    if not signature_validator(artifact):
        raise GeneratedSystemMaterializationError(
            "compile_artifact_signature_invalid",
            "safe_compile",
            "compile artifact signature is invalid",
        )
    return artifact


def _positive_id_list(value: Any, label: str) -> list[int]:
    if not isinstance(value, list):
        raise GeneratedSystemMaterializationError(
            "component_access_invalid", "staging", f"{label} must be an array"
        )
    parsed = list(value)
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in parsed
    ) or parsed != sorted(set(parsed)):
        raise GeneratedSystemMaterializationError(
            "component_access_invalid",
            "staging",
            f"{label} must contain sorted unique positive component IDs",
        )
    return parsed


def _all_system_ids(cgs: Mapping[str, Any]) -> set[str]:
    result = {
        str(item.get("id"))
        for item in cgs.get("global_systems", [])
        if isinstance(item, dict) and item.get("id")
    }
    for mode in cgs.get("modes", []):
        if not isinstance(mode, dict):
            continue
        result.update(
            str(item.get("id"))
            for item in mode.get("systems", [])
            if isinstance(item, dict) and item.get("id")
        )
    return result


def _require_float_free(value: Any, location: str) -> None:
    if isinstance(value, float):
        raise GeneratedSystemMaterializationError(
            "materialized_float_forbidden",
            "safe_compile",
            f"{location} contains a float, which typed CGS operations forbid",
        )
    if isinstance(value, list):
        for index, item in enumerate(value):
            _require_float_free(item, f"{location}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _require_float_free(item, f"{location}.{key}")


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
