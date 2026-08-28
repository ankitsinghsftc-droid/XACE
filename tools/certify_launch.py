"""
certify_launch.py - editor-free XACE launch readiness certification.

This command runs the strongest local checks that do not require opening
Godot, Unity, or Unreal editors. Engine-editor validation remains explicit
per-engine work; this command proves the shared XACE product paths.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_DIR = REPO_ROOT / "target-codex-certify"
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server"
PROJECT_SYSTEM = REPO_ROOT / "packages" / "project-system"
CERTIFICATION_REPORT_SCHEMA = "xace.launch_certification.v1"
INSTALLED_ENGINE_SUMMARY_SCHEMA = "xace.installed_engine_summary.v1"
CERTIFIED_ENGINES = ("godot", "unity", "unreal")


@dataclass(frozen=True)
class Check:
    label: str
    command: list[str]
    cwd: Path = REPO_ROOT


@dataclass(frozen=True)
class Result:
    check: Check
    returncode: int
    elapsed_seconds: float
    stdout_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class InstalledEngineResult:
    engine: str
    label: str
    ok: bool
    skipped: bool
    detail: str
    elapsed_seconds: float
    report_path: Path | None = None
    report: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


def build_checks(target_dir: Path, *, quick: bool = False) -> list[Check]:
    runtime_bin = target_dir / "debug" / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
    sgc_bin = target_dir / "debug" / ("xace-system-graph-compiler.exe" if os.name == "nt" else "xace-system-graph-compiler")
    npm = "npm.cmd" if os.name == "nt" else "npm"

    checks = [
        Check(
            "runtime binary",
            ["cargo", "build", "-p", "xace-runtime-core", "--bin", "xace_runtime", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime engine protocol tests",
            ["cargo", "test", "-p", "xace-runtime-core", "engine_protocol", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime control protocol tests",
            ["cargo", "test", "-p", "xace-runtime-core", "control_protocol", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime side-channel hash policy",
            ["cargo", "test", "-p", "xace-runtime-core", "side_channel_hash_policy", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime snapshot completeness",
            ["cargo", "test", "-p", "xace-runtime-core", "x10_012", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime snapshot serialization",
            ["cargo", "test", "-p", "xace-runtime-core", "snapshot_serializer", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime replay divergence diagnosis",
            ["cargo", "test", "-p", "xace-runtime-core", "x10_015", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "mutation gate apply path",
            [sys.executable, "tools/mutation_gate_apply_path_check.py"],
        ),
        Check(
            "static mutation conflict analysis",
            [sys.executable, "tools/mutation_conflict_analysis_check.py"],
        ),
        Check(
            "mutation gate atomic wrapper",
            ["cargo", "test", "-p", "xace-runtime-core", "x10_017", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime schema hot-swap",
            ["cargo", "test", "-p", "xace-runtime-core", "x10_020", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime hot-swap compatibility classes",
            ["cargo", "test", "-p", "xace-runtime-core", "x10_021", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "runtime state migration hooks",
            ["cargo", "test", "-p", "xace-runtime-core", "x10_022", "--lib", "--target-dir", str(target_dir)],
        ),
        Check(
            "engine side-effect rollback",
            [sys.executable, "tools/engine_side_effect_rollback_check.py", "--output", str(target_dir / "engine-side-effect-rollback" / "report.json")],
        ),
        Check(
            "SGC binary",
            ["cargo", "build", "-p", "xace-system-graph-compiler", "--target-dir", str(target_dir)],
        ),
        Check(
            "SGC CLI smoke",
            [sys.executable, "tools/sgc_cli_smoke.py", "--sgc-bin", str(sgc_bin)],
        ),
        Check(
            "project creation templates",
            [sys.executable, "-m", "unittest", "discover", "packages/project-system/tests"],
        ),
        Check(
            "project crash recovery",
            [
                sys.executable,
                "-m",
                "unittest",
                "packages/project-system/tests/test_project_system.py",
                "packages/builder-workspace/server/tests/test_cgs_persistence_authority.py",
            ],
        ),
        Check(
            "asset import/link workflow",
            [sys.executable, "-m", "unittest", "discover", "packages/asset-registry/tests"],
        ),
        Check(
            "asset reference validation gate",
            [
                sys.executable,
                "tools/asset_reference_validation_check.py",
                "--output",
                str(target_dir / "asset-reference-validation" / "report.json"),
                "--artifact-dir",
                str(target_dir / "asset-reference-validation" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "semantic binding UI gate",
            [
                sys.executable,
                "tools/semantic_binding_ui_check.py",
                "--output",
                str(target_dir / "semantic-binding-ui" / "report.json"),
                "--artifact-dir",
                str(target_dir / "semantic-binding-ui" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "semantic binding status gate",
            [
                sys.executable,
                "tools/semantic_binding_status_check.py",
                "--output",
                str(target_dir / "semantic-binding-status" / "report.json"),
                "--artifact-dir",
                str(target_dir / "semantic-binding-status" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "runtime fallback binding gate",
            [
                sys.executable,
                "tools/runtime_fallback_binding_check.py",
                "--output",
                str(target_dir / "runtime-fallback-binding" / "report.json"),
                "--artifact-dir",
                str(target_dir / "runtime-fallback-binding" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "import marker inventory gate",
            [
                sys.executable,
                "tools/import_marker_inventory_check.py",
                "--output",
                str(target_dir / "import-marker-inventory" / "report.json"),
                "--artifact-dir",
                str(target_dir / "import-marker-inventory" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "manual migration wizard gate",
            [
                sys.executable,
                "tools/manual_migration_wizard_check.py",
                "--output",
                str(target_dir / "manual-migration-wizard" / "report.json"),
                "--artifact-dir",
                str(target_dir / "manual-migration-wizard" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "adapter reversibility gate",
            [
                sys.executable,
                "tools/adapter_reversibility_check.py",
                "--output",
                str(target_dir / "adapter-reversibility" / "report.json"),
                "--artifact-dir",
                str(target_dir / "adapter-reversibility" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "adapter package handoff wording gate",
            [
                sys.executable,
                "tools/adapter_package_handoff_wording_check.py",
                "--output",
                str(target_dir / "adapter-package-handoff-wording" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "adapter package handoff preflight gate",
            [
                sys.executable,
                "tools/adapter_package_handoff_preflight_check.py",
                "--output",
                str(target_dir / "adapter-package-handoff-preflight" / "report.json"),
                "--artifact-dir",
                str(target_dir / "adapter-package-handoff-preflight" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "adapter package version gate",
            [
                sys.executable,
                "tools/adapter_package_version_check.py",
                "--output",
                str(target_dir / "adapter-package-version" / "report.json"),
                "--artifact-dir",
                str(target_dir / "adapter-package-version" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "canonical vertical slice fixture gate",
            [
                sys.executable,
                "tools/canonical_vertical_slice_check.py",
                "--output",
                str(target_dir / "canonical-vertical-slice" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "builder backend edit loop",
            [sys.executable, "-m", "unittest", "discover", "packages/builder-workspace/server/tests"],
        ),
        Check(
            "engine edit boundary",
            [sys.executable, "-m", "unittest", "packages/builder-workspace/server/tests/test_engine_edit_router.py"],
        ),
        Check(
            "builder python modules",
            [
                sys.executable,
                "-m",
                "py_compile",
                "tools/runtime_bridge_smoke.py",
                "tools/runtime_sgc_plan_loader_smoke.py",
                "tools/runtime_sgc_schedule_snapshot_smoke.py",
                "tools/sgc_runtime_proof.py",
                "tools/gameplay_primitive_library_check.py",
                "tools/typed_cgs_operation_e2e_check.py",
                "tools/generated_system_prompt_e2e_check.py",
                "tools/composite_prompt_planning_e2e_check.py",
                "tools/prompt_undo_redo_e2e_check.py",
                "tools/prompt_long_session_degradation_check.py",
                "tools/multiplayer_topology_check.py",
                "tools/runtime_input_sync_check.py",
                "tools/runtime_rollback_resimulation_check.py",
                "tools/runtime_prediction_reconciliation_check.py",
                "tools/session_lifecycle_check.py",
                "tools/session_compatibility_check.py",
                "tools/malicious_input_limits_check.py",
                "tools/multiplayer_diagnostics_check.py",
                "tools/network_chaos_proof.py",
                "tools/multi_user_soak_check.py",
                "tools/tick_debugger_minimum_check.py",
                "tools/tick_debugger_time_travel_check.py",
                "tools/tick_debugger_delta_retention_check.py",
                "tools/tick_debugger_breakpoint_check.py",
                "tools/tick_debugger_causality_graph_check.py",
                "tools/tick_debugger_rng_seed_trace_check.py",
                "tools/support_diagnostics_bundle.py",
                "tools/support_diagnostics_bundle_check.py",
                "tools/export_debug_report.py",
                "tools/export_debug_report_check.py",
                "tools/asset_reference_validation_check.py",
                "tools/semantic_binding_ui_check.py",
                "tools/semantic_binding_status_check.py",
                "tools/runtime_fallback_binding_check.py",
                "tools/import_marker_inventory_check.py",
                "tools/manual_migration_wizard_check.py",
                "tools/adapter_reversibility_check.py",
                "tools/adapter_package_handoff_wording_check.py",
                "tools/adapter_package_handoff_preflight_check.py",
                "tools/adapter_package_version_check.py",
                "tools/canonical_vertical_slice_check.py",
                "tools/godot_vertical_slice_certification.py",
                "tools/unity_vertical_slice_certification.py",
                "tools/replay_cross_platform_proof.py",
                "tools/cgs_end_to_end_proof.py",
                "tools/phase1_readiness_score.py",
                "tools/fixed_point_authority_check.py",
                "tools/mutation_gate_apply_path_check.py",
                "tools/mutation_conflict_analysis_check.py",
                "tools/engine_side_effect_rollback_check.py",
                "tools/three_engine_runtime_smoke.py",
                "tools/prompt_pipeline_smoke.py",
                "tools/generated_system_safe_compile_smoke.py",
                "tools/provider_readiness_smoke.py",
                "tools/hosted_provider_proof_gate.py",
                "tools/provider_timeout_retry_check.py",
                "tools/provider_token_cost_accounting_check.py",
                "tools/forbidden_claims_check.py",
                "tools/commercial_scope_check.py",
                "tools/source_inventory_check.py",
                "tools/fake_skip_register_check.py",
                "tools/production_path_check.py",
                "tools/inference_adapter_boundary_check.py",
                "tools/prompt_capability_matrix_check.py",
                "tools/prompt_classifier_gate_check.py",
                "tools/prompt_clarification_loop_check.py",
                "tools/prompt_diff_approval_check.py",
                "tools/prompt_apply_recovery_check.py",
                "tools/prompt_apply_validation_feedback_check.py",
                "tools/prompt_corpus_check.py",
                "tools/prompt_unknown_cgs_path_check.py",
                "tools/python_test_gate.py",
                "tools/prompt_corpus_benchmark.py",
                "tools/launch_provider_runtime_benchmark.py",
                "tools/deterministic_simple_edit_benchmark.py",
                "tools/prompt_launch_threshold_check.py",
                "tools/prompt_security_check.py",
                "tools/silent_success_check.py",
                "tools/sgc_cli_smoke.py",
                "tools/builder_onboarding_smoke.py",
                "tools/asset_playback_smoke.py",
                "packages/builder-workspace/ollama_adapter.py",
                "packages/builder-workspace/server/prompt_capability_matrix.py",
                "packages/builder-workspace/server/prompt_classifier_gate.py",
                "packages/prompt-intelligence/src/code_generation/code_generation_engine.py",
                "packages/prompt-intelligence/src/code_generation/generated_system_safe_compiler.py",
                "packages/prompt-intelligence/src/code_generation/unsupported_generated_system_guard.py",
                "packages/prompt-intelligence/src/llm_orchestrator/pil_retry_policy.py",
                "packages/builder-workspace/server/runtime_control_client.py",
                "packages/builder-workspace/server/cgs_persistence.py",
                "packages/builder-workspace/server/ws_message_router.py",
                "packages/builder-workspace/server/builder_server.py",
                "packages/builder-workspace/server/session_manager.py",
                "packages/builder-workspace/server/tests/fixtures/prompt_pipeline_contract.py",
                "packages/builder-workspace/server/provider_settings.py",
                "packages/builder-workspace/server/ollama_adapter.py",
                "packages/inference/src/provider_model_discovery.py",
                "packages/inference/src/model_router.py",
                "packages/inference/src/route_evidence.py",
                "packages/inference/src/inference_retry_policy.py",
                "packages/inference/src/inference_adapter.py",
                "packages/inference/src/telemetry_pipeline.py",
                "packages/inference/src/provider_accounting.py",
                "packages/project-system/project_manifest.py",
                "packages/project-system/project_creator.py",
                "packages/project-system/adapter_installation.py",
                "packages/project-system/adapter_package_handoff_preflight.py",
                "packages/project-system/adapter_package_versioning.py",
                "packages/project-system/engine_project_inventory.py",
                "packages/project-system/engine_migration_wizard.py",
                "packages/asset-registry/asset_reference_preflight.py",
                "packages/asset-registry/semantic_binding_status.py",
                "tools/provider_route_evidence_check.py",
            ],
        ),
        Check(
            "builder TypeScript production build",
            [npm, "run", "build"],
            REPO_ROOT / "packages" / "builder-workspace",
        ),
        Check(
            "builder UI contract",
            [npm, "run", "test:ui"],
            REPO_ROOT / "packages" / "builder-workspace",
        ),
        Check(
            "tick debugger minimum gate",
            [
                sys.executable,
                "tools/tick_debugger_minimum_check.py",
                "--output",
                str(target_dir / "tick-debugger" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "tick debugger time-travel gate",
            [
                sys.executable,
                "tools/tick_debugger_time_travel_check.py",
                "--output",
                str(target_dir / "tick-debugger-time-travel" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "tick debugger delta-retention gate",
            [
                sys.executable,
                "tools/tick_debugger_delta_retention_check.py",
                "--output",
                str(target_dir / "tick-debugger-delta-retention" / "report.json"),
                "--target-dir",
                str(target_dir / "tick-debugger-delta-retention"),
                "--json",
            ],
        ),
        Check(
            "tick debugger breakpoint gate",
            [
                sys.executable,
                "tools/tick_debugger_breakpoint_check.py",
                "--output",
                str(target_dir / "tick-debugger-breakpoints" / "report.json"),
                "--artifact-dir",
                str(target_dir / "tick-debugger-breakpoints" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "tick debugger causality graph gate",
            [
                sys.executable,
                "tools/tick_debugger_causality_graph_check.py",
                "--output",
                str(target_dir / "tick-debugger-causality" / "report.json"),
                "--artifact-dir",
                str(target_dir / "tick-debugger-causality" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "tick debugger RNG seed trace gate",
            [
                sys.executable,
                "tools/tick_debugger_rng_seed_trace_check.py",
                "--output",
                str(target_dir / "tick-debugger-rng-seed-trace" / "report.json"),
                "--artifact-dir",
                str(target_dir / "tick-debugger-rng-seed-trace" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "support diagnostics bundle gate",
            [
                sys.executable,
                "tools/support_diagnostics_bundle_check.py",
                "--output",
                str(target_dir / "support-diagnostics-bundle" / "report.json"),
                "--bundle-root",
                str(target_dir / "support-diagnostics-bundle" / "bundle"),
                "--json",
            ],
        ),
        Check(
            "exportable debug report gate",
            [
                sys.executable,
                "tools/export_debug_report_check.py",
                "--output",
                str(target_dir / "exportable-debug-report" / "report.json"),
                "--artifact-dir",
                str(target_dir / "exportable-debug-report" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "forbidden public claims",
            [sys.executable, "tools/forbidden_claims_check.py"],
        ),
        Check(
            "commercial scope record",
            [sys.executable, "tools/commercial_scope_check.py"],
        ),
        Check(
            "source inventory",
            [sys.executable, "tools/source_inventory_check.py"],
        ),
        Check(
            "fake and skip register",
            [sys.executable, "tools/fake_skip_register_check.py"],
        ),
        Check(
            "production path rules",
            [sys.executable, "tools/production_path_check.py"],
        ),
        Check(
            "fixed-point authority",
            [
                sys.executable,
                "tools/fixed_point_authority_check.py",
                "--output",
                str(target_dir / "fixed-point-authority" / "fixed_point_authority_report.json"),
            ],
        ),
        Check(
            "inference adapter boundary",
            [
                sys.executable,
                "tools/inference_adapter_boundary_check.py",
                "--output",
                str(target_dir / "inference-adapter-boundary" / "inference_adapter_boundary_report.json"),
            ],
        ),
        Check(
            "prompt capability matrix",
            [sys.executable, "tools/prompt_capability_matrix_check.py"],
        ),
        Check(
            "prompt classifier gate",
            [sys.executable, "tools/prompt_classifier_gate_check.py"],
        ),
        Check(
            "prompt clarification loop",
            [sys.executable, "tools/prompt_clarification_loop_check.py"],
        ),
        Check(
            "prompt diff approval gate",
            [sys.executable, "tools/prompt_diff_approval_check.py"],
        ),
        Check(
            "prompt apply atomic recovery gate",
            [sys.executable, "tools/prompt_apply_recovery_check.py"],
        ),
        Check(
            "prompt apply validation feedback gate",
            [sys.executable, "tools/prompt_apply_validation_feedback_check.py"],
        ),
        Check(
            "prompt corpus gate",
            [sys.executable, "tools/prompt_corpus_check.py"],
        ),
        Check(
            "prompt unknown CGS path gate",
            [
                sys.executable,
                "tools/prompt_unknown_cgs_path_check.py",
                "--output",
                str(target_dir / "prompt-unknown-cgs-path" / "prompt_unknown_cgs_path_report.json"),
            ],
        ),
        Check(
            "prompt intelligence Python suite",
            [
                sys.executable,
                "tools/python_test_gate.py",
                "--suite",
                "prompt-intelligence",
                "--output",
                str(target_dir / "prompt-intelligence-python" / "python_gate_report.json"),
            ],
        ),
        Check(
            "prompt corpus benchmark",
            [
                sys.executable,
                "tools/prompt_corpus_benchmark.py",
                "--output",
                str(target_dir / "prompt-corpus-benchmark"),
            ],
        ),
        Check(
            "launch provider/runtime prompt benchmark",
            [
                sys.executable,
                "tools/launch_provider_runtime_benchmark.py",
                "--output",
                str(target_dir / "launch-provider-runtime-prompt-benchmark"),
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
            ],
        ),
        Check(
            "deterministic simple edit benchmark",
            [
                sys.executable,
                "tools/deterministic_simple_edit_benchmark.py",
                "--output",
                str(target_dir / "deterministic-simple-edit-benchmark"),
            ],
        ),
        Check(
            "prompt launch thresholds",
            [
                sys.executable,
                "tools/prompt_launch_threshold_check.py",
                "--target-dir",
                str(target_dir / "prompt-launch-thresholds"),
            ],
        ),
        Check(
            "prompt security gate",
            [
                sys.executable,
                "tools/prompt_security_check.py",
                "--artifact-dir",
                str(target_dir / "prompt-security"),
            ],
        ),
        Check(
            "silent success response guard",
            [
                sys.executable,
                "tools/silent_success_check.py",
                "--output",
                str(target_dir / "silent-success" / "silent_success_report.json"),
            ],
        ),
        Check(
            "prompt pipeline contract/scenario smoke",
            [
                sys.executable,
                "tools/prompt_pipeline_smoke.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
            ],
        ),
        Check(
            "provider readiness stale policy",
            [
                sys.executable,
                "tools/provider_readiness_smoke.py",
                "--settings-path",
                str(target_dir / "provider-health-stale-policy" / "provider_settings.json"),
                "--output",
                str(target_dir / "provider-health-stale-policy" / "provider_health_stale_policy_report.json"),
                "--json",
            ],
        ),
        Check(
            "hosted provider proof gate",
            [
                sys.executable,
                "tools/hosted_provider_proof_gate.py",
                "--output",
                str(target_dir / "hosted-provider-proof" / "hosted_provider_proof_report.json"),
                "--json",
            ],
        ),
        Check(
            "provider route evidence gate",
            [
                sys.executable,
                "tools/provider_route_evidence_check.py",
                "--output",
                str(target_dir / "provider-route-evidence" / "provider_route_evidence_report.json"),
                "--json",
            ],
        ),
        Check(
            "provider timeout retry policy",
            [
                sys.executable,
                "tools/provider_timeout_retry_check.py",
                "--output",
                str(target_dir / "provider-timeout-retry" / "provider_timeout_retry_report.json"),
            ],
        ),
        Check(
            "provider token cost accounting",
            [
                sys.executable,
                "tools/provider_token_cost_accounting_check.py",
                "--output",
                str(target_dir / "provider-token-cost-accounting" / "provider_token_cost_accounting_report.json"),
            ],
        ),
        Check(
            "provider structured output constraints",
            [
                sys.executable,
                "tools/provider_structured_output_check.py",
                str(target_dir / "provider-structured-output" / "provider_structured_output_report.json"),
            ],
        ),
        Check(
            "builder onboarding smoke",
            [sys.executable, "tools/builder_onboarding_smoke.py", "--target-dir", str(target_dir / "builder-onboarding")],
        ),
        Check(
            "asset playback smoke",
            [sys.executable, "tools/asset_playback_smoke.py", "--runtime-bin", str(runtime_bin)],
        ),
        Check(
            "runtime bridge smoke",
            [sys.executable, "tools/runtime_bridge_smoke.py", "--runtime-bin", str(runtime_bin)],
        ),
        Check(
            "runtime SGC plan loader smoke",
            [sys.executable, "tools/runtime_sgc_plan_loader_smoke.py", "--runtime-bin", str(runtime_bin)],
        ),
        Check(
            "runtime SGC schedule snapshot smoke",
            [sys.executable, "tools/runtime_sgc_schedule_snapshot_smoke.py", "--runtime-bin", str(runtime_bin)],
        ),
        Check(
            "SGC runtime proof command",
            [
                sys.executable,
                "tools/sgc_runtime_proof.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--proof-root",
                str(target_dir / "sgc-runtime-proof"),
            ],
        ),
        Check(
            "cross-platform replay proof local leg",
            [
                sys.executable,
                "tools/replay_cross_platform_proof.py",
                "record",
                "--target-dir",
                str(target_dir),
                "--proof-root",
                str(target_dir / "replay-cross-platform-proof"),
                "--ticks",
                "3",
                "--world-seed",
                "424242",
                "--json",
            ],
        ),
        Check(
            "end-to-end CGS proof",
            [
                sys.executable,
                "tools/cgs_end_to_end_proof.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--proof-root",
                str(target_dir / "cgs-e2e-proof"),
                "--target-dir",
                str(target_dir),
            ],
        ),
        Check(
            "phase 1 readiness scorecard",
            [
                sys.executable,
                "tools/phase1_readiness_score.py",
                "--sgc-runtime-root",
                str(target_dir / "sgc-runtime-proof"),
                "--cgs-e2e-root",
                str(target_dir / "cgs-e2e-proof"),
                "--output",
                str(target_dir / "phase1-readiness" / "phase1_readiness_scorecard.json"),
                "--json",
            ],
        ),
        Check(
            "generated system safe compile smoke",
            [
                sys.executable,
                "tools/generated_system_safe_compile_smoke.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
            ],
        ),
        Check(
            "gameplay primitive library",
            [
                sys.executable,
                "tools/gameplay_primitive_library_check.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--output",
                str(target_dir / "gameplay-primitives" / "report.json"),
                "--artifact-dir",
                str(target_dir / "gameplay-primitives" / "artifacts"),
                "--require-full-catalog",
                "--json",
            ],
        ),
        Check(
            "typed CGS operations",
            [
                sys.executable,
                "tools/typed_cgs_operation_e2e_check.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--output",
                str(target_dir / "typed-cgs-operations" / "report.json"),
                "--artifact-dir",
                str(target_dir / "typed-cgs-operations" / "artifacts"),
                "--json",
            ],
        ),
        Check(
            "generated system prompt E2E",
            [
                sys.executable,
                "tools/generated_system_prompt_e2e_check.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--artifact-dir",
                str(target_dir / "generated-system-prompt" / "artifacts"),
                "--output",
                str(target_dir / "generated-system-prompt" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "composite prompt planning E2E",
            [
                sys.executable,
                "tools/composite_prompt_planning_e2e_check.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--artifact-dir",
                str(target_dir / "composite-prompt-planning" / "artifacts"),
                "--output",
                str(target_dir / "composite-prompt-planning" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "prompt undo redo E2E",
            [
                sys.executable,
                "tools/prompt_undo_redo_e2e_check.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--artifact-dir",
                str(target_dir / "prompt-undo-redo" / "artifacts"),
                "--output",
                str(target_dir / "prompt-undo-redo" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "prompt long session degradation",
            [
                sys.executable,
                "tools/prompt_long_session_degradation_check.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--artifact-dir",
                str(target_dir / "prompt-long-session" / "artifacts"),
                "--output",
                str(target_dir / "prompt-long-session" / "report.json"),
                "--json",
            ],
        ),
        Check(
            "feedback replay determinism",
            [
                "cargo",
                "test",
                "-p",
                "xace-engine-feedback",
                "feedback_replay_injects_the_same_tick_sequence",
                "--target-dir",
                str(target_dir),
            ],
        ),
        Check(
            "networked runtime smoke",
            [
                "cargo",
                "test",
                "-p",
                "xace-network-core",
                "networked_runtime_smoke_is_deterministic_across_arrival_orders",
                "--target-dir",
                str(target_dir),
            ],
        ),
        Check(
            "multiplayer topology gate",
            [
                sys.executable,
                "tools/multiplayer_topology_check.py",
                "--output",
                str(target_dir / "multiplayer-topology" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "runtime input sync gate",
            [
                sys.executable,
                "tools/runtime_input_sync_check.py",
                "--output",
                str(target_dir / "runtime-input-sync" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "runtime rollback resimulation gate",
            [
                sys.executable,
                "tools/runtime_rollback_resimulation_check.py",
                "--output",
                str(target_dir / "runtime-rollback-resimulation" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "runtime prediction reconciliation gate",
            [
                sys.executable,
                "tools/runtime_prediction_reconciliation_check.py",
                "--output",
                str(target_dir / "runtime-prediction-reconciliation" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "session lifecycle gate",
            [
                sys.executable,
                "tools/session_lifecycle_check.py",
                "--output",
                str(target_dir / "session-lifecycle" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "session compatibility gate",
            [
                sys.executable,
                "tools/session_compatibility_check.py",
                "--output",
                str(target_dir / "session-compatibility" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "malicious input limits gate",
            [
                sys.executable,
                "tools/malicious_input_limits_check.py",
                "--output",
                str(target_dir / "malicious-input-limits" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "multiplayer diagnostics gate",
            [
                sys.executable,
                "tools/multiplayer_diagnostics_check.py",
                "--output",
                str(target_dir / "multiplayer-diagnostics" / "report.json"),
                "--target-dir",
                str(target_dir),
                "--json",
            ],
        ),
        Check(
            "network chaos proof gate",
            [
                sys.executable,
                "tools/network_chaos_proof.py",
                "--full",
                "--release",
                "--duration-minutes",
                "60",
                "--tick-rate-hz",
                "60",
                "--output",
                str(target_dir / "network-chaos" / "report.json"),
                "--proof-root",
                str(target_dir / "network-chaos" / "proof"),
                "--target-dir",
                str(target_dir),
                "--run-id",
                "certify-launch-x10-043-60hz",
                "--json",
            ],
        ),
        Check(
            "multi-user soak gate",
            [
                sys.executable,
                "tools/multi_user_soak_check.py",
                "--runtime-bin",
                str(runtime_bin),
                "--sgc-bin",
                str(sgc_bin),
                "--output",
                str(target_dir / "multi-user-soak" / "report.json"),
                "--artifact-dir",
                str(target_dir / "multi-user-soak" / "artifacts"),
                "--target-dir",
                str(target_dir),
                "--cycles",
                "12",
                "--users",
                "4",
                "--prompt-changes",
                "4",
                "--json",
            ],
        ),
        Check(
            "save runtime replay",
            [
                "cargo",
                "test",
                "-p",
                "xace-save-engine",
                "runtime_checkpoint_save_load_replay_preserves_world_hash",
                "--target-dir",
                str(target_dir),
            ],
        ),
        Check(
            "save crash recovery",
            [
                "cargo",
                "test",
                "-p",
                "xace-save-engine",
                "x10_016",
                "--target-dir",
                str(target_dir),
            ],
        ),
        Check(
            "save schema migration",
            [sys.executable, "-m", "unittest", "packages/save-engine/tests/test_schema_migration.py"],
        ),
    ]

    if quick:
        keep = {
            "runtime binary",
            "runtime side-channel hash policy",
            "runtime snapshot completeness",
            "runtime snapshot serialization",
            "runtime replay divergence diagnosis",
            "mutation gate apply path",
            "static mutation conflict analysis",
            "mutation gate atomic wrapper",
            "runtime schema hot-swap",
            "runtime hot-swap compatibility classes",
            "runtime state migration hooks",
            "engine side-effect rollback",
            "SGC binary",
            "SGC CLI smoke",
            "project crash recovery",
            "builder python modules",
            "asset reference validation gate",
            "semantic binding UI gate",
            "semantic binding status gate",
            "runtime fallback binding gate",
            "import marker inventory gate",
            "manual migration wizard gate",
            "adapter reversibility gate",
            "adapter package handoff wording gate",
            "adapter package handoff preflight gate",
            "adapter package version gate",
            "canonical vertical slice fixture gate",
            "builder TypeScript production build",
            "builder UI contract",
            "tick debugger minimum gate",
            "tick debugger time-travel gate",
            "tick debugger delta-retention gate",
            "tick debugger breakpoint gate",
            "tick debugger causality graph gate",
            "tick debugger RNG seed trace gate",
            "support diagnostics bundle gate",
            "exportable debug report gate",
            "engine edit boundary",
            "forbidden public claims",
            "commercial scope record",
            "source inventory",
            "fake and skip register",
            "production path rules",
            "fixed-point authority",
            "inference adapter boundary",
            "prompt capability matrix",
            "prompt classifier gate",
            "prompt clarification loop",
            "prompt diff approval gate",
            "prompt apply atomic recovery gate",
            "prompt apply validation feedback gate",
            "prompt corpus gate",
            "prompt unknown CGS path gate",
            "prompt intelligence Python suite",
            "prompt corpus benchmark",
            "launch provider/runtime prompt benchmark",
            "deterministic simple edit benchmark",
            "prompt launch thresholds",
            "prompt security gate",
            "silent success response guard",
            "prompt pipeline contract/scenario smoke",
            "provider readiness stale policy",
            "hosted provider proof gate",
            "provider route evidence gate",
            "provider timeout retry policy",
            "provider token cost accounting",
            "provider structured output constraints",
            "builder onboarding smoke",
            "asset playback smoke",
            "runtime bridge smoke",
            "runtime SGC plan loader smoke",
            "runtime SGC schedule snapshot smoke",
            "SGC runtime proof command",
            "cross-platform replay proof local leg",
            "end-to-end CGS proof",
            "phase 1 readiness scorecard",
            "generated system safe compile smoke",
            "gameplay primitive library",
            "typed CGS operations",
            "generated system prompt E2E",
            "networked runtime smoke",
            "runtime input sync gate",
            "runtime rollback resimulation gate",
            "runtime prediction reconciliation gate",
            "session lifecycle gate",
            "session compatibility gate",
            "malicious input limits gate",
            "multiplayer diagnostics gate",
            "save runtime replay",
            "save crash recovery",
        }
        return [check for check in checks if check.label in keep]
    return checks


def _certification_report_path(args: argparse.Namespace, target_dir: Path) -> Path:
    raw = str(getattr(args, "report_path", "") or "").strip()
    if raw:
        return Path(raw).resolve()
    return (target_dir / "launch_certification_report.json").resolve()


def _installed_engine_output_dir(args: argparse.Namespace, runtime_bin: Path) -> Path:
    return Path(args.installed_engine_output_dir or (runtime_bin.parents[1] / "installed-engine-validation")).resolve()


def _command_artifact(command: list[str]) -> list[str]:
    return [str(part) for part in command]


def _result_artifact(result: Result) -> dict[str, Any]:
    return {
        "label": result.check.label,
        "status": "pass" if result.ok else "fail",
        "ok": result.ok,
        "skipped": False,
        "unsupported": False,
        "returncode": result.returncode,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "command": _command_artifact(result.check.command),
        "cwd": str(result.check.cwd),
        "stdout_tail": result.stdout_tail,
    }


def _skipped_check_artifact(check: Check, *, reason: str, unsupported: bool = False) -> dict[str, Any]:
    return {
        "label": check.label,
        "status": "skipped",
        "ok": True,
        "skipped": True,
        "unsupported": unsupported,
        "returncode": None,
        "elapsed_seconds": 0.0,
        "reason": reason,
        "command": _command_artifact(check.command),
        "cwd": str(check.cwd),
        "stdout_tail": "",
    }


def _installed_engine_skip_artifacts(
    args: argparse.Namespace,
    *,
    reason: str,
    unsupported: bool,
    requested: bool,
) -> list[dict[str, Any]]:
    required = _parse_engine_list(str(getattr(args, "require_installed_engines", "") or ""))
    artifacts: list[dict[str, Any]] = []
    for engine in CERTIFIED_ENGINES:
        required_engine = engine in required
        ok = not requested and not required_engine
        artifacts.append(
            {
                "engine": engine,
                "label": engine.title(),
                "status": "skipped",
                "ok": ok,
                "skipped": True,
                "unsupported": unsupported,
                "required": required_engine,
                "blocking": not ok,
                "detail": reason,
                "reason": reason,
                "elapsed_seconds": 0.0,
                "report_path": "",
                "report": {},
                "error": "" if ok else reason,
                "command": [],
                "stdout_tail": "",
            }
        )
    return artifacts


def _write_installed_engine_skip_summary(
    args: argparse.Namespace,
    runtime_bin: Path,
    *,
    reason: str,
    unsupported: bool,
    requested: bool,
) -> tuple[Path, dict[str, Any]]:
    output_dir = _installed_engine_output_dir(args, runtime_bin)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = _installed_engine_skip_artifacts(args, reason=reason, unsupported=unsupported, requested=requested)
    summary = {
        "schema": INSTALLED_ENGINE_SUMMARY_SCHEMA,
        "ok": all(bool(result.get("ok")) for result in results),
        "requested": requested,
        "skipped": True,
        "unsupported": unsupported,
        "xace_project": str(getattr(args, "xace_project", "") or ""),
        "runtime_bin": str(runtime_bin),
        "output_dir": str(output_dir),
        "required": sorted(_parse_engine_list(str(getattr(args, "require_installed_engines", "") or ""))),
        "results": results,
    }
    summary_path = output_dir / "installed_engine_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary_path, summary


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _installed_engine_checks_from_summary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    items = summary.get("results") if isinstance(summary.get("results"), list) else []
    checks: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ok = bool(item.get("ok"))
        skipped = bool(item.get("skipped"))
        status = str(item.get("status") or ("skipped" if skipped else ("pass" if ok else "fail")))
        engine = str(item.get("engine") or "").lower()
        checks.append(
            {
                "engine": engine,
                "label": str(item.get("label") or engine.title()),
                "status": status,
                "ok": ok,
                "skipped": skipped,
                "unsupported": bool(item.get("unsupported")),
                "required": bool(item.get("required")),
                "blocking": bool(item.get("blocking") or (not ok and (skipped or status == "fail"))),
                "detail": str(item.get("detail") or ""),
                "reason": str(item.get("reason") or item.get("detail") or ""),
                "elapsed_seconds": round(float(item.get("elapsed_seconds") or 0.0), 3),
                "report_path": str(item.get("report_path") or ""),
                "report": item.get("report") if isinstance(item.get("report"), dict) else {},
                "error": str(item.get("error") or ""),
                "command": item.get("command") if isinstance(item.get("command"), list) else [],
                "stdout_tail": str(item.get("stdout_tail") or ""),
            }
        )
    return checks


def _status_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "passed": sum(1 for item in items if item.get("status") == "pass"),
        "failed": sum(1 for item in items if item.get("status") == "fail"),
        "skipped": sum(1 for item in items if item.get("status") == "skipped"),
        "unsupported": sum(1 for item in items if item.get("unsupported")),
    }


def _certification_report(
    args: argparse.Namespace,
    *,
    target_dir: Path,
    report_path: Path,
    started_at: datetime,
    elapsed_seconds: float,
    results: list[Result],
    skipped_editor_checks: list[Check],
    installed_summary_path: Path,
    installed_summary: dict[str, Any],
) -> dict[str, Any]:
    editor_checks = [_result_artifact(result) for result in results]
    editor_skipped = [
        _skipped_check_artifact(
            check,
            reason="Not part of the --quick certification subset for this run.",
        )
        for check in skipped_editor_checks
    ]
    installed_checks = _installed_engine_checks_from_summary(installed_summary)
    editor_all = editor_checks + editor_skipped
    editor_ok = all(bool(item.get("ok")) for item in editor_checks)
    installed_ok = bool(installed_summary.get("ok", True))
    return {
        "schema": CERTIFICATION_REPORT_SCHEMA,
        "ok": editor_ok and installed_ok,
        "mode": "quick" if args.quick else "full",
        "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "target_dir": str(target_dir),
        "report_path": str(report_path),
        "editor_free": {
            "ok": editor_ok,
            "executed": len(editor_checks),
            "skipped": len(editor_skipped),
            "checks": editor_checks,
            "skipped_checks": editor_skipped,
            "summary": _status_summary(editor_all),
        },
        "installed_engines": {
            "ok": installed_ok,
            "requested": bool(args.installed_engines),
            "required": sorted(_parse_engine_list(str(getattr(args, "require_installed_engines", "") or ""))),
            "summary_path": str(installed_summary_path),
            "checks": installed_checks,
            "summary": _status_summary(installed_checks),
        },
        "artifacts": {
            "certification_report": str(report_path),
            "installed_engine_summary": str(installed_summary_path),
        },
    }


def _write_certification_report(report_path: Path, report: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[certify] report: {report_path}")


def run_installed_engine_certification(args: argparse.Namespace, runtime_bin: Path) -> int:
    print("[certify] XACE installed-engine readiness")
    if not runtime_bin.exists():
        print(f"[certify] FAIL installed engines: runtime binary not found: {runtime_bin}", file=sys.stderr)
        return 1

    xace_project = Path(str(args.xace_project or os.environ.get("XACE_PROJECT", ""))).resolve()
    if not str(args.xace_project or os.environ.get("XACE_PROJECT", "")).strip():
        print(
            "[certify] FAIL installed engines: pass --xace-project C:\\path\\to\\your\\XACE project",
            file=sys.stderr,
        )
        return 1

    helpers = _builder_helpers()
    opened = helpers["ProjectCreator"]().open_project(str(xace_project))
    output_dir = _installed_engine_output_dir(args, runtime_bin)
    output_dir.mkdir(parents=True, exist_ok=True)
    engine_paths = _installed_engine_project_paths(opened.manifest, args)
    required = _parse_engine_list(args.require_installed_engines)

    ran_any = False
    failures = 0
    results: list[InstalledEngineResult] = []
    for engine in ("godot", "unity", "unreal"):
        if required and engine not in required:
            continue
        label = engine.title()
        project_path = engine_paths.get(engine, "")
        if not project_path:
            required_missing = engine in required
            skipped = InstalledEngineResult(
                engine=engine,
                label=label,
                ok=not required_missing,
                skipped=True,
                detail=(
                    f"No {label} project path was supplied. Use --{engine}-project or save it in the XACE project dashboard."
                ),
                elapsed_seconds=0.0,
            )
            results.append(skipped)
            if required_missing:
                failures += 1
                print(f"[certify] FAIL installed {label} live validation: {skipped.detail}", flush=True)
            else:
                print(f"[certify] SKIP installed {label} live validation: {skipped.detail}", flush=True)
            continue

        ran_any = True
        print(f"[certify] RUN  installed {label} live validation", flush=True)
        started = time.perf_counter()
        try:
            if engine == "godot":
                result = _run_godot_installed_validation(opened, project_path, args.godot_exe, runtime_bin, output_dir, args)
            elif engine == "unity":
                result = _run_unity_installed_validation(opened, project_path, args.unity_exe, runtime_bin, output_dir, args)
            else:
                result = _run_unreal_installed_validation(opened, project_path, args.unreal_exe, output_dir, args)
        except Exception as exc:  # noqa: BLE001 - certification should report the first actionable error.
            result = {
                "ok": False,
                "error": str(exc),
            }
        elapsed = time.perf_counter() - started
        report = result.get("report") if isinstance(result.get("report"), dict) else None
        report_path = Path(str(result["report_path"])).resolve() if result.get("report_path") else None
        detail = _installed_engine_detail(engine, result)
        installed_result = InstalledEngineResult(
            engine=engine,
            label=label,
            ok=bool(result.get("ok")),
            skipped=False,
            detail=detail,
            elapsed_seconds=elapsed,
            report_path=report_path,
            report=report,
            raw=result,
        )
        results.append(installed_result)
        status = "PASS" if installed_result.ok else "FAIL"
        if not installed_result.ok:
            failures += 1
        print(f"[certify] {status} installed {label} live validation ({elapsed:.1f}s): {detail}", flush=True)

    if not ran_any and not required:
        print(
            "[certify] FAIL installed engines: no engine project paths were found. "
            "Pass --godot-project, --unity-project, or --unreal-project.",
            file=sys.stderr,
        )
        return 1

    summary_path = output_dir / "installed_engine_summary.json"
    summary = {
        "schema": INSTALLED_ENGINE_SUMMARY_SCHEMA,
        "ok": failures == 0,
        "requested": True,
        "skipped": False,
        "unsupported": False,
        "xace_project": str(xace_project),
        "runtime_bin": str(runtime_bin),
        "output_dir": str(output_dir),
        "required": sorted(required),
        "results": [
            {
                "engine": result.engine,
                "label": result.label,
                "status": "skipped" if result.skipped else ("pass" if result.ok else "fail"),
                "ok": result.ok,
                "skipped": result.skipped,
                "unsupported": result.skipped,
                "required": result.engine in required,
                "blocking": not result.ok,
                "detail": result.detail,
                "reason": result.detail if result.skipped else "",
                "elapsed_seconds": round(result.elapsed_seconds, 3),
                "report_path": str(result.report_path) if result.report_path else "",
                "report": result.report or {},
                "error": str((result.raw or {}).get("error") or ""),
                "command": (result.raw or {}).get("command") or [],
                "stdout_tail": str((result.raw or {}).get("stdout_tail") or ""),
            }
            for result in results
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[certify] installed-engine summary: {summary_path}")
    if failures:
        print(f"[certify] installed-engine readiness FAILED ({failures} failing check(s))", file=sys.stderr)
        return 1
    print("[certify] installed-engine readiness PASSED")
    return 0


def _run_godot_installed_validation(
    opened: Any,
    engine_project_path: str,
    executable_path: str,
    runtime_bin: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    helpers = _builder_helpers()
    engine_root = Path(engine_project_path).resolve()
    prepared = helpers["_install_project_adapter"](opened.project_dir, "godot")
    if not prepared.get("ok"):
        return {"ok": False, "error": prepared.get("error", "Godot adapter preparation failed."), "adapter_prepare": prepared}
    install = helpers["_copy_named_adapter_to_engine_project"](
        project_dir=opened.project_dir,
        manifest=opened.manifest,
        engine_type="godot",
        engine_project_path=str(engine_root),
        overwrite=True,
        save_primary_config=False,
    )
    if not install.get("ok"):
        return {"ok": False, "error": install.get("error", "Godot adapter install failed."), "adapter_install": install}

    scene_path = engine_root / "scenes" / "xace_runtime_scene.tscn"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene_path.write_text(helpers["_godot_runtime_scene_text"](), encoding="utf-8")
    runner_path = engine_root / "addons" / "xace" / "xace_certification_runner.gd"
    runner_path.write_text(_godot_certification_runner_text(), encoding="utf-8")

    executable = _resolve_cert_executable("godot", executable_path)
    if executable is None:
        return {
            "ok": False,
            "error": "Godot executable was not found. Pass --godot-exe C:\\path\\to\\Godot.exe.",
            "adapter_install": install,
        }

    runtime = _start_cert_runtime(opened, runtime_bin, args, preferred_engine_port=7777)
    process: subprocess.Popen[str] | None = None
    log_handle: Any | None = None
    result: dict[str, Any] | None = None
    report_path = output_dir / "godot_live_validation.json"
    log_path = output_dir / "godot_live_validation.log"
    if report_path.exists():
        report_path.unlink()
    if log_path.exists():
        log_path.unlink()
    try:
        cgs_hash = _load_project_cgs_hash(Path(opened.project_dir).resolve(), opened.manifest)
        command = [
            str(executable),
            "--headless",
            "--script",
            str(runner_path),
            "--path",
            str(engine_root),
            "--",
            "--xace-host=127.0.0.1",
            f"--xace-port={runtime['engine_port']}",
            f"--xace-cgs-hash={cgs_hash}",
            f"--xace-cert-timeout={int(float(args.installed_engine_timeout))}",
            f"--xace-cert-output={report_path}",
        ]
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=str(engine_root),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        proof = _wait_for_godot_live_proof(
            runtime["control"],
            report_path,
            timeout_seconds=float(args.installed_engine_timeout),
            process=process,
        )
        result = {
            "ok": bool(proof.get("ok")),
            "engine": "godot",
            "command": command,
            "adapter_prepare": prepared,
            "adapter_install": install,
            "report_path": str(report_path),
            "log_path": str(log_path),
            "report": proof,
            "error": proof.get("error", ""),
        }
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if log_handle is not None:
            log_handle.close()
        helpers["_stop_demo_runtime"](runtime["control"], runtime["process"])
    if result is None:
        result = {"ok": False, "error": "Godot validation did not produce a result."}
    if log_path.exists():
        result["stdout_tail"] = _tail_text(log_path.read_text(encoding="utf-8", errors="replace"))
    else:
        result["stdout_tail"] = _collect_process_tail(process)
    return result


def _run_unity_installed_validation(
    opened: Any,
    engine_project_path: str,
    executable_path: str,
    runtime_bin: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    helpers = _builder_helpers()
    engine_root = Path(engine_project_path).resolve()
    prepared = helpers["_install_project_adapter"](opened.project_dir, "unity")
    if not prepared.get("ok"):
        return {"ok": False, "error": prepared.get("error", "Unity adapter preparation failed."), "adapter_prepare": prepared}
    install = helpers["_copy_named_adapter_to_engine_project"](
        project_dir=opened.project_dir,
        manifest=opened.manifest,
        engine_type="unity",
        engine_project_path=str(engine_root),
        overwrite=True,
        save_primary_config=False,
    )
    if not install.get("ok"):
        return {"ok": False, "error": install.get("error", "Unity adapter install failed."), "adapter_install": install}

    executable = _resolve_cert_executable("unity", executable_path)
    if executable is None:
        return {
            "ok": False,
            "error": "Unity executable was not found. Pass --unity-exe C:\\path\\to\\Unity.exe.",
            "adapter_install": install,
        }

    runtime = _start_cert_runtime(opened, runtime_bin, args)
    report_path = output_dir / "unity_live_validation.json"
    command = [
        str(executable),
        "-batchmode",
        "-nographics",
        "-quit",
        "-projectPath",
        str(engine_root),
        "-executeMethod",
        "Xace.Adapter.Unity.Editor.XaceUnityLiveValidationCommand.Run",
        "--xace-port",
        str(runtime["engine_port"]),
        "--xace-validation-output",
        str(report_path),
        "--xace-validation-seconds",
        str(int(args.installed_engine_timeout)),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(engine_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=max(60.0, float(args.installed_engine_timeout) + 120.0),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": command,
            "report_path": str(report_path),
            "error": "Unity live validation timed out.",
            "stdout_tail": _tail_text(exc.stdout),
        }
    finally:
        helpers["_stop_demo_runtime"](runtime["control"], runtime["process"])

    report = _read_json_report(report_path)
    return {
        "ok": completed.returncode == 0 and bool(report.get("ok")),
        "engine": "unity",
        "command": command,
        "exit_code": completed.returncode,
        "adapter_prepare": prepared,
        "adapter_install": install,
        "report_path": str(report_path),
        "report": report,
        "stdout_tail": _tail_text(completed.stdout),
        "error": str(report.get("error") or "") if completed.returncode == 0 else "Unity live validation failed.",
    }


def _run_unreal_installed_validation(
    opened: Any,
    engine_project_path: str,
    executable_path: str,
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    helpers = _builder_helpers()
    control_port = helpers["_find_free_tcp_port"]()
    runtime_control = helpers["RuntimeControlClient"](helpers["RuntimeControlConfig"](
        host="127.0.0.1",
        port=control_port,
        timeout_seconds=2.0,
    ))
    result = helpers["_run_unreal_live_validation_from_builder"](
        Path(opened.project_dir).resolve(),
        opened.manifest,
        engine_project_path,
        executable_path,
        runtime_control,
        None,
    )
    commandlet = result.get("commandlet") if isinstance(result.get("commandlet"), dict) else {}
    if commandlet.get("report_path"):
        result["report_path"] = str(commandlet["report_path"])
    return result


def _start_cert_runtime(
    opened: Any,
    runtime_bin: Path,
    args: argparse.Namespace,
    *,
    preferred_engine_port: int | None = None,
) -> dict[str, Any]:
    helpers = _builder_helpers()
    engine_port = (
        int(preferred_engine_port)
        if preferred_engine_port and _tcp_port_is_free(int(preferred_engine_port))
        else helpers["_find_free_tcp_port"]()
    )
    control_port = helpers["_find_free_tcp_port"](avoid={engine_port})
    control = helpers["RuntimeControlClient"](helpers["RuntimeControlConfig"](
        host="127.0.0.1",
        port=control_port,
        timeout_seconds=2.0,
    ))
    cgs_path = helpers["_project_cgs_path"](Path(opened.project_dir).resolve(), opened.manifest)
    command = helpers["_demo_runtime_launch_command"](runtime_bin, cgs_path, engine_port, control_port)
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    status = helpers["_wait_for_runtime_status"](control, process, engine_port, timeout_seconds=8.0)
    if not status.get("running"):
        raise RuntimeError(status.get("error") or status.get("reason") or "Temporary runtime did not start.")
    return {
        "control": control,
        "process": process,
        "engine_port": engine_port,
        "control_port": control_port,
        "status": status,
        "command": command,
    }


def _tcp_port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def _wait_for_godot_live_proof(
    runtime_control: Any,
    report_path: Path,
    *,
    timeout_seconds: float,
    process: subprocess.Popen[str],
) -> dict[str, Any]:
    helpers = _builder_helpers()
    deadline = time.monotonic() + timeout_seconds
    last_runtime_status: dict[str, Any] = {}
    last_runtime_proof: dict[str, Any] = {}
    last_godot_report: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_runtime_status = helpers["_demo_runtime_status"](runtime_control, process=None)
        last_runtime_proof = _engine_connection_proof_from_runtime_status(last_runtime_status, "godot")
        if last_runtime_proof.get("ok"):
            last_runtime_proof["source"] = "runtime_status"
            if report_path.exists():
                last_runtime_proof["godot_report"] = _read_json_report(report_path)
            return last_runtime_proof
        if report_path.exists():
            last_godot_report = _read_json_report(report_path)
            if last_godot_report.get("ok"):
                return _godot_report_to_live_proof(last_godot_report, last_runtime_status)
        if process.poll() is not None:
            break
        time.sleep(0.5)

    if report_path.exists():
        last_godot_report = _read_json_report(report_path)
        if last_godot_report.get("ok"):
            return _godot_report_to_live_proof(last_godot_report, last_runtime_status)
    elif not last_godot_report:
        last_godot_report = {"ok": False, "error": f"Godot report was not written: {report_path}"}

    proof = last_runtime_proof or _engine_connection_proof_from_runtime_status(last_runtime_status, "godot")
    proof["source"] = "runtime_status"
    proof["godot_report"] = last_godot_report
    proof["runtime_status"] = last_runtime_status
    if process.poll() is not None:
        proof["error"] = proof.get("error") or "Godot process exited before live proof was complete."
    else:
        proof["error"] = proof.get("error") or "Godot live proof timed out."
    return proof


def _godot_report_to_live_proof(report: dict[str, Any], runtime_status: dict[str, Any]) -> dict[str, Any]:
    snapshots = int(report.get("snapshots_received") or 0)
    inputs = int(report.get("input_packets_sent") or 0)
    feedback = int(report.get("feedback_payloads_sent") or 0)
    malformed = int(report.get("malformed_messages") or 0)
    ok = (
        bool(report.get("connected"))
        and bool(report.get("handshake_complete"))
        and snapshots > 0
        and inputs > 0
        and feedback > 0
        and malformed == 0
    )
    return {
        "ok": ok,
        "source": "godot_report",
        "connected": bool(report.get("connected")),
        "handshake_complete": bool(report.get("handshake_complete")),
        "snapshots_received": snapshots,
        "snapshots_sent": snapshots,
        "input_packets_sent": inputs,
        "input_packets_received": inputs,
        "feedback_payloads_sent": feedback,
        "feedback_messages_received": feedback,
        "malformed_messages": malformed,
        "snapshot_hash": report.get("snapshot_hash") or runtime_status.get("snapshot_hash") or "",
        "tick": report.get("last_runtime_tick") or runtime_status.get("snapshot_tick") or runtime_status.get("tick"),
        "godot_report": report,
        "runtime_status": runtime_status,
        "error": "" if ok else "Godot report has not reached full live proof yet.",
    }


def _wait_for_engine_connection_proof(
    runtime_control: Any,
    engine: str,
    *,
    timeout_seconds: float,
    process: subprocess.Popen[str] | None = None,
) -> dict[str, Any]:
    helpers = _builder_helpers()
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = helpers["_demo_runtime_status"](runtime_control, process=None)
        proof = _engine_connection_proof_from_runtime_status(last_status, engine)
        if proof.get("ok"):
            return proof
        if process is not None and process.poll() is not None:
            proof["error"] = f"{engine.title()} process exited before live proof was complete."
            proof["runtime_status"] = last_status
            return proof
        time.sleep(0.5)
    proof = _engine_connection_proof_from_runtime_status(last_status, engine)
    proof["error"] = proof.get("error") or f"{engine.title()} live proof timed out."
    proof["runtime_status"] = last_status
    return proof


def _engine_connection_proof_from_runtime_status(status: dict[str, Any], engine: str) -> dict[str, Any]:
    connection = {}
    for item in status.get("engine_connections", []) or []:
        if isinstance(item, dict) and str(item.get("engine", "")).lower() == engine:
            connection = item
            break
    snapshots = int(connection.get("snapshots_sent") or 0)
    inputs = int(connection.get("input_packets_received") or 0)
    feedback = int(connection.get("feedback_messages_received") or 0)
    malformed = int(connection.get("malformed_messages") or 0)
    ok = bool(connection.get("connected")) and snapshots > 0 and inputs > 0 and feedback > 0 and malformed == 0
    return {
        "ok": ok,
        "connected": bool(connection.get("connected")),
        "snapshots_sent": snapshots,
        "input_packets_received": inputs,
        "feedback_messages_received": feedback,
        "malformed_messages": malformed,
        "snapshot_hash": connection.get("snapshot_hash") or status.get("snapshot_hash") or "",
        "tick": connection.get("tick") or status.get("snapshot_tick") or status.get("tick"),
        "error": "" if ok else "Runtime counters have not reached full live proof yet.",
    }


def _installed_engine_project_paths(manifest: Any, args: argparse.Namespace) -> dict[str, str]:
    adapter_config = dict(getattr(manifest, "adapter_config", {}) or {})
    demo = adapter_config.get("demo_engine_projects")
    saved_demo = demo if isinstance(demo, dict) else {}
    paths = {
        "godot": str(args.godot_project or saved_demo.get("godot") or ""),
        "unity": str(args.unity_project or saved_demo.get("unity") or ""),
        "unreal": str(args.unreal_project or saved_demo.get("unreal") or ""),
    }
    primary_engine = str(getattr(manifest, "engine_type", "") or "").lower()
    primary_path = str(adapter_config.get("engine_project_path") or "")
    if primary_engine in paths and not paths[primary_engine] and primary_path:
        paths[primary_engine] = primary_path
    return {key: value.strip() for key, value in paths.items()}


def _resolve_cert_executable(engine: str, explicit: str) -> Path | None:
    helpers = _builder_helpers()
    resolved = helpers["_resolve_engine_executable"](engine, explicit)
    if resolved is not None:
        return resolved
    if engine == "godot":
        env_bin = os.environ.get("GODOT_BIN", "")
        if env_bin:
            candidate = Path(env_bin).resolve()
            if candidate.exists() and candidate.is_file():
                return candidate
        downloads = Path.home() / "Downloads"
        candidates = []
        if downloads.exists():
            candidates.extend(downloads.glob("Godot*.exe"))
            candidates.extend(downloads.glob("Godot*/Godot*.exe"))
        console = [path for path in candidates if path.is_file() and path.name.endswith("_console.exe")]
        normal = [path for path in candidates if path.is_file()]
        if console:
            return console[0].resolve()
        if normal:
            return normal[0].resolve()
    return None


def _load_project_cgs_hash(project_dir: Path, manifest: Any) -> str:
    helpers = _builder_helpers()
    cgs_path = helpers["_project_cgs_path"](project_dir, manifest)
    with cgs_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return str(data.get("metadata", {}).get("cgs_hash", ""))


def _godot_certification_runner_text() -> str:
    return "\n".join([
        "extends SceneTree",
        "",
        "var _deadline_msec := 0",
        "var _started := false",
        "var _main_node: Node",
        "var _report_path := \"\"",
        "",
        "",
        "func _init() -> void:",
        "\tcall_deferred(\"_start_runner\")",
        "",
        "",
        "func _initialize() -> void:",
        "\tcall_deferred(\"_start_runner\")",
        "",
        "",
        "func _start_runner() -> void:",
        "\tif _started:",
        "\t\treturn",
        "\t_started = true",
        "\tprint(\"[XACE] Godot certification runner starting\")",
        "\t_report_path = _cert_output_path()",
        "\tvar main_script: Script = load(\"res://addons/xace/xace_godot_main.gd\")",
        "\tif main_script == null:",
        "\t\tpush_error(\"XACE Godot certification runner could not load xace_godot_main.gd\")",
        "\t\t_write_report(_build_error_report(\"script_load_failed\"))",
        "\t\tquit(2)",
        "\t\treturn",
        "\t_main_node = main_script.new()",
        "\t_main_node.name = \"XaceCertificationMain\"",
        "\troot.add_child(_main_node)",
        "\tprint(\"[XACE] Godot certification runner added XACE main node\")",
        "\t_deadline_msec = Time.get_ticks_msec() + _cert_timeout_msec()",
        "\t_write_report(_build_report(\"started\"))",
        "",
        "",
        "func _process(_delta: float) -> bool:",
        "\tvar report := _build_report(\"running\")",
        "\tif bool(report.get(\"ok\", false)):",
        "\t\treport[\"reason\"] = \"passed\"",
        "\t\t_write_report(report)",
        "\t\tquit(0)",
        "\t\treturn false",
        "\tif Time.get_ticks_msec() >= _deadline_msec:",
        "\t\treport[\"reason\"] = \"timeout\"",
        "\t\t_write_report(report)",
        "\t\tquit(1)",
        "\treturn false",
        "",
        "",
        "func _cert_timeout_msec() -> int:",
        "\tfor arg in OS.get_cmdline_user_args():",
        "\t\tif arg.begins_with(\"--xace-cert-timeout=\"):",
        "\t\t\treturn max(1000, int(float(arg.substr(\"--xace-cert-timeout=\".length())) * 1000.0))",
        "\treturn 30000",
        "",
        "",
        "func _cert_output_path() -> String:",
        "\tfor arg in OS.get_cmdline_user_args():",
        "\t\tif arg.begins_with(\"--xace-cert-output=\"):",
        "\t\t\treturn arg.substr(\"--xace-cert-output=\".length())",
        "\treturn \"user://xace_godot_live_validation.json\"",
        "",
        "",
        "func _build_error_report(reason: String) -> Dictionary:",
        "\treturn {",
        "\t\t\"ok\": false,",
        "\t\t\"engine\": \"godot\",",
        "\t\t\"reason\": reason,",
        "\t\t\"connected\": false,",
        "\t\t\"handshake_complete\": false,",
        "\t\t\"snapshots_received\": 0,",
        "\t\t\"input_packets_sent\": 0,",
        "\t\t\"feedback_payloads_sent\": 0,",
        "\t\t\"malformed_messages\": 0,",
        "\t}",
        "",
        "",
        "func _build_report(reason: String) -> Dictionary:",
        "\tvar transport := _main_node.get_node_or_null(\"XaceTransport\") if _main_node != null else null",
        "\tvar adapter := _main_node.get_node_or_null(\"XaceAdapter\") if _main_node != null else null",
        "\tvar delta_applicator := _main_node.get_node_or_null(\"XaceDeltaApplicator\") if _main_node != null else null",
        "\tvar transport_stats := _node_stats(transport)",
        "\tvar adapter_stats := _node_stats(adapter)",
        "\tvar delta_stats := _node_stats(delta_applicator)",
        "\tvar connected := false",
        "\tif transport != null and transport.has_method(\"is_runtime_connected\"):",
        "\t\tconnected = bool(transport.call(\"is_runtime_connected\"))",
        "\tvar handshake_complete := false",
        "\tif transport != null and transport.has_method(\"is_handshake_complete\"):",
        "\t\thandshake_complete = bool(transport.call(\"is_handshake_complete\"))",
        "\tvar snapshots_received := int(delta_stats.get(\"messages_applied\", 0))",
        "\tvar input_packets_sent := int(adapter_stats.get(\"input_packets_sent\", 0))",
        "\tvar feedback_payloads_sent := int(adapter_stats.get(\"feedback_payloads_sent\", 0))",
        "\tvar malformed_messages := int(transport_stats.get(\"malformed_frames\", 0))",
        "\tvar ok := connected and handshake_complete and snapshots_received > 0 and input_packets_sent > 0 and feedback_payloads_sent > 0 and malformed_messages == 0",
        "\treturn {",
        "\t\t\"ok\": ok,",
        "\t\t\"engine\": \"godot\",",
        "\t\t\"reason\": reason,",
        "\t\t\"connected\": connected,",
        "\t\t\"handshake_complete\": handshake_complete,",
        "\t\t\"snapshots_received\": snapshots_received,",
        "\t\t\"input_packets_sent\": input_packets_sent,",
        "\t\t\"feedback_payloads_sent\": feedback_payloads_sent,",
        "\t\t\"malformed_messages\": malformed_messages,",
        "\t\t\"last_runtime_tick\": int(adapter_stats.get(\"last_runtime_tick\", 0)),",
        "\t\t\"entity_count\": int(adapter_stats.get(\"entity_count\", 0)),",
        "\t\t\"snapshot_hash\": str(adapter_stats.get(\"snapshot_hash\", \"\")),",
        "\t\t\"transport\": transport_stats,",
        "\t\t\"adapter\": adapter_stats,",
        "\t\t\"delta_applicator\": delta_stats,",
        "\t}",
        "",
        "",
        "func _node_stats(node: Node) -> Dictionary:",
        "\tif node == null or not node.has_method(\"stats\"):",
        "\t\treturn {}",
        "\tvar value: Variant = node.call(\"stats\")",
        "\tif typeof(value) != TYPE_DICTIONARY:",
        "\t\treturn {}",
        "\treturn value as Dictionary",
        "",
        "",
        "func _write_report(report: Dictionary) -> void:",
        "\tif _report_path.is_empty():",
        "\t\treturn",
        "\tvar file := FileAccess.open(_report_path, FileAccess.WRITE)",
        "\tif file == null:",
        "\t\tpush_error(\"XACE Godot certification runner could not write report: %s\" % _report_path)",
        "\t\treturn",
        "\tfile.store_string(JSON.stringify(report, \"\\t\"))",
        "\tfile.close()",
        "",
    ])


def _read_json_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "error": f"Report was not written: {path}"}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
    return value if isinstance(value, dict) else {"ok": False, "error": "Report was not a JSON object."}


def _installed_engine_detail(engine: str, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return str(result.get("error") or result.get("reason") or "validation failed")
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    if engine == "godot":
        snapshots = report.get("snapshots_sent", report.get("snapshots_received"))
        inputs = report.get("input_packets_received", report.get("input_packets_sent"))
        feedback = report.get("feedback_messages_received", report.get("feedback_payloads_sent"))
        return (
            f"connected={report.get('connected')}, snapshots={snapshots}, "
            f"inputs={inputs}, feedback={feedback}, malformed={report.get('malformed_messages')}, "
            f"source={report.get('source', 'runtime_status')}"
        )
    if engine == "unity":
        return (
            f"connected={report.get('connected')}, handshake={report.get('handshake_accepted')}, "
            f"snapshots={report.get('snapshots')}, applied={report.get('applied_snapshots')}, "
            f"entities={report.get('applied_entities')}, feedback={report.get('feedback_ready')}, "
            f"protocol_errors={report.get('protocol_errors')}"
        )
    if engine == "unreal":
        return str(result.get("summary") or _unreal_report_detail(report))
    return "validation passed"


def _unreal_report_detail(report: dict[str, Any]) -> str:
    return (
        f"connected={report.get('connected')}, handshake={report.get('handshake_accepted')}, "
        f"snapshots={report.get('applied_snapshots')}, entities={report.get('applied_entities')}, "
        f"input={report.get('input_packets_built')}, feedback={report.get('feedback_ready')}, "
        f"protocol_errors={report.get('protocol_errors')}"
    )


def _parse_engine_list(raw: str) -> set[str]:
    if not raw.strip():
        return set()
    allowed = {"godot", "unity", "unreal"}
    out = {item.strip().lower() for item in raw.split(",") if item.strip()}
    unknown = out - allowed
    if unknown:
        raise SystemExit(f"Unknown engine(s) in --require-installed-engines: {', '.join(sorted(unknown))}")
    return out


def _builder_helpers() -> dict[str, Any]:
    if str(BUILDER_SERVER) not in sys.path:
        sys.path.insert(0, str(BUILDER_SERVER))
    if str(PROJECT_SYSTEM) not in sys.path:
        sys.path.insert(0, str(PROJECT_SYSTEM))
    from builder_server import (  # noqa: PLC0415
        _copy_named_adapter_to_engine_project,
        _demo_runtime_launch_command,
        _demo_runtime_status,
        _find_free_tcp_port,
        _godot_runtime_scene_text,
        _install_project_adapter,
        _project_cgs_path,
        _resolve_engine_executable,
        _run_unreal_live_validation_from_builder,
        _stop_demo_runtime,
        _wait_for_runtime_status,
    )
    from project_creator import ProjectCreator  # noqa: PLC0415
    from runtime_control_client import RuntimeControlClient, RuntimeControlConfig  # noqa: PLC0415

    return {
        "ProjectCreator": ProjectCreator,
        "RuntimeControlClient": RuntimeControlClient,
        "RuntimeControlConfig": RuntimeControlConfig,
        "_copy_named_adapter_to_engine_project": _copy_named_adapter_to_engine_project,
        "_demo_runtime_launch_command": _demo_runtime_launch_command,
        "_demo_runtime_status": _demo_runtime_status,
        "_find_free_tcp_port": _find_free_tcp_port,
        "_godot_runtime_scene_text": _godot_runtime_scene_text,
        "_install_project_adapter": _install_project_adapter,
        "_project_cgs_path": _project_cgs_path,
        "_resolve_engine_executable": _resolve_engine_executable,
        "_run_unreal_live_validation_from_builder": _run_unreal_live_validation_from_builder,
        "_stop_demo_runtime": _stop_demo_runtime,
        "_wait_for_runtime_status": _wait_for_runtime_status,
    }


def _collect_process_tail(process: subprocess.Popen[str] | None) -> str:
    if process is None or process.stdout is None:
        return ""
    if process.poll() is None:
        return ""
    try:
        output = process.stdout.read()
    except OSError:
        return ""
    return _tail_text(output)


def _tail_text(value: Any, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return str(value)[-limit:]


def run_check(check: Check, *, verbose: bool) -> Result:
    print(f"[certify] RUN  {check.label}", flush=True)
    started = time.perf_counter()
    stdout = None if verbose else subprocess.PIPE
    stderr = None if verbose else subprocess.STDOUT
    completed = subprocess.run(
        check.command,
        cwd=str(check.cwd),
        stdout=stdout,
        stderr=stderr,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started
    stdout_tail = _tail_text(completed.stdout)
    if completed.returncode != 0 and not verbose and completed.stdout:
        print(completed.stdout[-6000:], file=sys.stderr)
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"[certify] {status} {check.label} ({elapsed:.1f}s)", flush=True)
    return Result(check=check, returncode=completed.returncode, elapsed_seconds=elapsed, stdout_tail=stdout_tail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run XACE launch readiness certification.")
    parser.add_argument(
        "--target-dir",
        default=str(DEFAULT_TARGET_DIR),
        help="Cargo target directory used by certification builds/tests.",
    )
    parser.add_argument(
        "--report-path",
        default="",
        help="JSON report path. Defaults to <target-dir>/launch_certification_report.json.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run the shorter smoke-focused certification subset.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Stream command output instead of showing only failures and summary lines.",
    )
    parser.add_argument(
        "--installed-engines",
        action="store_true",
        help="Also run real installed-editor validation for supplied/saved Godot, Unity, and Unreal projects.",
    )
    parser.add_argument(
        "--xace-project",
        default=os.environ.get("XACE_PROJECT", ""),
        help="XACE project folder used by installed-engine validation.",
    )
    parser.add_argument(
        "--godot-project",
        default=os.environ.get("XACE_GODOT_PROJECT", ""),
        help="Godot project folder for installed-engine validation.",
    )
    parser.add_argument(
        "--unity-project",
        default=os.environ.get("XACE_UNITY_PROJECT", ""),
        help="Unity project folder for installed-engine validation.",
    )
    parser.add_argument(
        "--unreal-project",
        default=os.environ.get("XACE_UNREAL_PROJECT", ""),
        help="Unreal project folder for installed-engine validation.",
    )
    parser.add_argument(
        "--godot-exe",
        default=os.environ.get("XACE_GODOT_EXE", ""),
        help="Path to Godot executable for installed-engine validation.",
    )
    parser.add_argument(
        "--unity-exe",
        default=os.environ.get("XACE_UNITY_EXE", ""),
        help="Path to Unity executable for installed-engine validation.",
    )
    parser.add_argument(
        "--unreal-exe",
        default=os.environ.get("XACE_UNREAL_EXE", ""),
        help="Path to UnrealEditor.exe for installed-engine validation.",
    )
    parser.add_argument(
        "--require-installed-engines",
        default="",
        help="Comma-separated engines that must run when --installed-engines is used, for example godot,unity,unreal.",
    )
    parser.add_argument(
        "--installed-engine-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for each installed engine live proof after the editor starts.",
    )
    parser.add_argument(
        "--installed-engine-output-dir",
        default="",
        help="Folder for installed-engine JSON reports. Defaults under the certification target dir.",
    )
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    target_dir = Path(args.target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    report_path = _certification_report_path(args, target_dir)
    runtime_bin = target_dir / "debug" / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
    full_checks = build_checks(target_dir, quick=False)
    checks = build_checks(target_dir, quick=args.quick)
    selected_labels = {check.label for check in checks}
    skipped_editor_checks = [check for check in full_checks if args.quick and check.label not in selected_labels]
    print("[certify] XACE editor-free launch readiness")
    print(f"[certify] Checks: {len(checks)}")
    print(f"[certify] Target dir: {target_dir}")
    print(f"[certify] Report: {report_path}")
    if skipped_editor_checks:
        print(f"[certify] Quick mode will record {len(skipped_editor_checks)} skipped full-mode check(s).")

    results: list[Result] = []
    for check in checks:
        result = run_check(check, verbose=bool(args.verbose))
        results.append(result)
        if not result.ok:
            reason = (
                "Installed-engine validation was not reached because editor-free certification failed."
                if args.installed_engines
                else "Installed-engine validation was not requested for this run."
            )
            installed_summary_path, installed_summary = _write_installed_engine_skip_summary(
                args,
                runtime_bin,
                reason=reason,
                unsupported=True,
                requested=bool(args.installed_engines),
            )
            report = _certification_report(
                args,
                target_dir=target_dir,
                report_path=report_path,
                started_at=started_at,
                elapsed_seconds=time.perf_counter() - started,
                results=results,
                skipped_editor_checks=skipped_editor_checks,
                installed_summary_path=installed_summary_path,
                installed_summary=installed_summary,
            )
            _write_certification_report(report_path, report)
            print("[certify] launch readiness FAILED", file=sys.stderr)
            print(f"[certify] first failed check: {check.label}", file=sys.stderr)
            return result.returncode or 1

    total = sum(result.elapsed_seconds for result in results)
    print(f"[certify] editor-free launch readiness PASSED ({len(results)} checks, {total:.1f}s)")
    if args.installed_engines:
        installed = run_installed_engine_certification(args, runtime_bin)
        installed_summary_path = _installed_engine_output_dir(args, runtime_bin) / "installed_engine_summary.json"
        installed_summary = _read_json_object(installed_summary_path)
        if not installed_summary:
            installed_summary = {
                "schema": INSTALLED_ENGINE_SUMMARY_SCHEMA,
                "ok": False,
                "requested": True,
                "skipped": True,
                "unsupported": True,
                "runtime_bin": str(runtime_bin),
                "output_dir": str(installed_summary_path.parent),
                "required": sorted(_parse_engine_list(str(getattr(args, "require_installed_engines", "") or ""))),
                "results": _installed_engine_skip_artifacts(
                    args,
                    reason="Installed-engine validation failed before writing its summary artifact.",
                    unsupported=True,
                    requested=True,
                ),
            }
            installed_summary_path.parent.mkdir(parents=True, exist_ok=True)
            installed_summary_path.write_text(json.dumps(installed_summary, indent=2), encoding="utf-8")
    else:
        installed_summary_path, installed_summary = _write_installed_engine_skip_summary(
            args,
            runtime_bin,
            reason=(
                "Installed-engine validation was not requested for this run. "
                "Use --installed-engines with project paths to replace unsupported entries with real proof."
            ),
            unsupported=True,
            requested=False,
        )
        print("[certify] installed-engine validation skipped; unsupported entries recorded in artifact.")

    report = _certification_report(
        args,
        target_dir=target_dir,
        report_path=report_path,
        started_at=started_at,
        elapsed_seconds=time.perf_counter() - started,
        results=results,
        skipped_editor_checks=skipped_editor_checks,
        installed_summary_path=installed_summary_path,
        installed_summary=installed_summary,
    )
    _write_certification_report(report_path, report)
    if not bool(report.get("ok")):
        print("[certify] launch readiness FAILED", file=sys.stderr)
        if not args.installed_engines and _parse_engine_list(str(getattr(args, "require_installed_engines", "") or "")):
            print("[certify] installed-engine validation was required but --installed-engines was not passed.", file=sys.stderr)
        return installed if args.installed_engines and installed != 0 else 1
    if args.installed_engines:
        print("[certify] launch readiness PASSED with installed-engine validation")
    else:
        print("[certify] launch readiness PASSED with installed-engine skips explicitly recorded as unsupported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
