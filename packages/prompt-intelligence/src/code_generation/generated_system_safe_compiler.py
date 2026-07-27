"""
generated_system_safe_compiler.py - Safe generated-system compile gate.

This module routes generated Rust gameplay systems through the required local
launch gates before a runtime executor may be treated as a generated-code
artifact:

1. CGS/SystemSpec validation
2. runtime_executor ABI validation
3. generated-code contract validation
4. deterministic static checks
5. cargo check in an isolated temporary project
6. real SGC compilation
7. deterministic local artifact signing

The runtime independently verifies the signed compile artifact before
registering generated-code-backed executors.
"""

from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from cargo_compiler import CargoCompiler, CompileResult  # noqa: E402
from code_contract_validator import (  # noqa: E402
    CodeContractValidator,
    ContractValidationResult,
)
from determinism_code_checker import DeterminismCodeChecker, DeterminismReport  # noqa: E402
from system_spec_builder import SystemSpec, SystemSpecBuilder  # noqa: E402
from unsupported_generated_system_guard import (  # noqa: E402
    UnsupportedGeneratedSystemReport,
    check_unsupported_generated_system,
    unsupported_policy_hash,
)


GENERATED_SYSTEM_COMPILE_ARTIFACT_SCHEMA = "xace.generated_system_compile_artifact.v1"
GENERATED_SYSTEM_ABI_SCHEMA = "xace.generated_system_abi.v1"
GENERATED_SYSTEM_ABI_VERSION = 1
GENERATED_SYSTEM_UNSUPPORTED_POLICY_HASH = unsupported_policy_hash()
GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND = "generated.increment_numeric_field"
GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND = "generated.emit_event_on_rng_threshold"
LOCAL_SIGNING_KEY_ID = "xace-local-generated-system-v1"
REQUIRED_VALIDATION_STEPS = (
    "system_spec_validation",
    "runtime_abi_validation",
    "unsupported_api_rejection",
    "code_contract_validation",
    "determinism_static_check",
    "cargo_check_sandbox",
    "sgc_compile",
    "artifact_signature",
    "runtime_registration",
)


@dataclass
class SgcCompileResult:
    passed: bool
    plan: dict[str, Any] = field(default_factory=dict)
    plan_hash: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error: str = ""


@dataclass
class SafeGeneratedSystemCompileResult:
    system_id: str
    succeeded: bool
    stage: str = ""
    error: str = ""
    spec: SystemSpec | None = None
    contract_result: ContractValidationResult | None = None
    determinism_report: DeterminismReport | None = None
    unsupported_report: UnsupportedGeneratedSystemReport | None = None
    compile_result: CompileResult | None = None
    sgc_result: SgcCompileResult | None = None
    compile_artifact: dict[str, Any] = field(default_factory=dict)
    signed_runtime_executor: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.succeeded


class GeneratedSystemSafeCompiler:
    """Validates, compiles, SGC-checks, signs, and prepares runtime registration."""

    def __init__(self, *, sgc_bin: str | Path = "") -> None:
        self._spec_builder = SystemSpecBuilder()
        self._contract_validator = CodeContractValidator()
        self._determinism_checker = DeterminismCodeChecker()
        self._cargo_compiler = CargoCompiler()
        self._sgc_bin = Path(sgc_bin).resolve() if sgc_bin is not None and str(sgc_bin).strip() else None

    def compile(
        self,
        *,
        system_id: str,
        cgs: dict[str, Any],
        rust_source: str,
        mode_id: str = "",
        description: str = "",
        max_entities: int = 1000,
        tick_budget_us: int = 100,
        sgc_bin: str | Path = "",
    ) -> SafeGeneratedSystemCompileResult:
        spec = self._spec_builder.build(
            system_id=system_id,
            cgs=cgs,
            mode_id=mode_id,
            description=description,
            max_entities=max_entities,
            tick_budget_us=tick_budget_us,
        )
        if not spec.is_valid:
            return self._failure(
                system_id,
                "system_spec_validation",
                "; ".join(spec.validation_errors),
                spec=spec,
            )

        system = _find_system(cgs, system_id, mode_id)
        if system is None:
            return self._failure(system_id, "system_spec_validation", "system not found", spec=spec)

        runtime_executor = system.get("runtime_executor")
        try:
            _validate_runtime_executor_abi(system_id, runtime_executor, spec)
        except ValueError as exc:
            return self._failure(system_id, "runtime_abi_validation", str(exc), spec=spec)

        unsupported_report = check_unsupported_generated_system(rust_source)
        if not unsupported_report.passed:
            return self._failure(
                system_id,
                "unsupported_api_rejection",
                unsupported_report.summary(),
                spec=spec,
                unsupported_report=unsupported_report,
            )

        contract_result = self._contract_validator.validate(rust_source, spec)
        if not contract_result.passed:
            return self._failure(
                system_id,
                "code_contract_validation",
                "; ".join(contract_result.all_descriptions),
                spec=spec,
                unsupported_report=unsupported_report,
                contract_result=contract_result,
            )

        determinism_report = self._determinism_checker.check(rust_source)
        if not determinism_report.passed:
            return self._failure(
                system_id,
                "determinism_static_check",
                "; ".join(determinism_report.all_descriptions),
                spec=spec,
                unsupported_report=unsupported_report,
                contract_result=contract_result,
                determinism_report=determinism_report,
            )

        compile_result = self._cargo_compiler.compile(rust_source, spec)
        if not compile_result.cargo_available:
            return self._failure(
                system_id,
                "cargo_check_sandbox",
                "cargo is required for safe generated-system compilation",
                spec=spec,
                unsupported_report=unsupported_report,
                contract_result=contract_result,
                determinism_report=determinism_report,
                compile_result=compile_result,
            )
        if not compile_result.passed:
            return self._failure(
                system_id,
                "cargo_check_sandbox",
                compile_result.formatted_errors(),
                spec=spec,
                unsupported_report=unsupported_report,
                contract_result=contract_result,
                determinism_report=determinism_report,
                compile_result=compile_result,
            )

        sgc_result = _run_sgc_compile(
            cgs,
            Path(sgc_bin).resolve() if sgc_bin is not None and str(sgc_bin).strip() else self._sgc_bin,
        )
        if not sgc_result.passed:
            return self._failure(
                system_id,
                "sgc_compile",
                sgc_result.error,
                spec=spec,
                unsupported_report=unsupported_report,
                contract_result=contract_result,
                determinism_report=determinism_report,
                compile_result=compile_result,
                sgc_result=sgc_result,
            )
        if system_id not in _plan_system_ids(sgc_result.plan):
            return self._failure(
                system_id,
                "sgc_compile",
                f"SGC plan did not contain generated system '{system_id}'",
                spec=spec,
                unsupported_report=unsupported_report,
                contract_result=contract_result,
                determinism_report=determinism_report,
                compile_result=compile_result,
                sgc_result=sgc_result,
            )

        runtime_executor_copy = copy.deepcopy(runtime_executor)
        runtime_executor_copy.pop("compile_artifact", None)
        compile_artifact = build_compile_artifact(
            system_id=system_id,
            cgs_hash=_cgs_hash(cgs),
            rust_source=rust_source,
            runtime_executor=runtime_executor_copy,
            sgc_plan_hash=sgc_result.plan_hash,
            unsupported_policy_hash=unsupported_report.policy_hash,
            cargo_duration_ms=compile_result.duration_ms,
            cargo_warnings=compile_result.warnings_count,
        )
        signed_runtime_executor = copy.deepcopy(runtime_executor_copy)
        signed_runtime_executor["compile_artifact"] = compile_artifact

        return SafeGeneratedSystemCompileResult(
            system_id=system_id,
            succeeded=True,
            stage="runtime_registration",
            spec=spec,
            contract_result=contract_result,
            determinism_report=determinism_report,
            unsupported_report=unsupported_report,
            compile_result=compile_result,
            sgc_result=sgc_result,
            compile_artifact=compile_artifact,
            signed_runtime_executor=signed_runtime_executor,
            warnings=contract_result.warnings + determinism_report.warnings,
        )

    @staticmethod
    def _failure(
        system_id: str,
        stage: str,
        error: str,
        *,
        spec: SystemSpec | None = None,
        contract_result: ContractValidationResult | None = None,
        determinism_report: DeterminismReport | None = None,
        unsupported_report: UnsupportedGeneratedSystemReport | None = None,
        compile_result: CompileResult | None = None,
        sgc_result: SgcCompileResult | None = None,
    ) -> SafeGeneratedSystemCompileResult:
        return SafeGeneratedSystemCompileResult(
            system_id=system_id,
            succeeded=False,
            stage=stage,
            error=error,
            spec=spec,
            contract_result=contract_result,
            determinism_report=determinism_report,
            unsupported_report=unsupported_report,
            compile_result=compile_result,
            sgc_result=sgc_result,
        )


def build_compile_artifact(
    *,
    system_id: str,
    cgs_hash: str,
    rust_source: str,
    runtime_executor: dict[str, Any],
    sgc_plan_hash: str,
    unsupported_policy_hash: str = GENERATED_SYSTEM_UNSUPPORTED_POLICY_HASH,
    cargo_duration_ms: float = 0.0,
    cargo_warnings: int = 0,
) -> dict[str, Any]:
    runtime_executor_without_artifact = copy.deepcopy(runtime_executor)
    runtime_executor_without_artifact.pop("compile_artifact", None)
    abi = runtime_executor_without_artifact.get("abi")
    artifact = {
        "schema": GENERATED_SYSTEM_COMPILE_ARTIFACT_SCHEMA,
        "system_id": system_id,
        "cgs_hash": cgs_hash,
        "source_hash": _sha256_text(rust_source),
        "runtime_executor_hash": _sha256_json(runtime_executor_without_artifact),
        "abi_hash": _sha256_json(abi),
        "sgc_plan_hash": sgc_plan_hash,
        "unsupported_policy_hash": unsupported_policy_hash,
        "sandbox_hash": _sha256_json(
            {
                "policy": "cargo_check_temp_project_no_workspace_writes",
                "system_id": system_id,
                "source_hash": _sha256_text(rust_source),
            }
        ),
        "validation_steps": list(REQUIRED_VALIDATION_STEPS),
        "cargo": {
            "sandbox": "temp_cargo_project_no_workspace_writes",
            "duration_ms": round(float(cargo_duration_ms), 3),
            "warnings": int(cargo_warnings),
        },
        "signing_key_id": LOCAL_SIGNING_KEY_ID,
    }
    artifact["signature"] = sign_compile_artifact(artifact)
    return artifact


def sign_compile_artifact(artifact: dict[str, Any]) -> str:
    return _sha256_text(_signature_material(artifact))


def validate_compile_artifact_signature(artifact: dict[str, Any]) -> bool:
    return str(artifact.get("signature") or "") == sign_compile_artifact(artifact)


def _signature_material(artifact: dict[str, Any]) -> str:
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
    lines = [f"{field}={artifact.get(field, '')}" for field in fields]
    steps = artifact.get("validation_steps") if isinstance(artifact.get("validation_steps"), list) else []
    lines.append("validation_steps=" + ",".join(str(step) for step in steps))
    return "\n".join(lines)


def _validate_runtime_executor_abi(
    system_id: str,
    runtime_executor: Any,
    spec: SystemSpec,
) -> None:
    if not isinstance(runtime_executor, dict):
        raise ValueError("runtime_executor must be an object for safe generated-system compilation")
    kind = str(runtime_executor.get("kind") or "").strip()
    if kind not in {
        GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND,
        GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND,
    }:
        raise ValueError(f"runtime_executor.kind '{kind}' is not supported")
    abi = runtime_executor.get("abi")
    if not isinstance(abi, dict):
        raise ValueError("runtime_executor.abi is required for safe generated-system compilation")
    if abi.get("schema") != GENERATED_SYSTEM_ABI_SCHEMA:
        raise ValueError(f"runtime_executor.abi.schema must be '{GENERATED_SYSTEM_ABI_SCHEMA}'")
    if abi.get("version") != GENERATED_SYSTEM_ABI_VERSION:
        raise ValueError(f"runtime_executor.abi.version must be {GENERATED_SYSTEM_ABI_VERSION}")
    if not isinstance(abi.get("inputs"), dict):
        raise ValueError("runtime_executor.abi.inputs must be an object")
    if not isinstance(abi.get("events"), dict):
        raise ValueError("runtime_executor.abi.events must be an object")
    if not isinstance(abi.get("rng"), dict):
        raise ValueError("runtime_executor.abi.rng must be an object")
    if (abi.get("errors") or {}).get("policy") != "halt_and_rollback":
        raise ValueError("runtime_executor.abi.errors.policy must be 'halt_and_rollback'")
    rollback = abi.get("rollback") or {}
    expected_hooks = {
        "mutation_hook": "mutation_gate_deferred",
        "event_hook": "event_bus_phase_buffered",
        "rng_hook": "rng_windowed",
    }
    for key, expected in expected_hooks.items():
        if rollback.get(key) != expected:
            raise ValueError(f"runtime_executor.abi.rollback.{key} must be '{expected}'")

    component_type_id = _positive_int(runtime_executor.get("component_type_id"), "component_type_id")
    if component_type_id not in set(spec.read_type_ids) | set(spec.write_type_ids):
        raise ValueError("runtime_executor.component_type_id must be declared in reads or writes")

    inputs = abi["inputs"]
    query_components = _u32_list(inputs.get("query_components"))
    component_reads = _u32_list(inputs.get("component_reads"))
    if query_components != [component_type_id] or component_reads != [component_type_id]:
        raise ValueError("runtime_executor.abi.inputs must match component_type_id")

    if kind == GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND:
        if component_type_id not in spec.write_type_ids:
            raise ValueError("increment executor component_type_id must be declared in writes")
        field = str(runtime_executor.get("field") or "").strip()
        if not field or "." in field:
            raise ValueError("increment executor field must be a non-empty top-level field")
        amount = runtime_executor.get("amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(float(amount)):
            raise ValueError("increment executor amount must be finite")
        if inputs.get("current_tick") is not False:
            raise ValueError("increment executor ABI must not require current_tick")
        if abi["rng"].get("allowed") is not False or abi["rng"].get("max_calls_per_entity") != 0:
            raise ValueError("increment executor ABI must declare no RNG")
        if abi["events"].get("emits") != []:
            raise ValueError("increment executor ABI must declare no emitted events")
        return

    chance = runtime_executor.get("chance")
    if not isinstance(chance, (int, float)) or isinstance(chance, bool) or not (0.0 <= float(chance) <= 1.0):
        raise ValueError("RNG event executor chance must be between 0.0 and 1.0")
    event_type = str(runtime_executor.get("event_type") or "").strip()
    if not event_type:
        raise ValueError("RNG event executor event_type is required")
    if inputs.get("current_tick") is not True:
        raise ValueError("RNG event executor ABI must require current_tick")
    if abi["rng"].get("allowed") is not True or abi["rng"].get("max_calls_per_entity") != 1:
        raise ValueError("RNG event executor ABI must declare one RNG call per entity")
    emits = abi["events"].get("emits")
    if not isinstance(emits, list) or len(emits) != 1:
        raise ValueError("RNG event executor ABI must declare exactly one emitted event")
    if emits[0].get("event_type") != event_type or emits[0].get("broadcast") is not True:
        raise ValueError("RNG event executor ABI event declaration does not match executor")


def _run_sgc_compile(cgs: dict[str, Any], sgc_bin: Path | None) -> SgcCompileResult:
    if sgc_bin is None:
        return SgcCompileResult(False, error="SGC binary path is required")
    if not sgc_bin.exists():
        return SgcCompileResult(False, error=f"SGC binary not found: {sgc_bin}")
    payload = _sgc_input(cgs)
    completed = subprocess.run(
        [str(sgc_bin)],
        input=_canonical_json(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return SgcCompileResult(
            passed=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            error=(completed.stderr or completed.stdout)[-2000:],
        )
    try:
        plan = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return SgcCompileResult(
            passed=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            error=f"SGC stdout was not JSON: {exc}",
        )
    plan_hash = str(plan.get("plan_hash") or "")
    if not _is_hex64(plan_hash):
        return SgcCompileResult(False, plan=plan, error="SGC plan_hash missing or invalid")
    return SgcCompileResult(
        passed=True,
        plan=plan,
        plan_hash=plan_hash,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def _sgc_input(cgs: dict[str, Any]) -> dict[str, Any]:
    metadata = cgs.get("metadata") if isinstance(cgs.get("metadata"), dict) else {}
    systems = []
    for system in _all_systems(cgs):
        systems.append(
            {
                "id": str(system.get("id") or ""),
                "phase": system.get("phase") or "Simulation",
                "reads": sorted({int(value) for value in system.get("reads", [])}),
                "writes": sorted({int(value) for value in system.get("writes", [])}),
                "depends_on": sorted({str(value) for value in system.get("depends_on", [])}),
                "deterministic": bool(system.get("deterministic", True)),
                "version_major": int((system.get("version") or {}).get("major", 1))
                if isinstance(system.get("version"), dict)
                else 1,
                "version_minor": int((system.get("version") or {}).get("minor", 0))
                if isinstance(system.get("version"), dict)
                else 0,
                "description": str(system.get("description") or ""),
            }
        )
    return {
        "schema": "xace.sgc.cli.input.v1",
        "schema_version": str(metadata.get("schema_version") or metadata.get("version") or "0.1.0"),
        "plan_version": int(metadata.get("execution_plan_version") or 1),
        "cgs_hash": _cgs_hash(cgs),
        "systems": systems,
    }


def _find_system(cgs: dict[str, Any], system_id: str, mode_id: str = "") -> dict[str, Any] | None:
    for system in cgs.get("global_systems", []):
        if system.get("id") == system_id:
            return system
    for mode in cgs.get("modes", []):
        if mode_id and mode.get("id") != mode_id:
            continue
        for system in mode.get("systems", []):
            if system.get("id") == system_id:
                return system
    return None


def _all_systems(cgs: dict[str, Any]) -> list[dict[str, Any]]:
    systems = list(cgs.get("global_systems", []))
    for mode in cgs.get("modes", []):
        systems.extend(mode.get("systems", []))
    return systems


def _plan_system_ids(plan: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    phases = plan.get("phases") if isinstance(plan.get("phases"), dict) else {}
    for phase in phases.values():
        if not isinstance(phase, dict):
            continue
        for group in phase.get("groups", []):
            if isinstance(group, dict):
                ids.update(str(system_id) for system_id in group.get("systems", []))
    return ids


def _cgs_hash(cgs: dict[str, Any]) -> str:
    metadata = cgs.get("metadata") if isinstance(cgs.get("metadata"), dict) else {}
    value = str(metadata.get("cgs_hash") or "")
    return value if value else _sha256_json(cgs)


def _u32_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        raise ValueError("expected u32 array")
    parsed = sorted({int(item) for item in value})
    if any(item <= 0 for item in parsed):
        raise ValueError("u32 array values must be positive")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
