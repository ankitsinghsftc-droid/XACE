# XACE Source Of Truth Inventory

Inventory date: 2026-08-22

This file is the human-readable source inventory for Task 2 of
`XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md`. The machine-readable inventory
is `docs/source_inventory.json`, and `tools/source_inventory_check.py` validates
that the current repository tree is covered.

## Status Keys

- `production-source`: active source, manifests, docs, launchers, governance, or product tooling.
- `production-source-uncovered`: active/intended source that is not yet covered by the root Cargo, uv, or npm workspace manifests.
- `test-only`: tests, fixtures, smoke tools, proof generators, or benchmark helpers that must not be presented as product behavior by themselves.
- `archived`: historical, superseded, placeholder, or legacy material retained only for context.
- `generated`: build output, local state, proof artifacts, dependency installs, or generated files.
- `external`: outside-repo systems, installed engines, user projects, provider services, OS stores, or local agent/VCS metadata.

## Authoritative Manifests

- Rust workspace: `Cargo.toml`.
- JavaScript workspace: `package.json`.
- Python workspace: `pyproject.toml`.
- Commercial launch model: `docs/XACE_COMMERCIAL_SCOPE.md`.
- Reality baseline: `XACE_REALITY_AUDIT.md`.
- Baseline failure list: `docs/XACE_BASELINE_FAILURE_LIST.md`.
- Execution sequence: `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md`.
- Machine inventory: `docs/source_inventory.json`.
- Fake/skip register: `docs/fake_skip_register.json`.
- Production path rules: `docs/production_path_rules.json`.

## Root Paths

| Path | Status | Notes |
| --- | --- | --- |
| `.github` | production-source | Hosted CI workflow root. |
| `.git` | external | Git metadata. |
| `.agents`, `.codex` | external | Local agent metadata, not product source. |
| `.env.example` | production-source | Non-secret local environment template. |
| `.gitignore` | production-source | Repository ignore rules. |
| `.vscode` | external | Local/editor settings, not runtime source. |
| `.VSCodeCounter`, `.pytest_cache` | generated | Local code-count and pytest cache output. |
| `.xace` | generated | Local runtime/proof state unless a future task promotes a fixture. |
| `target*`, `node_modules`, `output`, `tmp` | generated | Build/proof output, root dependency install output, local document output, and temporary/vendor workspace artifacts. |
| `Cargo.toml`, `Cargo.lock` | production-source | Rust workspace and lockfile. |
| `package.json`, `package-lock.json` | production-source | npm workspace and lockfile. |
| `pyproject.toml`, `requirements.txt`, `tsconfig.json` | production-source | Python/TypeScript/dependency configuration. |
| `README.md` | production-source | Primary public boundary document. |
| `Start XACE Builder.cmd` | production-source | Local Windows Builder launcher. |
| `game.cgs.json` | production-source | Root starter/demo CGS. |
| `XACE_REALITY_AUDIT.md`, `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md`, `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md` | production-source | Current governance docs. |
| `MASTER_PLAN.md`, `XACE_FILE_MANIFEST(LATEST).md`, `CLAUDE.md` | archived | Historical planning/context inputs, not current product truth. |
| `test_m2_handshake.py` | test-only | Standalone test script. |

## Packages

| Path | Status | Notes |
| --- | --- | --- |
| `packages/core` | production-source | Rust workspace member: shared contracts and types. |
| `packages/core/src/assets/semantic_binding.rs` | production-source | X10-054/X10-056 semantic event playback binding contract, including deterministic runtime fallback metadata, fallback catalog schema, visible fallback kinds, and stable fallback seed generation. |
| `packages/runtime-core` | production-source | Rust workspace member: runtime library and binary. |
| `packages/runtime-core/src/runtime_orchestrator.rs` | production-source | Authoritative runtime tick/playback command path, including the X10-056 regression that proves missing semantic playback bindings emit deterministic fallback command metadata. |
| `packages/runtime-core/src/snapshot_engine/delta_timeline_retention.rs` | production-source | X10-047 delta-compressed authoritative timeline retention store for debugger scrubbing, sparse `WorldSnapshot` anchors, per-tick snapshot deltas, bounded memory pruning, and retained-tick restore proofs. |
| `packages/builder-workspace/src/preview/causality_graph.ts` | production-source | X10-049 source-free causality graph evaluator and reporter for prompt, mutation, system, event, RNG call, feedback, network packet, and state-change DAG traces. |
| `packages/builder-workspace/src/preview/rng_seed_trace.ts` | production-source | X10-050 source-free RNG seed trace evaluator and reporter for deterministic RNG calls by tick, system, seed, stream position, result, illegal-RNG block evidence, and legal replay identity evidence. |
| `packages/builder-workspace/src/preview/conditional_breakpoints.ts` | production-source | X10-048 source-free conditional breakpoint evaluator for entity state, component value, event type, mutation type, system ID, RNG call, hash mismatch, and network desync candidates. |
| `packages/system-graph-compiler` | production-source | Rust workspace member: SGC compiler and CLI. |
| `packages/engine-adapter` | production-source | Rust workspace member: shared adapter protocol/delta sync. |
| `packages/engine-feedback` | production-source | Rust workspace member: engine feedback handling. |
| `packages/network-core` | production-source | Rust workspace member: network primitives, including the X10-042 diagnostics snapshot capture path and X10-043 chaos proof simulator. |
| `packages/observability` | production-source | Rust workspace member: metrics, traces, crash, and health support. |
| `packages/save-engine` | production-source | Rust workspace member plus Python save/migration modules. |
| `packages/builder-workspace` | production-source | npm workspace member and Builder server/UI source, including the X10-045 protocol-driven tick debugger panel and X10-054 semantic binding authoring path. |
| `packages/builder-workspace/src/panels/semantic_binding_catalog.ts`, `packages/builder-workspace/src/panels/semantic_binding_panel.ts`, `packages/builder-workspace/src/panels/semantic_binding_status.ts` | production-source | X10-054/X10-055/X10-060 creator-facing semantic event, animation/audio/VFX asset compatibility, Godot/Unity/Unreal target authoring UI, and pre-runtime/handoff per-engine status surfacing for resolved, unresolved, unsupported, missing, and fallback bindings. |
| `packages/schema-factory`, `packages/gde`, `packages/prompt-intelligence`, `packages/asset-registry`, `packages/dcl`, `packages/inference`, `packages/project-system` | production-source | uv workspace members; `packages/project-system/engine_project_inventory.py` is the X10-057 read-only Godot/Unity/Unreal import marker scanner and reference-only inventory contract, `packages/project-system/engine_migration_wizard.py` is the X10-058 preview-only manual migration planning/rollback contract, and `packages/project-system/adapter_installation.py` is the X10-059 reversible adapter transaction/ownership-manifest contract. |
| `packages/project-system/adapter_package_handoff_preflight.py` | production-source | X10-061 adapter package handoff preflight gate requiring target engine, CGS, persisted SGC plan, runtime compatibility proof, adapter protocol/version markers, asset refs, semantic bindings, and secret scan to pass before package handoff. |
| `packages/project-system/adapter_package_versioning.py` | production-source | X10-062 adapter package manifest builder/verifier for version, compatibility matrix, dependency declarations, install/uninstall/rollback lifecycle scripts, rollback support, and SHA-256 checksums. |
| `packages/asset-registry/asset_reference_preflight.py` | production-source | X10-053/X10-060 strict runtime/save/adapter-package handoff validator for asset refs, hashes, types, statuses, local files, documented fallbacks, semantic binding asset compatibility, and target-engine support. |
| `packages/asset-registry/semantic_binding_status.py` | production-source | X10-055/X10-060 per-engine semantic binding readiness report generator and adapter report payload source for resolved, unresolved, unsupported, missing, and fallback status before runtime/handoff launch. |
| `packages/__pycache__` | generated | Python bytecode cache output. |
| `packages/asset-runtime` | production-source | Rust workspace member: runtime asset streaming, CDN loading, and hot reload. |
| `packages/cli` | production-source | Rust workspace member: developer-facing `xace` CLI. |
| `packages/workspace` | archived | Legacy workspace server; canonical Builder is `packages/builder-workspace`. |
| `packages/builder-server`, `packages/**/dist`, `packages/**/node_modules` | generated | Build/dependency output. |
| `packages/**/tests`, `packages/**/src/tests` | test-only | Package-level and module-level tests. |

Task 8 decision: previously uncovered production packages joined their relevant
root workspace manifests. `tools/workspace_membership_check.py` now enforces
that production Rust, Python, and npm packages are covered by exactly one
workspace.

## Engine Adapters

| Path | Status | Notes |
| --- | --- | --- |
| `adapters/godot` | production-source | Godot adapter source, template scene, and X10-062 package lifecycle wrapper script. |
| `adapters/unity` | production-source | Unity adapter source, editor helpers, and X10-062 package lifecycle wrapper script. |
| `adapters/unreal` | production-source | Unreal adapter source, commandlet helpers, and X10-062 package lifecycle wrapper script. |

Installed Godot, Unity, and Unreal editors are external dependencies, not repo
source. Installed-editor proof artifacts are generated output.

## Tools

| Path | Status | Notes |
| --- | --- | --- |
| `tools/certify_launch.py` | production-source | Launch certification orchestrator. |
| `tools/xace_builder_launch.py`, `tools/xace_godot_dev.py`, `tools/cgs_maker.py` | production-source | Local launch/project helpers. |
| `tools/cgs_schema_validate.py`, `tools/commercial_scope_check.py`, `tools/fake_skip_register_check.py`, `tools/fixed_point_authority_check.py`, `tools/forbidden_claims_check.py`, `tools/production_path_check.py`, `tools/inference_adapter_boundary_check.py`, `tools/hosted_provider_proof_gate.py`, `tools/support_diagnostics_bundle.py`, `tools/export_debug_report.py`, `tools/mutation_conflict_analysis_check.py`, `tools/mutation_gate_apply_path_check.py`, `tools/phase1_readiness_score.py`, `tools/provider_route_evidence_check.py`, `tools/provider_timeout_retry_check.py`, `tools/provider_token_cost_accounting_check.py`, `tools/provider_structured_output_check.py`, `tools/prompt_capability_matrix_check.py`, `tools/prompt_classifier_gate_check.py`, `tools/prompt_clarification_loop_check.py`, `tools/prompt_diff_approval_check.py`, `tools/prompt_apply_recovery_check.py`, `tools/prompt_apply_validation_feedback_check.py`, `tools/prompt_corpus_check.py`, `tools/prompt_unknown_cgs_path_check.py`, `tools/prompt_launch_threshold_check.py`, `tools/prompt_security_check.py`, `tools/python_test_gate.py`, `tools/security_secret_scan.py`, `tools/silent_success_check.py`, `tools/source_inventory_check.py`, `tools/workspace_membership_check.py` | production-source | Governance, schema, claims, fixed-point authority, inference-adapter boundary, hosted provider proof gate, X10-051 support diagnostics bundle export, X10-052 self-contained debug report export, static mutation conflict analysis, MutationGate apply-path enforcement, Phase 1 readiness scoring, provider route-evidence gate, provider timeout/retry telemetry, provider token/cost accounting, provider structured-output constraints, prompt capability/classifier/clarification-loop/diff-approval/atomic-recovery/validation-feedback/corpus/unknown-CGS-path/threshold/security, Python gate plus focused prompt-suite artifacts, no-silent-success, inventory/register/rules, and workspace membership validators. |
| `tools/prompt_corpus_benchmark.py`, `tools/launch_provider_runtime_benchmark.py`, `tools/deterministic_simple_edit_benchmark.py` | test-only | Task 47 local prompt corpus benchmark helper, X10-028 launch provider/runtime prompt benchmark with real adapter accounting plus SGC/runtime/rollback proof, and Task 58 deterministic simple-edit benchmark proving certified value edits make zero provider, PIL, or LLM calls. |
| `tools/asset_playback_smoke.py`, `tools/builder_onboarding_smoke.py`, `tools/generated_system_safe_compile_smoke.py`, `tools/prompt_pipeline_smoke.py`, `tools/provider_readiness_smoke.py`, `tools/runtime_bridge_smoke.py`, `tools/runtime_sgc_plan_loader_smoke.py`, `tools/runtime_sgc_schedule_snapshot_smoke.py`, `tools/sgc_cli_smoke.py`, `tools/three_engine_runtime_smoke.py` | test-only | Smoke/proof helpers, including the Task 54 provider health/stale-policy proof helper; not product behavior by themselves. |
| `tools/asset_reference_validation_check.py`, `tools/cgs_end_to_end_proof.py`, `tools/composite_prompt_planning_e2e_check.py`, `tools/determinism_proof.py`, `tools/engine_side_effect_rollback_check.py`, `tools/gameplay_primitive_library_check.py`, `tools/generated_system_prompt_e2e_check.py`, `tools/import_marker_inventory_check.py`, `tools/manual_migration_wizard_check.py`, `tools/adapter_reversibility_check.py`, `tools/adapter_package_handoff_wording_check.py`, `tools/malicious_input_limits_check.py`, `tools/multiplayer_diagnostics_check.py`, `tools/multiplayer_topology_check.py`, `tools/multi_user_soak_check.py`, `tools/mutation_atomicity_proof.py`, `tools/network_chaos_proof.py`, `tools/phase15_integration_check.py`, `tools/prompt_long_session_degradation_check.py`, `tools/prompt_undo_redo_e2e_check.py`, `tools/replay_cross_platform_proof.py`, `tools/runtime_input_sync_check.py`, `tools/runtime_rollback_resimulation_check.py`, `tools/runtime_prediction_reconciliation_check.py`, `tools/semantic_binding_ui_check.py`, `tools/semantic_binding_status_check.py`, `tools/runtime_fallback_binding_check.py`, `tools/session_lifecycle_check.py`, `tools/session_compatibility_check.py`, `tools/sgc_cli_integration.py`, `tools/sgc_runtime_proof.py`, `tools/tick_debugger_minimum_check.py`, `tools/tick_debugger_time_travel_check.py`, `tools/tick_debugger_delta_retention_check.py`, `tools/tick_debugger_breakpoint_check.py`, `tools/tick_debugger_causality_graph_check.py`, `tools/tick_debugger_rng_seed_trace_check.py`, `tools/support_diagnostics_bundle_check.py`, `tools/export_debug_report_check.py`, `tools/typed_cgs_operation_e2e_check.py` | test-only | Proof/integration/benchmark helpers, including the X10-014 cross-platform replay proof recorder, X10-023 engine side-effect rollback proof helper, X10-029 per-primitive real-SGC/persisted-runtime replay gate, X10-030 typed-operation atomic apply/runtime/rollback gate, X10-031 prompt-generated-system materialization/SGC/runtime/adversarial/rollback gate, X10-032 composite prompt planning/preview/apply/rollback gate, X10-033 proof-linked 50-step prompt undo/redo history gate, X10-034 fixed-length long-session degradation gate, X10-035 host/client launch topology gate, X10-036 runtime InputSynchroniser tick gate, X10-037 retained-snapshot rollback/resimulation gate, X10-038 lockstep-client prediction/reconciliation gate, X10-039 host/client session lifecycle gate, X10-040 session compatibility mismatch gate, X10-041 malicious-input limit gate, X10-042 multiplayer diagnostics panel gate, X10-043 network chaos proof harness, X10-044 accelerated multi-user soak harness, X10-045 minimum tick-debugger source-free divergence inspection gate, X10-046 1,000-tick debugger time-travel navigation gate, X10-047 delta-compressed timeline retention memory/restore gate, X10-048 conditional breakpoint exact-hit gate, X10-049 combat-damage causality graph gate, X10-050 RNG seed trace gate, X10-051 support diagnostics bundle gate, X10-052 exportable debug report round-trip gate, X10-053 strict asset-reference validation gate, X10-054 semantic binding UI/runtime/adapter contract gate, X10-055 semantic binding status/adapter-report gate, X10-056 deterministic runtime fallback binding/adapter-artifact gate, X10-057 read-only import marker inventory/refusal gate, X10-058 preview-only manual migration wizard gate, X10-059 reversible adapter install/update/rollback/uninstall gate, and X10-060 adapter package handoff wording gate. |
| `tools/adapter_package_handoff_preflight_check.py` | test-only | X10-061 retained blocked handoff matrix proving target engine, CGS, persisted SGC plan, runtime compatibility, adapter version, assets, semantic bindings, and secrets must pass before adapter package handoff copies any files. |
| `tools/adapter_package_version_check.py` | test-only | X10-062 retained package verification gate for Godot/Unity/Unreal adapter package version manifests, compatibility matrices, dependencies, lifecycle scripts, rollback declarations, checksums, tamper rejection, and Builder handoff manifest output. |
| `tools/godot_vertical_slice_certification.py` | test-only | X10-064 retained installed-Godot vertical-slice certification gate that stages the canonical slice, loads current Godot adapter scripts in installed Godot, and emits validation JSON, PNG, log, and hash evidence. |
| `tools/unity_vertical_slice_certification.py` | test-only | X10-065 retained installed-Unity vertical-slice certification gate that stages the canonical slice, compiles/constructs current Unity adapter components in installed Unity, and emits validation JSON, PNG, log, and hash evidence. |

## Docs

| Path | Status | Notes |
| --- | --- | --- |
| `docs/XACE_COMMERCIAL_SCOPE.md` | production-source | Frozen commercial scope record. |
| `docs/XACE_BASELINE_FAILURE_LIST.md` | production-source | Task 5 baseline failure, skipped-gate, and missing-artifact report. |
| `docs/XACE_FAKE_AND_SKIP_REGISTER.md`, `docs/fake_skip_register.json` | production-source | Task 3 fake/mock/stub/skip/smoke register artifacts. |
| `docs/XACE_PRODUCT_CLAIMS_MATRIX.md` | production-source | Claims governance. |
| `docs/XACE_PRODUCTION_PATH_RULES.md`, `docs/production_path_rules.json` | production-source | Task 4 production/test/demo/fake boundary rules. |
| `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md` | production-source | Readiness plan and historical audit. |
| `docs/STATE_AUTHORITY_RULES.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/CGS_SCHEMA_EXPORT_FORMAT.md`, `docs/CRASH_SAFE_PROJECT_RECOVERY.md`, `docs/FIXED_POINT_NUMERIC_MODEL.md`, `docs/SIDE_CHANNEL_HASH_POLICY.md`, `docs/SNAPSHOT_COMPLETENESS_POLICY.md`, `docs/SNAPSHOT_SERIALIZATION_CONTRACT.md`, `docs/REPLAY_CROSS_PLATFORM_PROOF.md`, `docs/REPLAY_DIVERGENCE_DIAGNOSIS.md`, `docs/INFERENCE_ADAPTER_BOUNDARY.md`, `docs/HOSTED_PROVIDER_PROOF_GATE.md`, `docs/PROVIDER_ROUTE_EVIDENCE_POLICY.md`, `docs/PROVIDER_TIMEOUT_RETRY_POLICY.md`, `docs/PROVIDER_TOKEN_COST_ACCOUNTING.md`, `docs/PROVIDER_HEALTH_STALE_POLICY.md`, `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/PROMPT_CORPUS.md`, `docs/PROMPT_LAUNCH_THRESHOLDS.md`, `docs/PROMPT_SECURITY_TESTS.md`, `docs/TYPED_CGS_OPERATIONS.md` | production-source | Technical contracts, crash-safe project recovery, fixed-point numeric model, side-channel hash policy, snapshot completeness/serialization policies, cross-platform replay proof, replay divergence diagnosis, inference adapter boundary, hosted provider proof gate, provider route-evidence policy, provider timeout/retry telemetry policy, provider token/cost accounting contract, provider health/stale-policy contract, prompt capability matrix, reviewed prompt corpus contract, prompt launch threshold/security contracts, and the closed X10-030/X10-031/X10-032/X10-033 typed-CGS prompt mutation, generated-system trust-boundary, composite planning, and prompt-history undo/redo contracts. |
| `docs/LAUNCH_READINESS_MAP.md`, `docs/GODOT_QUICKSTART.md` | production-source | Working map and adapter guidance. |
| `docs/schemas/*.json`, `docs/multiplayer_launch_topology_matrix.json`, `docs/prompt_capability_matrix.json`, `docs/prompt_corpus_100.jsonl`, `docs/prompt_corpus_manifest.json`, `docs/prompt_launch_thresholds.json`, `docs/prompt_security_cases.jsonl` | production-source | JSON schema contracts, the X10-035 multiplayer launch topology matrix, the canonical prompt capability matrix, the Task 46 reviewed prompt corpus artifacts, Task 48/X10-028 threshold profiles, and Task 50 prompt security cases. |
| `docs/XACE_SOURCE_OF_TRUTH_INVENTORY.md`, `docs/source_inventory.json` | production-source | Task 2 inventory artifacts. |
| `docs/00_philosophy.md`, `docs/01_system_overview.md`, `docs/02_canonical_data_models.md`, `docs/03_module_specs.md`, `docs/04_contracts.md`, `docs/07_global_invariants.md`, `docs/08_failure_classification.md`, `docs/09_state_machines.md`, `docs/10_versioning_and_build_order.md` | archived | Stub docs until completed or formally archived by a later task. |
| `docs/WORKSPACE_BUILDER_ARCHIVE.md`, `docs/XACE_Systemdesign.pdf` | archived | Archive/reference material. |

## Tests, Examples, And Projects

| Path | Status | Notes |
| --- | --- | --- |
| `tests` | test-only | Top-level tests and fixtures. |
| `tests/determinism` | test-only | Determinism-focused test suite. |
| `tests/fixtures` | test-only | Test fixtures and fixture docs. |
| `tests/integration` | test-only | Top-level integration tests. |
| `tests/unit` | test-only | Top-level unit tests. |
| `examples/zombie-chase` | production-source | Workspace example/reference vertical slice. |
| `projects/canonical_cross_engine_vertical_slice` | production-source | X10-063 versioned canonical CGS-owned cross-engine vertical slice fixture covering movement, combat, health, inventory, save/load, rollback, replay, semantic bindings, animation, audio, VFX fallback, and network-ready input for Godot/Unity/Unreal certification. |
| `projects/zombie_chase` | production-source | CGS project fixture used by local demos/proofs. |

## External Dependencies

- `C:/Users/ankit/firstgame`: user project referenced by local proofs.
- Godot, Unity, and Unreal installed editors: external engine dependencies.
- Hosted AI providers and local provider daemons: external services.
- OS credential stores: Windows Credential Manager, macOS Keychain, Linux Secret Service/libsecret.

## Generated Artifact Patterns

- `target*`
- `node_modules/**`
- `output/**`
- `tmp/**`
- `.xace/proof/**`
- `.VSCodeCounter/**`
- `packages/builder-server/**`
- `packages/**/dist/**`
- `packages/**/node_modules/**`
- `packages/**/__pycache__/**`

Generated artifacts may be retained for local evidence, but they are not source
of truth unless a later task promotes a specific fixture into a versioned test
path.
