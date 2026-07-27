"""
Static mutation conflict analysis for CGS pre-commit validation.

This module checks the executable graph shape of a proposed CGS before
CGSManager.commit() can stamp and persist it. It intentionally inspects the
resulting schema, not comments or declared intent.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any


CANONICAL_PHASES = {
    "Initialization": 0,
    "Input": 1,
    "Simulation": 2,
    "PostSimulation": 3,
    "Cleanup": 4,
}

RESERVED_COMPONENT_TYPE_IDS = {
    1: "COMP_TRANSFORM_V1",
    2: "COMP_IDENTITY_V1",
    5: "COMP_VELOCITY_V1",
    6: "COMP_INPUT_V1",
    100: "COMP_HEALTH_V1",
    101: "COMP_DAMAGE_V1",
    160: "COMP_AI_V1",
    201: "COMP_INVENTORY_V1",
    205: "COMP_ITEM_V1",
    260: "COMP_INTERACTION_V1",
}

SUPPORTED_RUNTIME_EXECUTOR_KINDS = {
    "generated.increment_numeric_field",
    "generated.emit_event_on_rng_threshold",
    "plugin.set_json_field",
    "plugin.increment_numeric_field",
    "external.copy_numeric_field",
    "external.increment_numeric_field",
}

ABI_SCHEMAS = {
    "xace.runtime_executor_abi.v1",
    "xace.generated_system_abi.v1",
}

RUNTIME_SOURCE_PREFIXES = ("generated.", "plugin.", "external.")
RUNTIME_SOURCE_LABELS = {
    "generated",
    "generator",
    "llm_generated",
    "llm-generated",
    "plugin",
    "external",
}

COMPILE_ARTIFACT_SCHEMA = "xace.generated_system_compile_artifact.v1"
COMPILE_ARTIFACT_SIGNING_KEY_ID = "xace-local-generated-system-v1"
UNSUPPORTED_POLICY_HASH = (
    "3306f82262ec3e951b9d8d7de53dac45f3e69fac8b6b00d0959c89877c5e47c5"
)
COMPILE_ARTIFACT_STEPS = [
    "system_spec_validation",
    "runtime_abi_validation",
    "unsupported_api_rejection",
    "code_contract_validation",
    "determinism_static_check",
    "cargo_check_sandbox",
    "sgc_compile",
    "artifact_signature",
    "runtime_registration",
]
LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class StaticMutationFinding:
    code: str
    message: str
    severity: str = "error"
    path: str = ""
    system_ids: tuple[str, ...] = ()
    component_type_ids: tuple[int, ...] = ()

    @property
    def is_blocking(self) -> bool:
        return self.severity == "error"


@dataclass
class StaticMutationConflictReport:
    findings: list[StaticMutationFinding] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(finding.is_blocking for finding in self.findings)

    @property
    def errors(self) -> list[str]:
        return [finding.message for finding in self.findings if finding.is_blocking]

    @property
    def warnings(self) -> list[str]:
        return [finding.message for finding in self.findings if not finding.is_blocking]

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: str = "error",
        path: str = "",
        system_ids: tuple[str, ...] = (),
        component_type_ids: tuple[int, ...] = (),
    ) -> None:
        self.findings.append(
            StaticMutationFinding(
                code=code,
                message=message,
                severity=severity,
                path=path,
                system_ids=system_ids,
                component_type_ids=component_type_ids,
            )
        )


@dataclass(frozen=True)
class SystemRecord:
    system_id: str
    path: str
    scope: str
    phase: str
    reads: frozenset[int]
    writes: frozenset[int]
    depends_on: tuple[str, ...]
    deterministic: bool | None
    runtime_executor: Any
    source: str
    raw: dict[str, Any]


@dataclass
class ComponentShape:
    type_id: int
    names: set[str] = field(default_factory=set)
    defaults: dict[str, Any] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)


class StaticMutationConflictAnalyzer:
    """Validates CGS graph and ABI safety before a mutation commit."""

    def analyze(
        self,
        proposed_cgs: dict[str, Any],
        original_cgs: dict[str, Any] | None = None,
        transaction: Any | None = None,
    ) -> StaticMutationConflictReport:
        del transaction
        report = StaticMutationConflictReport()
        if not isinstance(proposed_cgs, dict):
            report.add(
                "STATIC_CGS_NOT_OBJECT",
                "[StaticMutationConflict] Proposed CGS must be a JSON object.",
            )
            return report

        components = _collect_components(proposed_cgs, report)
        systems = _collect_systems(proposed_cgs, report)
        original_systems = _systems_by_id(_collect_systems(original_cgs or {}, StaticMutationConflictReport()))

        self._check_system_component_access(systems, components, report)
        dependency_graph = self._check_dependency_graph(systems, report)
        self._check_read_write_hazards(systems, dependency_graph, report)
        if original_cgs is not None:
            self._check_component_migrations(
                _collect_components(original_cgs, StaticMutationConflictReport()),
                components,
                systems,
                report,
            )
        self._check_runtime_executor_abi(systems, original_systems, report)
        return report

    def validate(
        self,
        proposed_cgs: dict[str, Any],
        original_cgs: dict[str, Any] | None = None,
        transaction: Any | None = None,
    ) -> StaticMutationConflictReport:
        return self.analyze(proposed_cgs, original_cgs, transaction)

    @staticmethod
    def _check_system_component_access(
        systems: list[SystemRecord],
        components: dict[int, ComponentShape],
        report: StaticMutationConflictReport,
    ) -> None:
        declared = set(components) | set(RESERVED_COMPONENT_TYPE_IDS)
        for system in systems:
            for field_name, values in (("reads", system.reads), ("writes", system.writes)):
                for component_type_id in sorted(values):
                    if component_type_id not in declared:
                        report.add(
                            "STATIC_UNDECLARED_COMPONENT_ACCESS",
                            (
                                "[StaticMutationConflict] System "
                                f"'{system.system_id}' {field_name} undeclared component "
                                f"type_id {component_type_id}. Declare it in component_schemas "
                                "or attach it to an actor before committing."
                            ),
                            path=f"{system.path}.{field_name}",
                            system_ids=(system.system_id,),
                            component_type_ids=(component_type_id,),
                        )

    @staticmethod
    def _check_dependency_graph(
        systems: list[SystemRecord],
        report: StaticMutationConflictReport,
    ) -> dict[str, set[str]]:
        by_id: dict[str, SystemRecord] = {}
        graph: dict[str, set[str]] = {}
        seen_paths: dict[str, str] = {}

        for system in systems:
            if not system.system_id:
                report.add(
                    "STATIC_EMPTY_SYSTEM_ID",
                    f"[StaticMutationConflict] {system.path}.id must be non-empty.",
                    path=f"{system.path}.id",
                )
                continue
            previous = seen_paths.get(system.system_id)
            if previous:
                report.add(
                    "STATIC_DUPLICATE_SYSTEM_ID",
                    (
                        "[StaticMutationConflict] System id "
                        f"'{system.system_id}' is declared more than once "
                        f"({previous} and {system.path})."
                    ),
                    path=system.path,
                    system_ids=(system.system_id,),
                )
            seen_paths[system.system_id] = system.path
            by_id.setdefault(system.system_id, system)
            graph.setdefault(system.system_id, set(system.depends_on))

            if system.phase not in CANONICAL_PHASES:
                report.add(
                    "STATIC_INVALID_SYSTEM_PHASE",
                    (
                        "[StaticMutationConflict] System "
                        f"'{system.system_id}' uses invalid phase '{system.phase}'."
                    ),
                    path=f"{system.path}.phase",
                    system_ids=(system.system_id,),
                )

        for system in systems:
            for dependency in system.depends_on:
                if dependency == system.system_id:
                    report.add(
                        "STATIC_SELF_DEPENDENCY",
                        (
                            "[StaticMutationConflict] System "
                            f"'{system.system_id}' depends on itself."
                        ),
                        path=f"{system.path}.depends_on",
                        system_ids=(system.system_id,),
                    )
                    continue
                dependency_record = by_id.get(dependency)
                if dependency_record is None:
                    report.add(
                        "STATIC_UNKNOWN_DEPENDENCY",
                        (
                            "[StaticMutationConflict] System "
                            f"'{system.system_id}' depends on unknown system "
                            f"'{dependency}'."
                        ),
                        path=f"{system.path}.depends_on",
                        system_ids=(system.system_id, dependency),
                    )
                    continue
                if not _systems_can_share_runtime_context(system, dependency_record):
                    report.add(
                        "STATIC_DEPENDENCY_SCOPE_CONFLICT",
                        (
                            "[StaticMutationConflict] System "
                            f"'{system.system_id}' depends on '{dependency}', but the "
                            "systems are declared in different mode scopes."
                        ),
                        path=f"{system.path}.depends_on",
                        system_ids=(system.system_id, dependency),
                    )
                if _phase_index(dependency_record.phase) > _phase_index(system.phase):
                    report.add(
                        "STATIC_LATER_PHASE_DEPENDENCY",
                        (
                            "[StaticMutationConflict] System "
                            f"'{system.system_id}' depends on later-phase system "
                            f"'{dependency}'. Move the dependency earlier or the "
                            "dependent system later."
                        ),
                        path=f"{system.path}.depends_on",
                        system_ids=(system.system_id, dependency),
                    )

        _detect_cycles(graph, report)
        return graph

    @staticmethod
    def _check_read_write_hazards(
        systems: list[SystemRecord],
        dependency_graph: dict[str, set[str]],
        report: StaticMutationConflictReport,
    ) -> None:
        for index, left in enumerate(systems):
            for right in systems[index + 1:]:
                if left.phase != right.phase:
                    continue
                if not _systems_can_share_runtime_context(left, right):
                    continue
                if _has_dependency_path(left.system_id, right.system_id, dependency_graph):
                    continue
                if _has_dependency_path(right.system_id, left.system_id, dependency_graph):
                    continue

                write_write = left.writes & right.writes
                left_write_right_read = left.writes & right.reads
                right_write_left_read = right.writes & left.reads
                affected = sorted(write_write | left_write_right_read | right_write_left_read)
                if not affected:
                    continue

                report.add(
                    "STATIC_READ_WRITE_HAZARD",
                    (
                        "[StaticMutationConflict] Same-phase systems "
                        f"'{left.system_id}' and '{right.system_id}' access component "
                        f"type_ids {affected} without a dependency path. Add depends_on "
                        "ordering or move one system to another phase before committing."
                    ),
                    path=f"{left.path}|{right.path}",
                    system_ids=(left.system_id, right.system_id),
                    component_type_ids=tuple(affected),
                )

    @staticmethod
    def _check_component_migrations(
        original_components: dict[int, ComponentShape],
        proposed_components: dict[int, ComponentShape],
        systems: list[SystemRecord],
        report: StaticMutationConflictReport,
    ) -> None:
        referenced = set()
        for system in systems:
            referenced.update(system.reads)
            referenced.update(system.writes)
            referenced.update(_runtime_executor_component_ids(system.runtime_executor))

        for type_id, old_shape in sorted(original_components.items()):
            new_shape = proposed_components.get(type_id)
            if new_shape is None:
                if type_id in referenced:
                    report.add(
                        "STATIC_COMPONENT_REMOVED_WHILE_REFERENCED",
                        (
                            "[StaticMutationConflict] Component type_id "
                            f"{type_id} was removed but is still referenced by executable "
                            "systems. Remove the system access first or provide a migration."
                        ),
                        component_type_ids=(type_id,),
                    )
                continue

            old_names = {name for name in old_shape.names if name}
            new_names = {name for name in new_shape.names if name}
            if old_names and new_names and old_names.isdisjoint(new_names):
                report.add(
                    "STATIC_COMPONENT_RENAMED_IN_PLACE",
                    (
                        "[StaticMutationConflict] Component type_id "
                        f"{type_id} changed names from {sorted(old_names)} to "
                        f"{sorted(new_names)}. Allocate a new type_id or add an "
                        "explicit migration before committing."
                    ),
                    path=";".join(new_shape.paths),
                    component_type_ids=(type_id,),
                )

            if type_id not in referenced:
                continue

            for field_name, old_value in sorted(old_shape.defaults.items()):
                if field_name not in new_shape.defaults:
                    report.add(
                        "STATIC_COMPONENT_FIELD_REMOVED",
                        (
                            "[StaticMutationConflict] Referenced component type_id "
                            f"{type_id} removed default field '{field_name}'. Add an "
                            "explicit migration or update all executable systems first."
                        ),
                        path=";".join(new_shape.paths),
                        component_type_ids=(type_id,),
                    )
                    continue
                old_type = _json_shape_type(old_value)
                new_type = _json_shape_type(new_shape.defaults[field_name])
                if old_type != "null" and new_type != "null" and old_type != new_type:
                    report.add(
                        "STATIC_COMPONENT_FIELD_TYPE_CHANGED",
                        (
                            "[StaticMutationConflict] Referenced component type_id "
                            f"{type_id} field '{field_name}' changed from "
                            f"{old_type} to {new_type}. Add a compatible migration "
                            "before committing."
                        ),
                        path=";".join(new_shape.paths),
                        component_type_ids=(type_id,),
                    )

    @staticmethod
    def _check_runtime_executor_abi(
        systems: list[SystemRecord],
        original_systems: dict[str, SystemRecord],
        report: StaticMutationConflictReport,
    ) -> None:
        for system in systems:
            runtime_executor = system.runtime_executor
            kind = ""
            if isinstance(runtime_executor, dict):
                kind = str(runtime_executor.get("kind") or "").strip()
            source = system.source.strip().lower()
            requires_executor = source in RUNTIME_SOURCE_LABELS or kind.startswith(RUNTIME_SOURCE_PREFIXES)

            if requires_executor and not isinstance(runtime_executor, dict):
                report.add(
                    "STATIC_RUNTIME_EXECUTOR_MISSING",
                    (
                        "[StaticMutationConflict] System "
                        f"'{system.system_id}' is {source or 'runtime-backed'} but "
                        "does not declare runtime_executor."
                    ),
                    path=f"{system.path}.runtime_executor",
                    system_ids=(system.system_id,),
                )
                continue
            if not isinstance(runtime_executor, dict):
                continue

            changed = _system_changed(system, original_systems.get(system.system_id))
            _validate_runtime_executor(system, runtime_executor, report, changed)


def _collect_systems(cgs: dict[str, Any], report: StaticMutationConflictReport) -> list[SystemRecord]:
    systems: list[SystemRecord] = []

    def add_system(raw: Any, path: str, scope: str) -> None:
        if not isinstance(raw, dict):
            report.add(
                "STATIC_SYSTEM_NOT_OBJECT",
                f"[StaticMutationConflict] {path} must be an object.",
                path=path,
            )
            return
        reads = _int_set(raw.get("reads"), f"{path}.reads", report)
        writes = _int_set(raw.get("writes"), f"{path}.writes", report)
        systems.append(
            SystemRecord(
                system_id=str(raw.get("id") or ""),
                path=path,
                scope=scope,
                phase=str(raw.get("phase") or ""),
                reads=frozenset(reads),
                writes=frozenset(writes),
                depends_on=tuple(_string_list(raw.get("depends_on"), f"{path}.depends_on", report)),
                deterministic=raw.get("deterministic") if isinstance(raw.get("deterministic"), bool) else None,
                runtime_executor=raw.get("runtime_executor"),
                source=str(raw.get("source") or ""),
                raw=raw,
            )
        )

    global_systems = cgs.get("global_systems", [])
    if isinstance(global_systems, list):
        for index, system in enumerate(global_systems):
            add_system(system, f"global_systems[{index}]", "global")
    elif "global_systems" in cgs:
        report.add(
            "STATIC_GLOBAL_SYSTEMS_NOT_ARRAY",
            "[StaticMutationConflict] global_systems must be an array.",
            path="global_systems",
        )

    modes = cgs.get("modes", [])
    if isinstance(modes, list):
        for mode_index, mode in enumerate(modes):
            if not isinstance(mode, dict):
                continue
            mode_id = str(mode.get("id") or f"mode_index_{mode_index}")
            mode_systems = mode.get("systems", [])
            if not isinstance(mode_systems, list):
                continue
            for system_index, system in enumerate(mode_systems):
                add_system(
                    system,
                    f"modes[{mode_index}].systems[{system_index}]",
                    f"mode:{mode_id}",
                )
    return systems


def _collect_components(
    cgs: dict[str, Any],
    report: StaticMutationConflictReport,
) -> dict[int, ComponentShape]:
    components: dict[int, ComponentShape] = {}

    def add_component(raw: Any, path: str) -> None:
        if not isinstance(raw, dict):
            return
        raw_type_id = raw.get("type_id")
        if not isinstance(raw_type_id, int) or raw_type_id < 1:
            if "type_id" in raw:
                report.add(
                    "STATIC_INVALID_COMPONENT_TYPE_ID",
                    (
                        "[StaticMutationConflict] Component declaration at "
                        f"{path} has invalid type_id {raw_type_id!r}."
                    ),
                    path=f"{path}.type_id",
                )
            return
        shape = components.setdefault(raw_type_id, ComponentShape(type_id=raw_type_id))
        name = str(raw.get("name") or "").strip()
        if name:
            shape.names.add(name)
        defaults = raw.get("defaults")
        if isinstance(defaults, dict):
            for key, value in defaults.items():
                shape.defaults.setdefault(str(key), value)
        shape.paths.append(path)

    component_schemas = cgs.get("component_schemas", [])
    if isinstance(component_schemas, list):
        for index, component in enumerate(component_schemas):
            add_component(component, f"component_schemas[{index}]")

    modes = cgs.get("modes", [])
    if isinstance(modes, list):
        for mode_index, mode in enumerate(modes):
            if not isinstance(mode, dict):
                continue
            actors = mode.get("actors", [])
            if not isinstance(actors, list):
                continue
            for actor_index, actor in enumerate(actors):
                if not isinstance(actor, dict):
                    continue
                actor_components = actor.get("components", [])
                if not isinstance(actor_components, list):
                    continue
                for component_index, component in enumerate(actor_components):
                    add_component(
                        component,
                        (
                            f"modes[{mode_index}].actors[{actor_index}]"
                            f".components[{component_index}]"
                        ),
                    )
    return components


def _int_set(
    value: Any,
    path: str,
    report: StaticMutationConflictReport,
) -> set[int]:
    if not isinstance(value, list):
        report.add(
            "STATIC_ACCESS_SET_NOT_ARRAY",
            f"[StaticMutationConflict] {path} must be an array of component type IDs.",
            path=path,
        )
        return set()
    result: set[int] = set()
    for entry in value:
        if not isinstance(entry, int) or entry < 1:
            report.add(
                "STATIC_INVALID_ACCESS_COMPONENT_ID",
                (
                    "[StaticMutationConflict] "
                    f"{path} contains invalid component type_id {entry!r}."
                ),
                path=path,
            )
            continue
        if entry in result:
            report.add(
                "STATIC_DUPLICATE_ACCESS_COMPONENT_ID",
                (
                    "[StaticMutationConflict] "
                    f"{path} contains duplicate component type_id {entry}."
                ),
                path=path,
                component_type_ids=(entry,),
            )
        result.add(entry)
    return result


def _string_list(
    value: Any,
    path: str,
    report: StaticMutationConflictReport,
) -> list[str]:
    if not isinstance(value, list):
        report.add(
            "STATIC_DEPENDS_ON_NOT_ARRAY",
            f"[StaticMutationConflict] {path} must be an array of system IDs.",
            path=path,
        )
        return []
    result: list[str] = []
    seen: set[str] = set()
    for entry in value:
        item = str(entry or "").strip() if isinstance(entry, str) else ""
        if not item:
            report.add(
                "STATIC_INVALID_DEPENDENCY_ID",
                f"[StaticMutationConflict] {path} contains an empty dependency id.",
                path=path,
            )
            continue
        if item in seen:
            report.add(
                "STATIC_DUPLICATE_DEPENDENCY_ID",
                f"[StaticMutationConflict] {path} contains duplicate dependency '{item}'.",
                path=path,
            )
        seen.add(item)
        result.append(item)
    return result


def _systems_by_id(systems: list[SystemRecord]) -> dict[str, SystemRecord]:
    result: dict[str, SystemRecord] = {}
    for system in systems:
        if system.system_id:
            result.setdefault(system.system_id, system)
    return result


def _phase_index(phase: str) -> int:
    return CANONICAL_PHASES.get(phase, 10_000)


def _detect_cycles(graph: dict[str, set[str]], report: StaticMutationConflictReport) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()
    reported: set[tuple[str, ...]] = set()

    def visit(system_id: str, stack: list[str]) -> None:
        if system_id in visited:
            return
        if system_id in visiting:
            if system_id in stack:
                start = stack.index(system_id)
                cycle = tuple(stack[start:] + [system_id])
                if cycle not in reported:
                    report.add(
                        "STATIC_DEPENDENCY_CYCLE",
                        (
                            "[StaticMutationConflict] System dependency cycle "
                            f"detected: {' -> '.join(cycle)}."
                        ),
                        system_ids=cycle,
                    )
                    reported.add(cycle)
            return
        visiting.add(system_id)
        stack.append(system_id)
        for dependency in sorted(graph.get(system_id, set())):
            if dependency in graph:
                visit(dependency, stack)
        stack.pop()
        visiting.remove(system_id)
        visited.add(system_id)

    for system_id in sorted(graph):
        visit(system_id, [])


def _has_dependency_path(start: str, target: str, graph: dict[str, set[str]]) -> bool:
    pending = list(graph.get(start, set()))
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.get(current, set()))
    return False


def _systems_can_share_runtime_context(left: SystemRecord, right: SystemRecord) -> bool:
    if left.scope == "global" or right.scope == "global":
        return True
    return left.scope == right.scope


def _json_shape_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _runtime_executor_component_ids(runtime_executor: Any) -> set[int]:
    if not isinstance(runtime_executor, dict):
        return set()
    ids: set[int] = set()
    for field_name in ("component_type_id", "source_component_type_id", "target_component_type_id"):
        value = runtime_executor.get(field_name)
        if isinstance(value, int) and value > 0:
            ids.add(value)
    return ids


def _system_changed(current: SystemRecord, original: SystemRecord | None) -> bool:
    if original is None:
        return True
    return _stable_json(current.raw) != _stable_json(original.raw)


def _validate_runtime_executor(
    system: SystemRecord,
    executor: dict[str, Any],
    report: StaticMutationConflictReport,
    changed: bool,
) -> None:
    kind = str(executor.get("kind") or "").strip()
    if not kind:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_KIND_MISSING",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.kind is required."
            ),
            path=f"{system.path}.runtime_executor.kind",
            system_ids=(system.system_id,),
        )
        return
    if kind not in SUPPORTED_RUNTIME_EXECUTOR_KINDS:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_KIND_UNSUPPORTED",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.kind '{kind}' is not "
                "supported by the deterministic runtime executor ABI."
            ),
            path=f"{system.path}.runtime_executor.kind",
            system_ids=(system.system_id,),
        )
        return
    if not kind.startswith(RUNTIME_SOURCE_PREFIXES):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_SOURCE_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.kind must start with "
                "generated., plugin., or external."
            ),
            path=f"{system.path}.runtime_executor.kind",
            system_ids=(system.system_id,),
        )
    if system.deterministic is not True:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_NONDETERMINISTIC",
            (
                "[StaticMutationConflict] Runtime-backed system "
                f"'{system.system_id}' must declare deterministic=true."
            ),
            path=f"{system.path}.deterministic",
            system_ids=(system.system_id,),
        )

    expected = _expected_runtime_executor_abi(system, executor, report)
    if expected is None:
        return

    abi = executor.get("abi")
    if not isinstance(abi, dict):
        if changed and kind != "generated.increment_numeric_field":
            report.add(
                "STATIC_RUNTIME_EXECUTOR_ABI_MISSING",
                (
                    "[StaticMutationConflict] New or changed runtime-backed "
                    f"system '{system.system_id}' must include an explicit "
                    "runtime_executor.abi block."
                ),
                path=f"{system.path}.runtime_executor.abi",
                system_ids=(system.system_id,),
            )
        if "compile_artifact" in executor:
            report.add(
                "STATIC_COMPILE_ARTIFACT_ABI_MISSING",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' compile_artifact requires an explicit "
                    "runtime_executor.abi block."
                ),
                path=f"{system.path}.runtime_executor.compile_artifact",
                system_ids=(system.system_id,),
            )
        return

    _validate_explicit_abi(system, abi, expected, report)
    if "compile_artifact" in executor:
        _validate_compile_artifact(system, executor, report)


def _expected_runtime_executor_abi(
    system: SystemRecord,
    executor: dict[str, Any],
    report: StaticMutationConflictReport,
) -> dict[str, Any] | None:
    kind = str(executor.get("kind") or "").strip()

    if kind in {
        "generated.increment_numeric_field",
        "plugin.increment_numeric_field",
        "external.increment_numeric_field",
    }:
        component_type_id = _required_u32(executor, "component_type_id", system, report)
        field_name = _required_field_name(executor, "field", system, report)
        _required_finite_number(executor, "amount", system, report)
        if component_type_id is None or field_name is None:
            return None
        _require_access(system, component_type_id, read=True, write=True, report=report)
        return {
            "inputs": {
                "query_components": [component_type_id],
                "component_reads": [component_type_id],
                "current_tick": False,
            },
            "events": {"emits": []},
            "rng": {"allowed": False, "max_calls_per_entity": 0},
        }

    if kind == "plugin.set_json_field":
        component_type_id = _required_u32(executor, "component_type_id", system, report)
        field_name = _required_field_name(executor, "field", system, report)
        if "value" not in executor or not _is_scalar_json(executor.get("value")):
            report.add(
                "STATIC_RUNTIME_EXECUTOR_VALUE_INVALID",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' runtime_executor.value must be a "
                    "scalar JSON value."
                ),
                path=f"{system.path}.runtime_executor.value",
                system_ids=(system.system_id,),
            )
        if component_type_id is None or field_name is None:
            return None
        _require_access(system, component_type_id, read=True, write=True, report=report)
        return {
            "inputs": {
                "query_components": [component_type_id],
                "component_reads": [component_type_id],
                "current_tick": False,
            },
            "events": {"emits": []},
            "rng": {"allowed": False, "max_calls_per_entity": 0},
        }

    if kind == "external.copy_numeric_field":
        source_component = _required_u32(executor, "source_component_type_id", system, report)
        target_component = _required_u32(executor, "target_component_type_id", system, report)
        _required_field_name(executor, "source_field", system, report)
        _required_field_name(executor, "target_field", system, report)
        if "scale" in executor:
            _required_finite_number(executor, "scale", system, report)
        if "offset" in executor:
            _required_finite_number(executor, "offset", system, report)
        if source_component is None or target_component is None:
            return None
        _require_access(system, source_component, read=True, write=False, report=report)
        _require_access(system, target_component, read=True, write=True, report=report)
        components = sorted({source_component, target_component})
        return {
            "inputs": {
                "query_components": components,
                "component_reads": components,
                "current_tick": False,
            },
            "events": {"emits": []},
            "rng": {"allowed": False, "max_calls_per_entity": 0},
        }

    if kind == "generated.emit_event_on_rng_threshold":
        component_type_id = _required_u32(executor, "component_type_id", system, report)
        chance = _required_finite_number(executor, "chance", system, report)
        event_type = str(executor.get("event_type") or "").strip()
        if chance is not None and (chance < 0.0 or chance > 1.0):
            report.add(
                "STATIC_RUNTIME_EXECUTOR_CHANCE_INVALID",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' runtime_executor.chance must be between 0 and 1."
                ),
                path=f"{system.path}.runtime_executor.chance",
                system_ids=(system.system_id,),
            )
        if not event_type:
            report.add(
                "STATIC_RUNTIME_EXECUTOR_EVENT_TYPE_MISSING",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' runtime_executor.event_type is required."
                ),
                path=f"{system.path}.runtime_executor.event_type",
                system_ids=(system.system_id,),
            )
        payload = _payload_as_strings(executor.get("payload"), system, report)
        if component_type_id is None or not event_type:
            return None
        _require_access(system, component_type_id, read=True, write=False, report=report)
        return {
            "inputs": {
                "query_components": [component_type_id],
                "component_reads": [component_type_id],
                "current_tick": True,
            },
            "events": {
                "emits": [{
                    "event_type": event_type,
                    "broadcast": True,
                    "payload": payload,
                }],
            },
            "rng": {"allowed": True, "max_calls_per_entity": 1},
        }

    return None


def _required_u32(
    executor: dict[str, Any],
    key: str,
    system: SystemRecord,
    report: StaticMutationConflictReport,
) -> int | None:
    value = executor.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 0xFFFF_FFFF:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_COMPONENT_ID_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.{key} must be a positive u32."
            ),
            path=f"{system.path}.runtime_executor.{key}",
            system_ids=(system.system_id,),
        )
        return None
    return value


def _required_field_name(
    executor: dict[str, Any],
    key: str,
    system: SystemRecord,
    report: StaticMutationConflictReport,
) -> str | None:
    field_name = str(executor.get(key) or "").strip()
    if not field_name or "." in field_name:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_FIELD_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.{key} must be a "
                "non-empty top-level JSON object field."
            ),
            path=f"{system.path}.runtime_executor.{key}",
            system_ids=(system.system_id,),
        )
        return None
    return field_name


def _required_finite_number(
    executor: dict[str, Any],
    key: str,
    system: SystemRecord,
    report: StaticMutationConflictReport,
) -> float | None:
    value = executor.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_NUMBER_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.{key} must be a finite number."
            ),
            path=f"{system.path}.runtime_executor.{key}",
            system_ids=(system.system_id,),
        )
        return None
    return float(value)


def _require_access(
    system: SystemRecord,
    component_type_id: int,
    *,
    read: bool,
    write: bool,
    report: StaticMutationConflictReport,
) -> None:
    if read and component_type_id not in system.reads:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_READ_MISSING",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor component type_id "
                f"{component_type_id} must be declared in reads."
            ),
            path=f"{system.path}.reads",
            system_ids=(system.system_id,),
            component_type_ids=(component_type_id,),
        )
    if write and component_type_id not in system.writes:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_WRITE_MISSING",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor component type_id "
                f"{component_type_id} must be declared in writes."
            ),
            path=f"{system.path}.writes",
            system_ids=(system.system_id,),
            component_type_ids=(component_type_id,),
        )


def _validate_explicit_abi(
    system: SystemRecord,
    abi: dict[str, Any],
    expected: dict[str, Any],
    report: StaticMutationConflictReport,
) -> None:
    schema = str(abi.get("schema") or "").strip()
    if schema not in ABI_SCHEMAS:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_SCHEMA_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.abi.schema must be one "
                f"of {sorted(ABI_SCHEMAS)}."
            ),
            path=f"{system.path}.runtime_executor.abi.schema",
            system_ids=(system.system_id,),
        )
    if abi.get("version") != 1:
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_VERSION_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.abi.version must be 1."
            ),
            path=f"{system.path}.runtime_executor.abi.version",
            system_ids=(system.system_id,),
        )

    inputs = abi.get("inputs")
    if not isinstance(inputs, dict):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_INPUTS_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.abi.inputs must be an object."
            ),
            path=f"{system.path}.runtime_executor.abi.inputs",
            system_ids=(system.system_id,),
        )
    else:
        query_components = _abi_u32_list(inputs.get("query_components"))
        component_reads = _abi_u32_list(inputs.get("component_reads"))
        current_tick = inputs.get("current_tick")
        expected_inputs = expected["inputs"]
        if query_components != expected_inputs["query_components"]:
            report.add(
                "STATIC_RUNTIME_EXECUTOR_ABI_QUERY_MISMATCH",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' ABI query_components does not match "
                    "runtime_executor inputs."
                ),
                path=f"{system.path}.runtime_executor.abi.inputs.query_components",
                system_ids=(system.system_id,),
            )
        if component_reads != expected_inputs["component_reads"]:
            report.add(
                "STATIC_RUNTIME_EXECUTOR_ABI_READ_MISMATCH",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' ABI component_reads does not match "
                    "runtime_executor reads."
                ),
                path=f"{system.path}.runtime_executor.abi.inputs.component_reads",
                system_ids=(system.system_id,),
            )
        if current_tick is not expected_inputs["current_tick"]:
            report.add(
                "STATIC_RUNTIME_EXECUTOR_ABI_TICK_MISMATCH",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' ABI current_tick does not match "
                    "runtime_executor tick usage."
                ),
                path=f"{system.path}.runtime_executor.abi.inputs.current_tick",
                system_ids=(system.system_id,),
            )

    rng = abi.get("rng")
    expected_rng = expected["rng"]
    if not isinstance(rng, dict):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_RNG_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.abi.rng must be an object."
            ),
            path=f"{system.path}.runtime_executor.abi.rng",
            system_ids=(system.system_id,),
        )
    elif (
        rng.get("allowed") is not expected_rng["allowed"]
        or rng.get("max_calls_per_entity") != expected_rng["max_calls_per_entity"]
    ):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_RNG_MISMATCH",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' ABI rng does not match runtime_executor RNG usage."
            ),
            path=f"{system.path}.runtime_executor.abi.rng",
            system_ids=(system.system_id,),
        )

    _validate_abi_events(system, abi.get("events"), expected["events"], report)

    errors = abi.get("errors")
    if not isinstance(errors, dict) or errors.get("policy") != "halt_and_rollback":
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_ERROR_POLICY_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.abi.errors.policy must "
                "be halt_and_rollback."
            ),
            path=f"{system.path}.runtime_executor.abi.errors",
            system_ids=(system.system_id,),
        )

    rollback = abi.get("rollback")
    expected_hooks = {
        "mutation_hook": "mutation_gate_deferred",
        "event_hook": "event_bus_phase_buffered",
        "rng_hook": "rng_windowed",
    }
    if not isinstance(rollback, dict):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_ROLLBACK_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.abi.rollback must be an object."
            ),
            path=f"{system.path}.runtime_executor.abi.rollback",
            system_ids=(system.system_id,),
        )
    else:
        for key, expected_value in expected_hooks.items():
            if rollback.get(key) != expected_value:
                report.add(
                    "STATIC_RUNTIME_EXECUTOR_ABI_ROLLBACK_HOOK_INVALID",
                    (
                        "[StaticMutationConflict] System "
                        f"'{system.system_id}' runtime_executor.abi.rollback.{key} "
                        f"must be {expected_value}."
                    ),
                    path=f"{system.path}.runtime_executor.abi.rollback.{key}",
                    system_ids=(system.system_id,),
                )


def _validate_abi_events(
    system: SystemRecord,
    events: Any,
    expected_events: dict[str, Any],
    report: StaticMutationConflictReport,
) -> None:
    if not isinstance(events, dict) or not isinstance(events.get("emits"), list):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_EVENTS_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.abi.events.emits must be an array."
            ),
            path=f"{system.path}.runtime_executor.abi.events",
            system_ids=(system.system_id,),
        )
        return
    actual = events["emits"]
    expected = expected_events["emits"]
    if len(actual) != len(expected):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_ABI_EVENTS_MISMATCH",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' ABI events.emits does not match "
                "runtime_executor event declarations."
            ),
            path=f"{system.path}.runtime_executor.abi.events.emits",
            system_ids=(system.system_id,),
        )
        return
    for index, expected_event in enumerate(expected):
        event = actual[index]
        if not isinstance(event, dict):
            report.add(
                "STATIC_RUNTIME_EXECUTOR_ABI_EVENT_INVALID",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' ABI events.emits[{index}] must be an object."
                ),
                path=f"{system.path}.runtime_executor.abi.events.emits[{index}]",
                system_ids=(system.system_id,),
            )
            continue
        payload = _payload_as_strings(event.get("payload"), system, report)
        if (
            event.get("event_type") != expected_event["event_type"]
            or event.get("broadcast") is not expected_event["broadcast"]
            or payload != expected_event["payload"]
        ):
            report.add(
                "STATIC_RUNTIME_EXECUTOR_ABI_EVENT_MISMATCH",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' ABI event declaration does not match "
                    "runtime_executor event output."
                ),
                path=f"{system.path}.runtime_executor.abi.events.emits[{index}]",
                system_ids=(system.system_id,),
            )


def _validate_compile_artifact(
    system: SystemRecord,
    executor: dict[str, Any],
    report: StaticMutationConflictReport,
) -> None:
    artifact = executor.get("compile_artifact")
    if not isinstance(artifact, dict):
        report.add(
            "STATIC_COMPILE_ARTIFACT_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor.compile_artifact must be an object."
            ),
            path=f"{system.path}.runtime_executor.compile_artifact",
            system_ids=(system.system_id,),
        )
        return

    required_strings = {
        "schema": COMPILE_ARTIFACT_SCHEMA,
        "system_id": system.system_id,
        "signing_key_id": COMPILE_ARTIFACT_SIGNING_KEY_ID,
        "unsupported_policy_hash": UNSUPPORTED_POLICY_HASH,
    }
    for key, expected in required_strings.items():
        if artifact.get(key) != expected:
            report.add(
                "STATIC_COMPILE_ARTIFACT_FIELD_INVALID",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' compile_artifact.{key} must be {expected}."
                ),
                path=f"{system.path}.runtime_executor.compile_artifact.{key}",
                system_ids=(system.system_id,),
            )

    for key in (
        "cgs_hash",
        "source_hash",
        "runtime_executor_hash",
        "abi_hash",
        "sgc_plan_hash",
        "sandbox_hash",
        "signature",
    ):
        value = artifact.get(key)
        if not isinstance(value, str) or LOWER_HEX_64.fullmatch(value) is None:
            report.add(
                "STATIC_COMPILE_ARTIFACT_HASH_INVALID",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' compile_artifact.{key} must be a "
                    "lowercase 64-character SHA-256 digest."
                ),
                path=f"{system.path}.runtime_executor.compile_artifact.{key}",
                system_ids=(system.system_id,),
            )

    if artifact.get("validation_steps") != COMPILE_ARTIFACT_STEPS:
        report.add(
            "STATIC_COMPILE_ARTIFACT_STEPS_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' compile_artifact.validation_steps does "
                "not match the safe-compile gate order."
            ),
            path=f"{system.path}.runtime_executor.compile_artifact.validation_steps",
            system_ids=(system.system_id,),
        )

    abi = executor.get("abi")
    if isinstance(abi, dict):
        expected_abi_hash = _sha256(_stable_json(abi).encode("utf-8"))
        if artifact.get("abi_hash") != expected_abi_hash:
            report.add(
                "STATIC_COMPILE_ARTIFACT_ABI_HASH_MISMATCH",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' compile_artifact.abi_hash does not "
                    "match runtime_executor.abi."
                ),
                path=f"{system.path}.runtime_executor.compile_artifact.abi_hash",
                system_ids=(system.system_id,),
            )

    executor_without_artifact = copy.deepcopy(executor)
    executor_without_artifact.pop("compile_artifact", None)
    expected_executor_hash = _sha256(_stable_json(executor_without_artifact).encode("utf-8"))
    if artifact.get("runtime_executor_hash") != expected_executor_hash:
        report.add(
            "STATIC_COMPILE_ARTIFACT_EXECUTOR_HASH_MISMATCH",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' compile_artifact.runtime_executor_hash "
                "does not match runtime_executor."
            ),
            path=f"{system.path}.runtime_executor.compile_artifact.runtime_executor_hash",
            system_ids=(system.system_id,),
        )

    signature = _compile_artifact_signature(artifact)
    if signature and artifact.get("signature") != signature:
        report.add(
            "STATIC_COMPILE_ARTIFACT_SIGNATURE_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' compile_artifact.signature does not verify."
            ),
            path=f"{system.path}.runtime_executor.compile_artifact.signature",
            system_ids=(system.system_id,),
        )


def _abi_u32_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    parsed = [
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    ]
    return sorted(set(parsed))


def _payload_as_strings(
    value: Any,
    system: SystemRecord,
    report: StaticMutationConflictReport,
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        report.add(
            "STATIC_RUNTIME_EXECUTOR_PAYLOAD_INVALID",
            (
                "[StaticMutationConflict] System "
                f"'{system.system_id}' runtime_executor payload must be an object."
            ),
            path=f"{system.path}.runtime_executor.payload",
            system_ids=(system.system_id,),
        )
        return {}
    payload: dict[str, str] = {}
    for key, raw in value.items():
        if not _is_scalar_json(raw):
            report.add(
                "STATIC_RUNTIME_EXECUTOR_PAYLOAD_VALUE_INVALID",
                (
                    "[StaticMutationConflict] System "
                    f"'{system.system_id}' runtime_executor payload field "
                    f"'{key}' must be scalar."
                ),
                path=f"{system.path}.runtime_executor.payload.{key}",
                system_ids=(system.system_id,),
            )
            continue
        if isinstance(raw, bool):
            payload[str(key)] = str(raw).lower()
        else:
            payload[str(key)] = str(raw)
    return payload


def _is_scalar_json(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _compile_artifact_signature(artifact: dict[str, Any]) -> str:
    fields = [
        "schema",
        "system_id",
        "cgs_hash",
        "source_hash",
        "runtime_executor_hash",
        "abi_hash",
        "sgc_plan_hash",
        "unsupported_policy_hash",
        "sandbox_hash",
        "signing_key_id",
    ]
    lines: list[str] = []
    for field_name in fields:
        value = artifact.get(field_name)
        if not isinstance(value, str) or not value:
            return ""
        lines.append(f"{field_name}={value}")
    steps = artifact.get("validation_steps")
    if not isinstance(steps, list):
        return ""
    lines.append("validation_steps=" + ",".join(str(step) for step in steps))
    return _sha256("\n".join(lines).encode("utf-8"))
