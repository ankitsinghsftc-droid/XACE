# XACE Source Of Truth Inventory

Inventory date: 2026-07-24

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
| `target*`, `node_modules` | generated | Build/proof output and root dependency install output. |
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
| `packages/runtime-core` | production-source | Rust workspace member: runtime library and binary. |
| `packages/system-graph-compiler` | production-source | Rust workspace member: SGC compiler and CLI. |
| `packages/engine-adapter` | production-source | Rust workspace member: shared adapter protocol/delta sync. |
| `packages/engine-feedback` | production-source | Rust workspace member: engine feedback handling. |
| `packages/network-core` | production-source | Rust workspace member: network primitives. |
| `packages/observability` | production-source | Rust workspace member: metrics, traces, crash, and health support. |
| `packages/save-engine` | production-source | Rust workspace member plus Python save/migration modules. |
| `packages/builder-workspace` | production-source | npm workspace member and Builder server/UI source. |
| `packages/schema-factory`, `packages/gde`, `packages/prompt-intelligence`, `packages/asset-registry`, `packages/dcl`, `packages/inference`, `packages/project-system` | production-source | uv workspace members. |
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
| `adapters/godot` | production-source | Godot adapter source and template scene. |
| `adapters/unity` | production-source | Unity adapter source and editor helpers. |
| `adapters/unreal` | production-source | Unreal adapter source and commandlet helpers. |

Installed Godot, Unity, and Unreal editors are external dependencies, not repo
source. Installed-editor proof artifacts are generated output.

## Tools

| Path | Status | Notes |
| --- | --- | --- |
| `tools/certify_launch.py` | production-source | Launch certification orchestrator. |
| `tools/xace_builder_launch.py`, `tools/xace_godot_dev.py`, `tools/cgs_maker.py` | production-source | Local launch/project helpers. |
| `tools/cgs_schema_validate.py`, `tools/commercial_scope_check.py`, `tools/fake_skip_register_check.py`, `tools/fixed_point_authority_check.py`, `tools/forbidden_claims_check.py`, `tools/production_path_check.py`, `tools/inference_adapter_boundary_check.py`, `tools/hosted_provider_proof_gate.py`, `tools/mutation_conflict_analysis_check.py`, `tools/mutation_gate_apply_path_check.py`, `tools/phase1_readiness_score.py`, `tools/provider_route_evidence_check.py`, `tools/provider_timeout_retry_check.py`, `tools/provider_token_cost_accounting_check.py`, `tools/prompt_capability_matrix_check.py`, `tools/prompt_classifier_gate_check.py`, `tools/prompt_clarification_loop_check.py`, `tools/prompt_diff_approval_check.py`, `tools/prompt_apply_recovery_check.py`, `tools/prompt_apply_validation_feedback_check.py`, `tools/prompt_corpus_check.py`, `tools/prompt_launch_threshold_check.py`, `tools/prompt_security_check.py`, `tools/python_test_gate.py`, `tools/security_secret_scan.py`, `tools/silent_success_check.py`, `tools/source_inventory_check.py`, `tools/workspace_membership_check.py` | production-source | Governance, schema, claims, fixed-point authority, inference-adapter boundary, hosted provider proof gate, static mutation conflict analysis, MutationGate apply-path enforcement, Phase 1 readiness scoring, provider route-evidence gate, provider timeout/retry telemetry, provider token/cost accounting, prompt capability/classifier/clarification-loop/diff-approval/atomic-recovery/validation-feedback/corpus/threshold/security, Python gate, no-silent-success, inventory/register/rules, and workspace membership validators. |
| `tools/prompt_corpus_benchmark.py`, `tools/deterministic_simple_edit_benchmark.py` | test-only | Task 47 local prompt corpus benchmark helper plus Task 58 deterministic simple-edit benchmark proving certified value edits make zero provider, PIL, or LLM calls. |
| `tools/asset_playback_smoke.py`, `tools/builder_onboarding_smoke.py`, `tools/generated_system_safe_compile_smoke.py`, `tools/prompt_pipeline_smoke.py`, `tools/provider_readiness_smoke.py`, `tools/runtime_bridge_smoke.py`, `tools/runtime_sgc_plan_loader_smoke.py`, `tools/runtime_sgc_schedule_snapshot_smoke.py`, `tools/sgc_cli_smoke.py`, `tools/three_engine_runtime_smoke.py` | test-only | Smoke/proof helpers, including the Task 54 provider health/stale-policy proof helper; not product behavior by themselves. |
| `tools/cgs_end_to_end_proof.py`, `tools/determinism_proof.py`, `tools/mutation_atomicity_proof.py`, `tools/phase15_integration_check.py`, `tools/replay_cross_platform_proof.py`, `tools/sgc_cli_integration.py`, `tools/sgc_runtime_proof.py` | test-only | Proof/integration/benchmark helpers, including the X10-014 cross-platform replay proof recorder and aggregator. |

## Docs

| Path | Status | Notes |
| --- | --- | --- |
| `docs/XACE_COMMERCIAL_SCOPE.md` | production-source | Frozen commercial scope record. |
| `docs/XACE_BASELINE_FAILURE_LIST.md` | production-source | Task 5 baseline failure, skipped-gate, and missing-artifact report. |
| `docs/XACE_FAKE_AND_SKIP_REGISTER.md`, `docs/fake_skip_register.json` | production-source | Task 3 fake/mock/stub/skip/smoke register artifacts. |
| `docs/XACE_PRODUCT_CLAIMS_MATRIX.md` | production-source | Claims governance. |
| `docs/XACE_PRODUCTION_PATH_RULES.md`, `docs/production_path_rules.json` | production-source | Task 4 production/test/demo/fake boundary rules. |
| `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md` | production-source | Readiness plan and historical audit. |
| `docs/STATE_AUTHORITY_RULES.md`, `docs/SGC_CLI_CONTRACT.md`, `docs/SGC_EXECUTION_PLAN_CONTRACT.md`, `docs/CGS_SCHEMA_EXPORT_FORMAT.md`, `docs/CRASH_SAFE_PROJECT_RECOVERY.md`, `docs/FIXED_POINT_NUMERIC_MODEL.md`, `docs/SIDE_CHANNEL_HASH_POLICY.md`, `docs/SNAPSHOT_COMPLETENESS_POLICY.md`, `docs/SNAPSHOT_SERIALIZATION_CONTRACT.md`, `docs/REPLAY_CROSS_PLATFORM_PROOF.md`, `docs/REPLAY_DIVERGENCE_DIAGNOSIS.md`, `docs/INFERENCE_ADAPTER_BOUNDARY.md`, `docs/HOSTED_PROVIDER_PROOF_GATE.md`, `docs/PROVIDER_ROUTE_EVIDENCE_POLICY.md`, `docs/PROVIDER_TIMEOUT_RETRY_POLICY.md`, `docs/PROVIDER_TOKEN_COST_ACCOUNTING.md`, `docs/PROVIDER_HEALTH_STALE_POLICY.md`, `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/PROMPT_CORPUS.md`, `docs/PROMPT_LAUNCH_THRESHOLDS.md`, `docs/PROMPT_SECURITY_TESTS.md` | production-source | Technical contracts, crash-safe project recovery, fixed-point numeric model, side-channel hash policy, snapshot completeness/serialization policies, cross-platform replay proof, replay divergence diagnosis, inference adapter boundary, hosted provider proof gate, provider route-evidence policy, provider timeout/retry telemetry policy, provider token/cost accounting contract, provider health/stale-policy contract, prompt capability matrix, reviewed prompt corpus contract, prompt launch threshold contract, and prompt security test contract. |
| `docs/LAUNCH_READINESS_MAP.md`, `docs/GODOT_QUICKSTART.md` | production-source | Working map and adapter guidance. |
| `docs/schemas/*.json`, `docs/prompt_capability_matrix.json`, `docs/prompt_corpus_100.jsonl`, `docs/prompt_corpus_manifest.json`, `docs/prompt_launch_thresholds.json`, `docs/prompt_security_cases.jsonl` | production-source | JSON schema contracts, the canonical prompt capability matrix, the Task 46 reviewed prompt corpus artifacts, Task 48 threshold profiles, and Task 50 prompt security cases. |
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
| `projects/zombie_chase` | production-source | CGS project fixture used by local demos/proofs. |

## External Dependencies

- `C:/Users/ankit/firstgame`: user project referenced by local proofs.
- Godot, Unity, and Unreal installed editors: external engine dependencies.
- Hosted AI providers and local provider daemons: external services.
- OS credential stores: Windows Credential Manager, macOS Keychain, Linux Secret Service/libsecret.

## Generated Artifact Patterns

- `target*`
- `node_modules/**`
- `.xace/proof/**`
- `.VSCodeCounter/**`
- `packages/builder-server/**`
- `packages/**/dist/**`
- `packages/**/node_modules/**`
- `packages/**/__pycache__/**`

Generated artifacts may be retained for local evidence, but they are not source
of truth unless a later task promotes a specific fixture into a versioned test
path.
