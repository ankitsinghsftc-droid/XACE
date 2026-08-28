"""Retained X10-031 proof: prompt generated system -> signed runtime replay.

The provider supplies only a closed add_generated_system behavior. Local
trusted code derives the executor and ABI, generates deterministic Rust,
passes cargo and the real SGC safe-compile gate, signs the compile artifact,
re-parses the materialized batch through the trusted typed boundary, and
commits it atomically through GDE. The committed CGS is compiled by the real
SGC and replayed twice by the real runtime from a persisted plan.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_SRC = REPO_ROOT / "packages" / "prompt-intelligence" / "src"
CODEGEN_DIR = PROMPT_SRC / "code_generation"
GDE_PACKAGE = REPO_ROOT / "packages" / "gde"
TOOLS_DIR = REPO_ROOT / "tools"
for location in (
    REPO_ROOT,
    PROMPT_SRC,
    PROMPT_SRC / "output_parser",
    CODEGEN_DIR,
    GDE_PACKAGE,
    TOOLS_DIR,
):
    resolved = str(location)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
for prompt_subdir in ("llm_orchestrator", "context_assembler"):
    resolved = str(PROMPT_SRC / prompt_subdir)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)

from packages.dcl.gameplay_primitives import committed_cgs_hash  # noqa: E402
from code_generation_engine import CodeGenerationEngine  # noqa: E402
from generated_system_materializer import (  # noqa: E402
    GeneratedSystemMaterializationError,
    GeneratedSystemMaterializer,
)
from generated_system_safe_compiler import (  # noqa: E402
    REQUIRED_VALIDATION_STEPS,
    validate_compile_artifact_signature,
)
from structured_output_parser import StructuredOutputParser  # noqa: E402
from typed_operations import (  # noqa: E402
    TypedOperationError,
    normalized_typed_operation_batch,
    parse_typed_operation_batch,
    typed_operation_batch_json_schema,
)
from src.domain_dsl.mutation_metadata.mutation_metadata_model import (  # noqa: E402
    MutationMetadata,
)
from src.gde_orchestrator import GDEOrchestrator  # noqa: E402
from cgs_schema_validate import ValidationResult, validate_cgs  # noqa: E402
from generated_system_safe_compile_smoke import (  # noqa: E402
    VALID_GENERATED_COUNTER_RUST,
)
import sgc_runtime_proof as runtime_proof  # noqa: E402


DEFAULT_RUNTIME_BIN = (
    REPO_ROOT
    / "target-codex-task29-primitives"
    / "debug"
    / "xace_runtime.exe"
)
DEFAULT_SGC_BIN = (
    REPO_ROOT
    / "target-codex-task29-primitives"
    / "debug"
    / "xace-system-graph-compiler.exe"
)
DEFAULT_ROOT = REPO_ROOT / "target-codex-task31-generated-systems"
DEFAULT_ARTIFACT_DIR = DEFAULT_ROOT / "artifacts"
DEFAULT_OUTPUT = DEFAULT_ROOT / "report.json"
SYSTEM_ID = "GeneratedCounterSystem"
COMPONENT_TYPE_ID = 300


@dataclass(frozen=True)
class _StaticInferenceResponse:
    text: str


class _StaticCodeAdapter:
    """Offline deterministic provider used only for generated Rust source."""

    def __init__(self, rust_source: str) -> None:
        self._rust_source = rust_source
        self.calls: list[str] = []

    def call(self, request: Any) -> _StaticInferenceResponse:
        self.calls.append(str(getattr(request, "call_label", "")))
        return _StaticInferenceResponse(text=self._rust_source)


class _CapturingCodeGenerationEngine:
    """Retain real engine results so the proof can assert every compile gate."""

    def __init__(self, engine: CodeGenerationEngine) -> None:
        self._engine = engine
        self.results: list[Any] = []

    def generate_system(self, **kwargs: Any) -> Any:
        result = self._engine.generate_system(**kwargs)
        self.results.append(result)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove prompt-generated systems end to end."
    )
    parser.add_argument("--runtime-bin", default=str(DEFAULT_RUNTIME_BIN))
    parser.add_argument("--sgc-bin", default=str(DEFAULT_SGC_BIN))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ticks", type=int, default=4)
    parser.add_argument("--world-seed", type=int, default=31)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run_check(
            runtime_bin=Path(args.runtime_bin).resolve(),
            sgc_bin=Path(args.sgc_bin).resolve(),
            artifact_dir=Path(args.artifact_dir).resolve(),
            ticks=args.ticks,
            world_seed=args.world_seed,
        )
        runtime_proof.write_json(Path(args.output).resolve(), report)
    except Exception as exc:  # noqa: BLE001 - retained proof emits actionable failure.
        print(f"generated system prompt proof failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(report, sort_keys=True)
        if args.json
        else json.dumps(report, indent=2, sort_keys=True)
    )
    return 0


def run_check(
    *,
    runtime_bin: Path,
    sgc_bin: Path,
    artifact_dir: Path,
    ticks: int,
    world_seed: int,
) -> dict[str, Any]:
    runtime_proof.require(
        runtime_bin.is_file(), f"runtime binary not found: {runtime_bin}"
    )
    runtime_proof.require(sgc_bin.is_file(), f"SGC binary not found: {sgc_bin}")
    runtime_proof.require(ticks > 1, "ticks must be greater than one")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    base_cgs = _base_cgs()
    base_hash = base_cgs["metadata"]["cgs_hash"]
    base_canonical = _canonical(base_cgs)
    provider_batch = _provider_batch()
    provider_schema = typed_operation_batch_json_schema()
    provider_contract = _provider_contract_proof(provider_schema)
    provider_generated_variant_closed = provider_contract[
        "generated_variant_is_closed"
    ]
    runtime_proof.require(
        provider_contract["generated_variant_hides_runtime_executor"],
        "provider schema exposes internal runtime_executor",
    )
    runtime_proof.require(
        provider_generated_variant_closed,
        "provider add_generated_system grammar is not closed",
    )
    runtime_proof.write_json(artifact_dir / "provider_schema.json", provider_schema)
    runtime_proof.write_json(artifact_dir / "base.cgs.json", base_cgs)
    runtime_proof.write_json(
        artifact_dir / "provider_generated_system_batch.json", provider_batch
    )

    provider_parsed = parse_typed_operation_batch(provider_batch)
    provider_normalized = normalized_typed_operation_batch(provider_parsed)
    runtime_proof.require(
        "runtime_executor" not in provider_normalized["operations"][0],
        "provider normalization introduced a runtime executor",
    )
    runtime_proof.write_json(
        artifact_dir / "provider_normalized_batch.json", provider_normalized
    )

    adapter = _StaticCodeAdapter(VALID_GENERATED_COUNTER_RUST)
    real_engine = CodeGenerationEngine(adapter, sgc_bin=sgc_bin)
    capturing_engine = _CapturingCodeGenerationEngine(real_engine)
    materializer = GeneratedSystemMaterializer(
        enabled=True,
        sgc_bin_path=str(sgc_bin),
        code_generation_engine=capturing_engine,
    )
    materialized = materializer.materialize(
        provider_normalized,
        base_cgs,
        session_id="x10-031-proof",
    )
    runtime_proof.require(
        materialized.generated_system_ids == (SYSTEM_ID,),
        "local materializer did not produce the requested generated system",
    )
    runtime_proof.require(
        len(materialized.compile_artifacts) == 1,
        "local materializer did not retain exactly one compile artifact",
    )
    runtime_proof.require(
        len(capturing_engine.results) == 1,
        "local materializer did not invoke the real code-generation engine once",
    )
    materialized_batch = materialized.normalized_batch
    generation = capturing_engine.results[0]
    safe_compile = getattr(generation, "safe_compile_result", None)
    runtime_proof.require(
        bool(getattr(generation, "succeeded", False)),
        f"real code-generation engine failed: {getattr(generation, 'error', '')}",
    )
    runtime_proof.require(
        safe_compile is not None and bool(getattr(safe_compile, "succeeded", False)),
        "real generated-system safe compile did not succeed",
    )
    artifact = copy.deepcopy(
        materialized_batch["operations"][0]["runtime_executor"][
            "compile_artifact"
        ]
    )
    signed_executor = copy.deepcopy(
        materialized_batch["operations"][0]["runtime_executor"]
    )
    unsigned_executor = copy.deepcopy(signed_executor)
    unsigned_executor.pop("compile_artifact", None)
    runtime_proof.require(
        validate_compile_artifact_signature(artifact),
        "local generated-system compile artifact signature is invalid",
    )
    runtime_proof.require(
        artifact.get("validation_steps") == list(REQUIRED_VALIDATION_STEPS),
        "local compile artifact omitted or reordered safe-compile gates",
    )
    runtime_proof.require(
        artifact.get("runtime_executor_hash")
        == runtime_proof.sha256_json(unsigned_executor),
        "compile artifact is not bound to the locally derived runtime executor",
    )
    runtime_proof.require(
        _is_float_free(materialized_batch),
        "materialized typed batch contains a floating-point value",
    )
    runtime_proof.write_json(
        artifact_dir / "materialized_signed_batch.json",
        materialized_batch,
    )
    runtime_proof.write_json(
        artifact_dir / "local_compile_artifact.json", artifact
    )

    trusted_parsed = parse_typed_operation_batch(
        materialized_batch,
        allow_materialized_generated_systems=True,
    )
    trusted_normalized = normalized_typed_operation_batch(trusted_parsed)
    canonical = StructuredOutputParser().parse_typed(
        json.dumps(trusted_normalized, sort_keys=True),
        base_cgs,
        allow_materialized_generated_systems=True,
    )
    runtime_proof.require(
        canonical.is_fully_valid,
        "; ".join(canonical.validation.errors),
    )
    runtime_proof.require(
        canonical.normalized_batch == trusted_normalized,
        "trusted typed parser changed the materialized batch",
    )
    runtime_proof.write_json(
        artifact_dir / "trusted_normalized_batch.json", trusted_normalized
    )
    runtime_proof.write_json(
        artifact_dir / "prompt_proposed.cgs.json", canonical.proposed_cgs
    )

    orchestrator = GDEOrchestrator(session_id="x10-031-proof")
    orchestrator.load_cgs(base_cgs)
    commit = orchestrator.process_typed_operation_batch(
        trusted_normalized,
        _metadata(orchestrator, "x10-031-proof"),
    )
    runtime_proof.require(commit.success, commit.error)
    committed = orchestrator.current_cgs
    committed_hash = orchestrator.current_hash
    generated_system = _find_system(committed, SYSTEM_ID)
    runtime_proof.require(
        generated_system is not None, "GDE commit omitted generated system"
    )
    generated_system_contract_complete = _generated_system_contract_complete(
        generated_system,
        trusted_normalized["operations"][0],
    )
    runtime_proof.require(
        generated_system_contract_complete,
        "committed generated system contract is incomplete or mismatched",
    )
    runtime_proof.require(
        generated_system.get("runtime_executor")
        == trusted_normalized["operations"][0]["runtime_executor"],
        "GDE commit changed the signed runtime executor",
    )
    runtime_proof.require(
        generated_system.get("source") == "generated"
        and generated_system.get("description")
        == trusted_normalized["operations"][0]["explanation"],
        "GDE commit omitted generated source/explanation metadata",
    )
    runtime_proof.require(
        tuple(commit.typed_operation_kinds) == ("add_generated_system",),
        "GDE lost generated typed-operation provenance",
    )
    runtime_proof.write_json(artifact_dir / "committed.cgs.json", committed)

    validation = ValidationResult()
    validate_cgs(
        committed,
        validation,
        allow_legacy_hash=False,
        allow_draft_hash=False,
    )
    runtime_proof.require(validation.ok, "; ".join(validation.errors))

    project_root = artifact_dir / "runtime-project"
    cgs_path = project_root / "game.cgs.json"
    runtime_proof.write_json(cgs_path, committed)
    sgc_input = runtime_proof.sgc_input_from_cgs(committed)
    runtime_proof.write_json(artifact_dir / "sgc_input.json", sgc_input)
    sgc_result = runtime_proof.run_sgc(sgc_bin, sgc_input)
    plan = sgc_result["plan"]
    runtime_proof.validate_sgc_plan(plan, committed_hash, sgc_input)
    persisted_plan, sgc_proof_metadata = runtime_proof.persist_sgc_plan(
        project_root=project_root,
        sgc_input=sgc_input,
        sgc_plan=plan,
    )
    runtime_proof.write_json(artifact_dir / "persisted_plan.json", persisted_plan)
    scheduled = runtime_proof.scheduled_system_ids_from_plan(persisted_plan)
    runtime_proof.require(
        SYSTEM_ID in scheduled, f"{SYSTEM_ID} was not scheduled by real SGC"
    )

    first_run = runtime_proof.run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=artifact_dir / "first.schedule_report.json",
        stdout_path=artifact_dir / "first.runtime.stdout.txt",
        stderr_path=artifact_dir / "first.runtime.stderr.txt",
        ticks=ticks,
        world_seed=world_seed,
    )
    second_run = runtime_proof.run_runtime(
        runtime_bin=runtime_bin,
        cgs_path=cgs_path,
        report_path=artifact_dir / "second.schedule_report.json",
        stdout_path=artifact_dir / "second.runtime.stdout.txt",
        stderr_path=artifact_dir / "second.runtime.stderr.txt",
        ticks=ticks,
        world_seed=world_seed,
    )
    first_report = runtime_proof.read_runtime_report(
        first_run["report_path"], persisted_plan, ticks, world_seed
    )
    second_report = runtime_proof.read_runtime_report(
        second_run["report_path"], persisted_plan, ticks, world_seed
    )
    replay = runtime_proof.compare_replay_reports(first_report, second_report)
    world_hashes = [record["world_hash"] for record in first_report["hash_log"]]
    runtime_proof.require(
        len(set(world_hashes)) == ticks,
        "generated increment system did not change authoritative world state each tick",
    )

    adversarial = _adversarial_rejection_proof(
        base_cgs=base_cgs,
        provider_batch=provider_batch,
        signed_batch=trusted_normalized,
        materializer=materializer,
        code_generation_engine=capturing_engine,
    )

    orchestrator._cgs_manager.rollback_to_hash(base_hash, base_cgs)
    rollback_exact = (
        orchestrator.current_hash == base_hash
        and _canonical(orchestrator.current_cgs) == base_canonical
    )
    runtime_proof.require(
        rollback_exact, "rollback did not restore the exact pre-generation CGS"
    )

    safe_sgc_result = getattr(safe_compile, "sgc_result", None)
    safe_cargo_result = getattr(safe_compile, "compile_result", None)
    checks = {
        "provider_schema_hides_runtime_executor": provider_contract[
            "generated_variant_hides_runtime_executor"
        ],
        "provider_generated_variant_closed": provider_generated_variant_closed,
        "provider_batch_parsed_without_executor": (
            "runtime_executor" not in provider_normalized["operations"][0]
        ),
        "local_materializer_invoked_real_codegen": len(adapter.calls) == 1,
        "generated_rust_contract_and_cargo_passed": bool(
            getattr(safe_cargo_result, "passed", False)
        ),
        "safe_compile_invoked_real_sgc": bool(
            safe_sgc_result is not None
            and getattr(safe_sgc_result, "passed", False)
            and getattr(safe_sgc_result, "returncode", -1) == 0
        ),
        "compile_artifact_signed_and_complete": (
            validate_compile_artifact_signature(artifact)
            and artifact.get("validation_steps") == list(REQUIRED_VALIDATION_STEPS)
        ),
        "compile_artifact_bound_to_derived_executor": (
            artifact.get("runtime_executor_hash")
            == runtime_proof.sha256_json(unsigned_executor)
        ),
        "materialized_batch_is_float_free": _is_float_free(
            materialized_batch
        ),
        "compile_artifact_duration_is_deterministic": (
            artifact.get("cargo", {}).get("duration_ms") == 0
        ),
        "trusted_typed_parse_valid": canonical.is_fully_valid,
        "gde_atomic_commit": commit.success,
        "generated_system_contract_complete": (
            generated_system_contract_complete
        ),
        "standalone_cgs_validation": validation.ok,
        "real_sgc_binary_invoked_after_commit": sgc_result["returncode"] == 0,
        "generated_system_scheduled": SYSTEM_ID in scheduled,
        "persisted_sgc_plan_loaded": first_report["plan_source"] == "persisted_sgc",
        "real_runtime_binary_invoked_twice": (
            first_run["returncode"] == 0 and second_run["returncode"] == 0
        ),
        "generated_system_changed_world_each_tick": len(set(world_hashes)) == ticks,
        "tick_hash_replay_match": replay["tick_hash_replay_match"],
        "schedule_replay_match": replay["schedule_replay_match"],
        "unsigned_batch_rejected_atomically": adversarial["unsigned"]["passed"],
        "tampered_artifact_rejected_atomically": adversarial["tampered"]["passed"],
        "provider_executor_rejected_atomically": adversarial[
            "provider_runtime_executor"
        ]["passed"],
        "rollback_exact": rollback_exact,
    }
    complete = all(checks.values())
    runtime_proof.require(complete, "one or more X10-031 proof checks failed")

    return {
        "schema": "xace.generated_system_prompt_e2e_report.v1",
        "ok": complete,
        "x10_031_complete": complete,
        "completion_condition": "all checks must be true",
        "system_id": SYSTEM_ID,
        "operation_schema": trusted_normalized["schema"],
        "operation_kinds": ["add_generated_system"],
        "base_cgs_hash": base_hash,
        "committed_cgs_hash": committed_hash,
        "rolled_back_cgs_hash": orchestrator.current_hash,
        "typed_operation_batch_hash": commit.typed_operation_batch_hash,
        "local_compile_artifact": {
            "schema": artifact["schema"],
            "source_hash": artifact["source_hash"],
            "runtime_executor_hash": artifact["runtime_executor_hash"],
            "abi_hash": artifact["abi_hash"],
            "sgc_plan_hash": artifact["sgc_plan_hash"],
            "signature": artifact["signature"],
            "validation_steps": artifact["validation_steps"],
        },
        "code_generation": {
            "provider_calls": list(adapter.calls),
            "attempts_used": getattr(generation, "attempts_used", 0),
            "safe_compile_stage": getattr(safe_compile, "stage", ""),
            "safe_compile_sgc_returncode": getattr(
                safe_sgc_result, "returncode", -1
            ),
        },
        "post_commit_plan_hash": persisted_plan["plan_hash"],
        "scheduled_system_ids": scheduled,
        "latest_world_hash": first_report["latest_world_hash"],
        "checks": checks,
        "provider_contract": provider_contract,
        "adversarial_rejections": adversarial,
        "sgc_proof_metadata": sgc_proof_metadata,
        "artifacts": {
            "directory": str(artifact_dir),
            "provider_batch": str(
                artifact_dir / "provider_generated_system_batch.json"
            ),
            "materialized_batch": str(
                artifact_dir / "materialized_signed_batch.json"
            ),
            "committed_cgs": str(artifact_dir / "committed.cgs.json"),
            "compile_artifact": str(
                artifact_dir / "local_compile_artifact.json"
            ),
            "persisted_plan": str(artifact_dir / "persisted_plan.json"),
            "first_runtime_report": first_run["report_path"],
            "second_runtime_report": second_run["report_path"],
        },
    }


def _base_cgs() -> dict[str, Any]:
    cgs = {
        "format": "xace.cgs.export",
        "format_version": "1.0.0",
        "metadata": {
            "name": "Prompt generated system proof",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "execution_plan_version": 1,
        },
        "component_schemas": [
            {
                "type_id": COMPONENT_TYPE_ID,
                "name": "COMP_COUNTER_V1",
                "version": "1.0.0",
                "fields": [
                    {
                        "name": "count",
                        "field_type": "fixed",
                        "default": 0,
                        "description": "Authoritative fixed-point counter.",
                    }
                ],
                "defaults": {"count": 0},
                "source": "generated",
            }
        ],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    {
                        "id": "counter",
                        "spawn_count": 1,
                        "components": [
                            {
                                "type_id": COMPONENT_TYPE_ID,
                                "name": "COMP_COUNTER_V1",
                                "defaults": {"count": 0},
                            }
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }
    cgs["metadata"]["cgs_hash"] = committed_cgs_hash(cgs)
    return cgs


def _provider_batch() -> dict[str, Any]:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.x10-031-proof",
        "prompt_id": "prompt.x10-031-proof",
        "summary": "Generate a deterministic counter system.",
        "operations": [
            {
                "operation_id": "op.generated.counter",
                "kind": "add_generated_system",
                "explanation": (
                    "Increment the authoritative fixed-point counter every "
                    "simulation tick."
                ),
                "system_id": SYSTEM_ID,
                "phase": "Simulation",
                "reads": [COMPONENT_TYPE_ID],
                "writes": [COMPONENT_TYPE_ID],
                "depends_on": [],
                "behavior": {
                    "kind": "increment_numeric_field",
                    "component_type_id": COMPONENT_TYPE_ID,
                    "field": "count",
                    "amount": 1,
                },
                "scope": "global",
                "mode_id": "",
                "version": "1.0.0",
                "deterministic": True,
                "parallel": False,
            }
        ],
    }


def _metadata(
    orchestrator: GDEOrchestrator,
    session_id: str,
) -> MutationMetadata:
    return MutationMetadata.create(
        source="prompt",
        parent_cgs_hash=orchestrator.current_hash,
        schema_version_target="0.1.0",
        prompt_text="generate a counter system",
        confidence=0.99,
        description="Generate a deterministic fixed-point counter system.",
        risk_level="medium",
        session_id=session_id,
    )


def _provider_contract_proof(schema: dict[str, Any]) -> dict[str, Any]:
    operations = schema["properties"]["operations"]
    variants = operations["items"]["anyOf"]
    generated = next(
        (
            variant
            for variant in variants
            if variant.get("properties", {})
            .get("kind", {})
            .get("const")
            == "add_generated_system"
        ),
        None,
    )
    runtime_proof.require(
        isinstance(generated, dict),
        "provider schema has no add_generated_system variant",
    )
    properties = generated["properties"]
    return {
        "schema_hash": runtime_proof.sha256_json(schema),
        "generated_variant_hides_runtime_executor": (
            "runtime_executor" not in properties
        ),
        "generated_variant_is_closed": (
            generated.get("additionalProperties") is False
            and set(generated.get("required", [])) == set(properties)
        ),
        "generated_variant_fields": sorted(properties),
    }


def _adversarial_rejection_proof(
    *,
    base_cgs: dict[str, Any],
    provider_batch: dict[str, Any],
    signed_batch: dict[str, Any],
    materializer: GeneratedSystemMaterializer,
    code_generation_engine: _CapturingCodeGenerationEngine,
) -> dict[str, dict[str, Any]]:
    unsigned = copy.deepcopy(signed_batch)
    del unsigned["operations"][0]["runtime_executor"]["compile_artifact"]
    unsigned_proof = _gde_rejection(
        base_cgs,
        unsigned,
        "x10-031-unsigned",
        expected_code="GDE_TYPED_OPERATION_INVALID",
    )

    tampered = copy.deepcopy(signed_batch)
    artifact = tampered["operations"][0]["runtime_executor"]["compile_artifact"]
    signature = str(artifact["signature"])
    artifact["signature"] = (
        ("0" if signature[0] != "0" else "1") + signature[1:]
    )
    tampered_proof = _gde_rejection(
        base_cgs,
        tampered,
        "x10-031-tampered",
        expected_code="GDE_TYPED_CGS_INCONSISTENT",
    )

    provider_executor = copy.deepcopy(provider_batch)
    provider_executor["operations"][0]["runtime_executor"] = copy.deepcopy(
        signed_batch["operations"][0]["runtime_executor"]
    )
    provider_orchestrator = GDEOrchestrator(
        session_id="x10-031-provider-executor"
    )
    provider_orchestrator.load_cgs(base_cgs)
    before_hash = provider_orchestrator.current_hash
    before_canonical = _canonical(provider_orchestrator.current_cgs)
    parser_error = ""
    materializer_error = ""
    materializer_error_code = ""
    try:
        parse_typed_operation_batch(provider_executor)
    except TypedOperationError as exc:
        parser_error = str(exc)
    try:
        materializer.materialize(
            provider_executor,
            base_cgs,
            session_id="x10-031-provider-executor",
        )
    except GeneratedSystemMaterializationError as exc:
        materializer_error = str(exc)
        materializer_error_code = exc.code
    code_generation_calls = len(code_generation_engine.results)
    exact_unchanged = (
        provider_orchestrator.current_hash == before_hash
        and _canonical(provider_orchestrator.current_cgs) == before_canonical
    )
    provider_proof = {
        "passed": (
            "internal-only" in parser_error
            and materializer_error_code == "provider_supplied_runtime_executor"
            and len(code_generation_engine.results) == code_generation_calls
            and exact_unchanged
        ),
        "provider_parser_rejected": "internal-only" in parser_error,
        "materializer_rejected": (
            materializer_error_code == "provider_supplied_runtime_executor"
        ),
        "no_additional_codegen_invocation": (
            len(code_generation_engine.results) == code_generation_calls
        ),
        "exact_base_cgs_unchanged": exact_unchanged,
        "parser_error": parser_error,
        "materializer_error": materializer_error,
        "materializer_error_code": materializer_error_code,
    }
    return {
        "unsigned": unsigned_proof,
        "tampered": tampered_proof,
        "provider_runtime_executor": provider_proof,
    }


def _gde_rejection(
    base_cgs: dict[str, Any],
    batch: dict[str, Any],
    session_id: str,
    *,
    expected_code: str,
) -> dict[str, Any]:
    orchestrator = GDEOrchestrator(session_id=session_id)
    orchestrator.load_cgs(base_cgs)
    before_hash = orchestrator.current_hash
    before_canonical = _canonical(orchestrator.current_cgs)
    result = orchestrator.process_typed_operation_batch(
        batch,
        _metadata(orchestrator, session_id),
    )
    exact_unchanged = (
        orchestrator.current_hash == before_hash
        and _canonical(orchestrator.current_cgs) == before_canonical
    )
    return {
        "passed": (
            not result.success
            and result.code == expected_code
            and exact_unchanged
        ),
        "rejected": not result.success,
        "code": result.code,
        "expected_code": expected_code,
        "exact_base_cgs_unchanged": exact_unchanged,
        "error": result.error,
    }


def _find_system(cgs: dict[str, Any], system_id: str) -> dict[str, Any] | None:
    for system in cgs.get("global_systems", []):
        if isinstance(system, dict) and system.get("id") == system_id:
            return system
    for mode in cgs.get("modes", []):
        if not isinstance(mode, dict):
            continue
        for system in mode.get("systems", []):
            if isinstance(system, dict) and system.get("id") == system_id:
                return system
    return None


def _generated_system_contract_complete(
    system: dict[str, Any],
    operation: dict[str, Any],
) -> bool:
    component_type_id = operation["behavior"]["component_type_id"]
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
    executor = system.get("runtime_executor")
    if not isinstance(executor, dict):
        return False
    behavior = operation["behavior"]
    return (
        system.get("id") == operation["system_id"]
        and system.get("phase") == operation["phase"]
        and system.get("reads") == operation["reads"]
        and system.get("writes") == operation["writes"]
        and system.get("depends_on") == operation["depends_on"]
        and system.get("version") == operation["version"]
        and system.get("deterministic") is True
        and system.get("parallel") is operation["parallel"]
        and system.get("source") == "generated"
        and system.get("description") == operation["explanation"]
        and executor.get("kind") == "generated.increment_numeric_field"
        and executor.get("component_type_id") == behavior["component_type_id"]
        and executor.get("field") == behavior["field"]
        and executor.get("amount") == behavior["amount"]
        and executor.get("abi") == expected_abi
        and isinstance(executor.get("compile_artifact"), dict)
    )


def _is_float_free(value: Any) -> bool:
    if isinstance(value, float):
        return False
    if isinstance(value, list):
        return all(_is_float_free(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_float_free(item)
            for key, item in value.items()
        )
    return True


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
