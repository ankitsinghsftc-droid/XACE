# XACE 10/10 Completion Tasklist

Source inputs:
- `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md`
- Brutal technical audit of the nine core XACE architecture areas
- Existing assumption: master tasks 1-58 are complete and should not be reopened unless a later proof gate disproves them

Purpose:
This is the final working backlog for taking XACE from "promising but partially integrated" to "10/10 complete" across the audited core architecture and commercial-readiness surface.

10/10 means:
- Every production claim is backed by reproducible proof artifacts.
- No production path silently uses mocks, fakes, skipped checks, naive mutation fallback, hashless plans, reset-based hot reload, or unsupported generated systems.
- CGS, SGC, runtime, prompt, rollback, multiplayer, debugger, adapters, save/load, CI, and release gates work as one end-to-end system.
- The readiness scoring tool reports 9/10 or 10/10 in every major area, and an independent audit can reproduce the result from a clean checkout.

## Completion Gates

Do not call XACE complete until all gates pass.

- [ ] `cargo test --workspace` passes on Windows, Linux, and macOS.
- [ ] Python production tests run through one documented command and pass without ad hoc `PYTHONPATH` surgery.
- [ ] Builder TypeScript/server tests, build, typecheck, and lint pass in CI.
- [ ] Cross-platform replay proof produces identical runtime-authoritative hashes on Windows, Linux, and macOS.
- [ ] Prompt launch profile runs provider, compile, runtime, rollback, and reproducibility dimensions, not only local classifier checks.
- [ ] Installed-engine proof exists for Godot, Unity, and Unreal for the same canonical vertical slice.
- [ ] Multiplayer chaos proof passes for the chosen supported topology.
- [ ] 8-hour product soak passes with prompt edits, SGC, runtime, adapters, save/load, rollback, and recovery.
- [ ] Fuzz, security, secret-scan, supply-chain, and proof-artifact gates pass.
- [ ] Public claims audit maps every user-facing claim to a proof artifact.
- [ ] Signed release candidate installs on a fresh machine without repository knowledge.

## Phase 1 - Authoritative CGS, SGC, And Runtime Contract

Status: complete locally as of 2026-07-23. Phase 1 remains subject to the
global completion gates at the top of this document.

Closes audit areas: CGS/IR, SGC/dependency checks, engine-agnostic execution.

Master task sources: 21-34, 59-62, 138-140.

- [x] X10-001: Make the persisted SGC execution plan the only production runtime authority.
  - Acceptance: runtime refuses to tick when required plan file is missing, hashless, stale, schema-incompatible, or adapter-protocol-incompatible.
  - Evidence: runtime load tests, plan schema validation, failure proof artifacts.
  - Done 2026-07-23: `RuntimeConfig::default()` and `load_and_spawn()` now require a persisted SGC plan by default. Missing plans fail before tick zero, and the runtime-core suite passes with explicit dev-only derived-plan fixtures.
  - Verification: `cargo test -p xace-runtime-core -q`.

- [x] X10-002: Remove hashless derived-plan fallback from production mode.
  - Acceptance: CGS-derived plans are test-only or explicitly dev-only; production requires `.xace/execution_plans/*.plan.json`.
  - Evidence: import scan proving production paths cannot silently derive schedules.
  - Done 2026-07-23: `SgcPlanPolicy::PreferPersisted` no longer silently derives when the plan file is absent; `SgcPlanPolicy::DeriveFromCgs` is the only explicit derived-plan path and the CLI labels it development/test-only.
  - Verification: focused missing-plan regression tests plus `cargo test -p xace-runtime-core -q`.

- [x] X10-003: Fix SGC plan identity ownership.
  - Acceptance: SGC or the plan writer always emits `compiled_from_cgs_hash`, plan hash, schema version, plan version, adapter protocol, component access sets, system metadata, proof bundle, and migration status.
  - Evidence: byte-for-byte reproducibility test for unchanged CGS input.
  - Done 2026-07-23: SGC CLI now emits complete identity/provenance fields through `compile_and_verify_with_identity`; malformed or missing CGS hashes are rejected instead of stamped as placeholders. Builder persistence preserves SGC-owned identity blocks when present and only enriches legacy incomplete plans.
  - Verification: `cargo test -p xace-core -q`; `cargo test -p xace-system-graph-compiler -q`; `cargo test -p xace-runtime-core -q`; `python tools/sgc_cli_smoke.py --sgc-bin target/debug/xace-system-graph-compiler.exe`; `python tools/sgc_cli_integration.py --sgc-bin target/debug/xace-system-graph-compiler.exe --benchmark-repeats 1 --json`; `python tools/sgc_runtime_proof.py --runtime-bin target/debug/xace_runtime.exe --sgc-bin target/debug/xace-system-graph-compiler.exe --ticks 2 --json`.
  - Proof artifact: `.xace/proof/sgc-runtime/20260723T064837Z/summary.json`.

- [x] X10-004: Enforce complete CGS schema validation before SGC and runtime load.
  - Acceptance: CGS validation covers component schemas, system read/write overlap, dependencies, actor defaults, modes, rules, assets, network/save metadata, and version contracts.
  - Evidence: invalid CGS corpus blocked with exact diagnostics.
  - Done 2026-07-23: runtime CGS loading and Builder SGC-plan persistence now run strict whole-file CGS validation before component registration, entity spawn, SGC input reconstruction, or proof/plan writes. The gate validates metadata/version/hash contracts, default modes, actor/component defaults, rules, system access/dependencies/cycles, and shallow assets/network/save metadata; invalid corpora emit accumulated exact diagnostics.
  - Verification: `cargo test -p xace-runtime-core -q`; `python -m unittest packages.builder-workspace.server.tests.test_cgs_persistence_authority packages.builder-workspace.server.tests.test_sgc_execution_plan_contract`; `python tools/cgs_schema_validate.py game.cgs.json --json`.

- [x] X10-005: Replace `register_all_component_tables` no-op with authoritative component-table registration.
  - Acceptance: runtime registers every CGS component table from schema metadata and rejects unknown or duplicate type IDs before tick zero.
  - Evidence: tests for built-in, generated, plugin, and invalid component registrations.
  - Done 2026-07-23: `register_all_component_tables` now derives authoritative registrations from the full validated CGS root, including built-ins, top-level `component_schemas`, actor components across all modes, and system access sets. Runtime registration happens after schema validation and before entity spawn; duplicate schema type IDs, undeclared access IDs, conflicting names, and pre-registered table stores are rejected before tick zero.
  - Verification: `cargo test -p xace-runtime-core -q`; `python -m unittest packages.builder-workspace.server.tests.test_cgs_persistence_authority packages.builder-workspace.server.tests.test_sgc_execution_plan_contract`; `python tools/cgs_schema_validate.py game.cgs.json --json`.

- [x] X10-006: Expand runtime system registry beyond narrow generated ABI.
  - Acceptance: runtime can execute built-in, generated, plugin, and external deterministic systems through one registry contract.
  - Evidence: at least three non-built-in generated systems run through SGC, runtime tick, replay, rollback, and adapter snapshot proof.
  - Done 2026-07-23: non-built-in systems now normalize through one `runtime_executor` registration path before entering `SystemRegistry`. The runtime accepts compatible legacy generated ABI metadata and the broader `xace.runtime_executor_abi.v1` contract, with deterministic generated, plugin, and external executor kinds executing only through `SystemContext`, `MutationGate`, deterministic schedule snapshots, and replay/restore paths.
  - Verification: `cargo test -p xace-runtime-core -q`; `cargo test -p xace-system-graph-compiler -q`; `python -m unittest packages.builder-workspace.server.tests.test_cgs_persistence_authority packages.builder-workspace.server.tests.test_sgc_execution_plan_contract`; `python tools/cgs_schema_validate.py game.cgs.json --json`.

- [x] X10-007: Require runtime ticks to validate schedule snapshot identity.
  - Acceptance: every tick records and verifies CGS hash, plan hash, plan version, phase/group order, component access, and system IDs.
  - Evidence: replay rejects any plan drift at the first bad tick.
  - Done 2026-07-23: runtime startup now seals a `RuntimeScheduleIdentity` from the loaded SGC/derived plan. Every tick builds its executable phase plan only from an identity-validated snapshot that includes schema/source, schema version, plan version/hash, CGS hash, compiled CGS hash, scheduled system IDs, phase/group order, component access, and dependencies. Replay validation compares recorded snapshots against the sealed identity and reports the first schedule mismatch before treating replay as valid.
  - Verification: `cargo test -p xace-runtime-core -q`; `cargo build -p xace-runtime-core --bin xace_runtime`; `python tools/runtime_sgc_schedule_snapshot_smoke.py --runtime-bin target/debug/xace_runtime.exe --ticks 2`.

- [x] X10-008: Build readiness score inputs for CGS, SGC, and runtime contract.
  - Acceptance: scorecard consumes proof artifacts, not docs, to grade these areas.
  - Evidence: readiness scoring tool reports pass/fail with links.
  - Done 2026-07-23: added `tools/phase1_readiness_score.py`, an artifact-backed scorecard for the Canonical CGS Contract, SGC Execution Plan Contract, and Runtime Schedule/Replay Contract. The tool validates retained JSON proof summaries, linked CGS/SGC/runtime artifacts, identity hashes, persisted-plan metadata, schedule snapshots, replay equality, and control replay proof before assigning scores; docs are not accepted as score inputs.
  - Proof artifacts: `.xace/proof/sgc-runtime/20260723T101634Z/summary.json`; `.xace/proof/cgs-e2e/20260723T101645Z/summary.json`; `target-codex-readiness/phase1_readiness_scorecard.json`.
  - Score: 100.0% overall; CGS 10.0/10, SGC 10.0/10, runtime 10.0/10.
  - Verification: `python tools/phase1_readiness_score.py --output target-codex-readiness\phase1_readiness_scorecard.json`; `python -m py_compile tools/phase1_readiness_score.py tools/sgc_runtime_proof.py tools/cgs_end_to_end_proof.py tools/certify_launch.py`; `cargo test -p xace-runtime-core -q`; `cargo test -p xace-system-graph-compiler -q`; `python -m unittest packages.builder-workspace.server.tests.test_cgs_persistence_authority packages.builder-workspace.server.tests.test_sgc_execution_plan_contract`; `python tools/source_inventory_check.py`.

## Phase 2 - Determinism, Fixed-Point Math, Snapshots, And Replay

Closes audit areas: hash-proven determinism, fixed-point math, time rollback foundation.

Master task sources: 59-66, 111-112, 117-120.

- [x] X10-009: Decide and implement authoritative fixed-point numeric model.
  - Acceptance: gameplay-authoritative simulation fields use fixed-point or integer-scaled math; `f32`/`f64` are banned from authoritative gameplay state except explicitly non-authoritative telemetry/rendering.
  - Evidence: static scan and deterministic replay proof across OS/architecture.
  - Done 2026-07-23: added `Fixed64` as the canonical authoritative numeric primitive (`i64` micro-units, transparent integer serde) and migrated core authoritative state surfaces away from raw floats: transform vectors/quaternions, velocity vectors/limits, collider sizes/offsets/materials, world size/gravity, actor stats, tick-derived game/lifetime helpers, event fixed-point parsing, and snapshot `time_seconds`.
  - Static gate: `tools/fixed_point_authority_check.py` scans 42 authoritative core files and fails on executable `f32`, `f64`, or float literals; the gate is now included in `tools/certify_launch.py`.
  - Contract doc: `docs/FIXED_POINT_NUMERIC_MODEL.md`.
  - Proof artifacts: `target-codex-fixed-point/fixed_point_authority_report.json`; `.xace/proof/sgc-runtime/20260723T104432Z/summary.json`.
  - Verification: `python tools/fixed_point_authority_check.py --output target-codex-fixed-point/fixed_point_authority_report.json`; `python -m py_compile tools/fixed_point_authority_check.py tools/certify_launch.py`; `python tools/source_inventory_check.py`; `cargo test -p xace-core -q`; `cargo test -p xace-runtime-core -q`; `cargo test -p xace-system-graph-compiler -q`; `python tools/sgc_runtime_proof.py --runtime-bin target/debug/xace_runtime.exe --sgc-bin target/debug/xace-system-graph-compiler.exe --ticks 2 --json`.
  - Follow-on: X10-010 completed the local runtime math migration; cross-platform replay remains the global completion gate and X10-014.

- [x] X10-010: Migrate built-in systems from float math to deterministic numeric primitives.
  - Acceptance: movement, AI, combat, inventory weights, timers, input values, and generated-system numeric ops use the same fixed-point contract.
  - Evidence: before/after replay hashes remain stable and cross-platform.
  - Done 2026-07-24: added shared runtime fixed-point JSON helpers (`packages/runtime-core/src/fixed_json.rs`) and migrated built-in runtime movement, AI, interaction range checks, inventory weights, damage, death, generated-system numeric operations, `ISystemContext::next_random`, live `SystemContext` RNG output, and the `examples/zombie-chase` reference systems/runner to `Fixed64` raw micro-unit state.
  - Static gate: `tools/fixed_point_authority_check.py` now scans 55 authoritative state/runtime/example files, including `runtime-core` built-ins, generated-system ABI, system context, and `examples/zombie-chase/src`; `next_task_float_debt` is empty.
  - Proof artifacts: `target-codex-fixed-point/fixed_point_authority_report.json`; `.xace/proof/sgc-runtime/20260724T031517Z/`.
  - Verification: `cargo test -p xace-core -q`; `cargo test -p xace-runtime-core -q`; `cargo test -p xace-zombie-chase -q`; `python tools/fixed_point_authority_check.py --output target-codex-fixed-point/fixed_point_authority_report.json --json`; `python tools/sgc_runtime_proof.py --runtime-bin target/debug/xace_runtime.exe --sgc-bin target/debug/xace-system-graph-compiler.exe --ticks 2 --json`.
  - Remaining proof boundary: same-machine deterministic replay is covered by existing runtime/example tests; Windows/Linux/macOS replay proof remains X10-014.

- [x] X10-011: Complete side-channel hash policy.
  - Acceptance: RNG, event queue, mutation queue, feedback queue, network input buffers, save state, adapter side effects, and asset binding state are either hash-authoritative or explicitly excluded with proof.
  - Evidence: docs plus injected divergence tests.
  - Done 2026-07-24: added executable side-channel policy coverage in `packages/runtime-core/src/determinism_guard/side_channel_hash_policy.rs`; expanded `WorldHasher` to include `cgs_hash`, RNG snapshot state, pending event queue state, pending mutation queue state, and clean-boundary status; kept feedback queues, pre-materialized network input buffers, save metadata, and adapter playback side effects explicitly excluded with replay/log/persisted-hash proofs.
  - Contract doc: `docs/SIDE_CHANNEL_HASH_POLICY.md`; determinism status updated in `docs/06_determinism_guarantees.md`.
  - Certification: `tools/certify_launch.py` now includes `runtime side-channel hash policy`.
  - Verification: `cargo test -p xace-runtime-core side_channel_hash_policy --lib`; `cargo test -p xace-runtime-core world_hasher --lib`; `cargo test -p xace-runtime-core --lib`.
  - Follow-on: X10-012 still owns full snapshot-completeness hardening; X10-013 still owns full canonical snapshot deserialization.

- [x] X10-012: Harden snapshot completeness.
  - Acceptance: snapshots include or explicitly exclude entity records, component tables, archived entities, RNG stream positions, events, mutations, feedback, network sync, save state, and adapter side effects.
  - Evidence: restore behavior matches original timeline after rollback and replay.
  - Done 2026-07-24: added executable snapshot-completeness policy coverage in `packages/runtime-core/src/snapshot_engine/snapshot_completeness_policy.rs`, enforcing included fields and explicit exclusions for transient/non-authoritative channels.
  - Restore hardening: `SnapshotEngine::restore_snapshot` and `RuntimeOrchestrator::restore_world_snapshot` now reject non-clean snapshots with pending events, pending mutations, or live RNG stream positions before restore side effects; `EntityStore::restore_from_snapshot` reconstructs archived ID reservations from archived entity records; `ComponentTableStore::restore_from_tables_snapshot` clears rows absent from the snapshot while preserving registered empty tables.
  - Contract doc: `docs/SNAPSHOT_COMPLETENESS_POLICY.md`.
  - Certification: `tools/certify_launch.py` now includes `runtime snapshot completeness`.
  - Verification: `cargo test -p xace-runtime-core x10_012 --lib`; `cargo test -p xace-runtime-core snapshot_engine --lib`; `cargo test -p xace-runtime-core runtime_orchestrator --lib`.

- [x] X10-013: Replace minimal snapshot deserialization with full canonical snapshot restore.
  - Acceptance: serialized snapshots round-trip all authoritative fields.
  - Evidence: snapshot round-trip fuzz tests.
  - Done 2026-07-24: replaced `SnapshotSerializer::deserialize` minimal fallback with full `serde_json::from_str::<WorldSnapshot>` parsing plus validation; `SnapshotSerializer::serialize` now writes the full authoritative `WorldSnapshot` schema instead of the old partial `entity_store`/`component_tables` projection.
  - Contract doc: `docs/SNAPSHOT_SERIALIZATION_CONTRACT.md`.
  - Certification: `tools/certify_launch.py` now includes `runtime snapshot serialization`.
  - Verification: `cargo test -p xace-runtime-core snapshot_serializer --lib`.
  - Round-trip proof: X10-013 tests preserve tick, fixed-point time, schema/plan versions, `cgs_hash`, entity records, component tables, archived records, RNG state, event queue state, mutation queue state, `world_hash`, and `is_clean`, including a deterministic 32-case fuzz loop and a legacy-minimal rejection test.

- [x] X10-014: Add cross-platform replay proof.
  - Acceptance: same CGS, SGC plan, generated systems, input log, and seed produce identical hashes on Windows, Linux, and macOS.
  - Evidence: `.xace/proof/replay-cross-platform/<run-id>/`.
  - Done 2026-07-24: added `tools/replay_cross_platform_proof.py`, which records a real per-platform CGS -> SGC -> runtime replay proof and aggregates Windows/Linux/macOS `platform_report.json` files into a single pass/fail `summary.json`.
  - Runtime binding: `xace_runtime` now accepts `--world-seed`, includes `world_seed` in schedule snapshot reports, and `tools/sgc_runtime_proof.py` records the pinned seed, canonical empty input-log hash, per-tick hash log, generated systems, scheduled systems, and schedule fingerprint.
  - CI: `.github/workflows/xace-scope.yml` now runs the replay recorder on Windows, Linux, and macOS, downloads all platform artifacts, and fails the aggregate job unless canonical replay identity matches across all three OSes.
  - Contract doc: `docs/REPLAY_CROSS_PLATFORM_PROOF.md`.
  - Certification: `tools/certify_launch.py` now compiles the proof tool and records the local OS replay leg in quick/full certification.
  - Verification: `python -m py_compile tools/replay_cross_platform_proof.py tools/sgc_runtime_proof.py tools/cgs_end_to_end_proof.py`; `python tools/replay_cross_platform_proof.py self-test --target-dir target-codex-replay-cross-platform-self-test --json`.
  - Final global completion boundary: this repository can now produce the required three-platform artifact, but the top-level completion gate is not closed until the Windows/Linux/macOS CI aggregate artifact is retained for a real run.

- [x] X10-015: Add replay divergence diagnosis.
  - Acceptance: first divergent tick report identifies system, component, event, RNG call, mutation, input packet, and SGC group when possible.
  - Evidence: injected divergence tests with readable reports.
  - Done 2026-07-24: `RuntimeOrchestrator` now records per-tick replay traces and attaches `RuntimeReplayDivergenceDiagnosis` to the first hash mismatch from `validate_recorded_replay_from_cgs`.
  - Runtime binding: diagnosis includes suspected SGC group, candidate systems, component changes, emitted events, RNG access records, mutation counts, input packet traces, expected trace, actual trace, and a human-readable summary.
  - RNG binding: `RngInterceptor::accesses_for_tick` exposes deterministic RNG audit records in stable system order for divergent ticks.
  - Contract doc: `docs/REPLAY_DIVERGENCE_DIAGNOSIS.md`.
  - Certification: `tools/certify_launch.py` now runs `cargo test -p xace-runtime-core x10_015 --lib`.
  - Verification: `cargo test -p xace-runtime-core x10_015 --lib --target-dir target-codex-replay-diagnosis`.

- [x] X10-016: Add crash-safe project recovery.
  - Acceptance: interrupted CGS writes, plan writes, snapshot index writes, save writes, runtime crashes, and Builder crashes recover to the last valid state.
  - Evidence: corruption-injection tests.
  - Done 2026-07-24: `CGSPersistence.recover()` now removes stale temp writes, rebuilds snapshot indexes, validates/restores plan-backed structural CGS states, repairs interrupted ExecutionPlan writes from valid SGC proof bundles, and removes incomplete proof bundles.
  - Builder binding: `create_app()` runs recovery at startup and returns the structured recovery report in the WebSocket `session_init` payload.
  - Project/save binding: project manifest/template writes now use crash-safe temp/fsync/replace plus last-valid backups, and `FileSaveEngine` now repairs corrupt or missing save files plus interrupted session/metadata commits to the last complete slot state.
  - Contract doc: `docs/CRASH_SAFE_PROJECT_RECOVERY.md`.
  - Certification: `tools/certify_launch.py` now runs focused project crash recovery and save crash recovery gates in quick/full certification.
  - Verification: `python -m unittest packages/project-system/tests/test_project_system.py packages/builder-workspace/server/tests/test_cgs_persistence_authority.py`; `cargo test -p xace-save-engine x10_016 --target-dir target-codex-crash-recovery`.

## Phase 3 - Mutation Safety And True Live Schema Hot-Swapping

Closes audit areas: mutation gate, live schema hot-swapping.

Master task sources: 39-44, 62-66, 77-81.

- [x] X10-017: Remove unreachable legacy mutation-gate apply code.
  - Acceptance: mutation gate has one apply path with atomic rollback, diagnostics, and tests.
  - Evidence: mutation-gate tests plus dead-code scan.
  - Done 2026-07-25: `MutationGate::apply_all()` and `MutationGate::apply_all_with_runtime_state()` now both delegate to one private `apply_all_transaction()` implementation; the hidden unreachable direct-apply body and `#[allow(unreachable_code)]` escape hatch were removed.
  - Runtime binding: the single apply implementation captures entity/component/queue state plus optional event/RNG rollback state, restores on apply-time failure, verifies rollback hash, stores `MutationApplyFailureDiagnostic`, and returns structured `XaceError` context.
  - Contract doc: `docs/05_mutation_lifecycle.md` now reflects the implemented runtime apply-time rollback contract and remaining overclaim boundaries for conflict analysis, engine side effects, and live hot-swap.
  - Certification: `tools/certify_launch.py` now runs `mutation gate apply path` and `mutation gate atomic wrapper` in quick/full certification.
  - Verification: `cargo test -p xace-runtime-core x10_017 --lib --target-dir target-codex-task17-runtime`; `cargo test -p xace-runtime-core mutation_gate --lib --target-dir target-codex-task17-runtime`; `python tools/mutation_gate_apply_path_check.py --json`.

- [x] X10-018: Add static mutation conflict analysis before commit.
  - Acceptance: proposed mutations are checked for dependency cycles, state conflicts, read/write hazards, incompatible component migrations, and generated-system ABI violations before CGS persistence.
  - Evidence: adversarial mutation corpus blocked before write.
  - Done 2026-07-25: GDE consistency validation now runs a static mutation conflict analyzer before commit and Builder direct asset-link persistence refuses invalid proposed CGS writes before saving.
  - Analyzer coverage: dependency cycles, same-phase read/write and write/write hazards, undeclared component access, incompatible component removal/rename/field migrations, and generated/plugin/external runtime executor ABI mismatches.
  - Certification: `tools/certify_launch.py` now runs `static mutation conflict analysis` in quick/full certification.
  - Certification maintenance: task 18 quick-certification also repaired drifted test-only smoke fixtures for strict CGS schema fields and fixed-point generated counter assertions.
  - Verification: `python tools/mutation_conflict_analysis_check.py --json`; `python -m unittest packages.builder-workspace.server.tests.test_session_manager_authority packages.builder-workspace.server.tests.test_engine_edit_router`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task18-quick --report-path target-codex-certify-task18-quick\launch_certification_report.json`.

- [x] X10-019: Make prompt, GDE, SGC, runtime, and adapter apply one atomic transaction.
  - Acceptance: failure in any step restores CGS, plan, runtime state, snapshot index, adapter-visible effects, and UI status.
  - Evidence: failure matrix leaves no partial state.
  - Done 2026-07-26: Builder prompt apply now treats GDE commit, SGC compile/skip, CGS save, snapshot, execution-plan/proof persistence, runtime reload, replay validation, adapter validation, and UI success emission as one recovery-backed transaction.
  - Recovery coverage: SGC and persistence failures after GDE commit reload the pre-apply CGS into GDE, restore `game.cgs.json`, prune failed-hash snapshot/plan/proof artifacts and snapshot-index entries, preserve pending prompt/UI status, restore the adapter-visible session edit log, and suppress `cgs_update`.
  - Runtime coverage: runtime/replay/adapter validation failures restore cached runtime status and request a runtime-control reload of the pre-apply version IDs when a runtime was connected.
  - Certification: `tools/certify_launch.py` now runs the renamed `prompt apply atomic recovery gate` in quick/full certification.
  - Verification: `python -m py_compile packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py tools/prompt_apply_recovery_check.py tools/certify_launch.py`; `python tools/prompt_apply_recovery_check.py --json`; `python tools/prompt_apply_validation_feedback_check.py --json`; `python -m unittest packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task19-quick --report-path target-codex-certify-task19-quick\launch_certification_report.json`.

- [x] X10-020: Implement state-preserving runtime schema hot-swap.
  - Acceptance: accepted schema/system changes compile into a new plan and swap at a safe tick boundary without resetting global state vectors.
  - Evidence: runtime remains at live tick, entity IDs and component state preserved, new systems active on the expected tick.
  - Done 2026-07-26: `RuntimeOrchestrator::hot_swap_cgs_at_tick_boundary()` now loads the incoming CGS and persisted SGC plan into scratch stores, builds a fresh runtime registry/schedule identity, validates additive component-table compatibility, and swaps the active runtime metadata/registry/schedule at the current clean tick boundary without rebuilding `EntityStore` or existing component rows.
  - Runtime binding: `reload_cgs` in `xace_runtime` now performs state-preserving hot-swap instead of disconnecting adapters and resetting the orchestrator to tick 0; requested CGS hash, schema version, and execution-plan version are validated against the disk CGS/plan before swap.
  - Determinism binding: `DeterminismGuard::reconfigure_for_hot_swap()` relocks schema/plan/system IDs for the new compiled schedule while preserving the existing per-tick hash log.
  - Certification: `tools/certify_launch.py` now runs `runtime schema hot-swap` in quick/full certification.
  - Verification: `cargo test -p xace-runtime-core x10_020 --lib --target-dir target-codex-task20-runtime`; `cargo test -p xace-runtime-core --target-dir target-codex-task20-runtime`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task20-quick --report-path target-codex-certify-task20-quick\launch_certification_report.json`.

- [x] X10-021: Define and enforce hot-swap compatibility classes.
  - Acceptance: additive, migratable, state-transforming, and reset-required changes are classified; only compatible changes hot-swap live.
  - Evidence: incompatible changes are refused or require explicit reset approval.
  - Done 2026-07-27: runtime hot-swap now emits `RuntimeHotSwapCompatibilityReport` with `additive`, `migratable`, `state_transforming`, and `reset_required` classes plus stable issue codes for component, actor topology, semantic binding, schedule, and system-contract changes.
  - Runtime binding: `RuntimeOrchestrator::classify_hot_swap_cgs_at_tick_boundary()` and the live `hot_swap_cgs_at_tick_boundary()` path share the same scratch-load candidate; live swap proceeds only when every issue is `additive`, and refuses migratable/state-transforming/reset-required candidates before mutating live state.
  - Enforcement coverage: empty new component tables and added systems are additive; actor component backfill requirements are migratable; existing system executor/access/order/phase/dependency changes are state-transforming; actor topology/mode/component removal changes are reset-required.
  - Certification: `tools/certify_launch.py` now runs `runtime hot-swap compatibility classes` in quick/full certification.
  - Verification: `cargo test -p xace-runtime-core x10_021 --lib --target-dir target-codex-task21-runtime`; `cargo test -p xace-runtime-core --target-dir target-codex-task21-runtime`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task21-quick --report-path target-codex-certify-task21-quick\launch_certification_report.json`.

- [x] X10-022: Add runtime state migration hooks.
  - Acceptance: component schema migrations transform existing state deterministically and record old/new hashes.
  - Evidence: migration tests across multiple component versions.
  - Done 2026-07-27: runtime hot-swap now supports explicit `RuntimeComponentMigrationHook` registrations for deterministic component backfill from the candidate CGS defaults; migratable candidates still fail closed unless every migratable compatibility issue has an exact hook for the from/to schema-version transition and component type.
  - Runtime binding: `RuntimeOrchestrator::hot_swap_cgs_at_tick_boundary()` resolves migration hooks before live mutation, applies component table additions and migration writes under the existing rollback snapshot, verifies entity state remains unchanged, and emits `RuntimeHotSwapMigrationReport` with old/new world hashes plus per-component row hashes.
  - Audit log: `RuntimeOrchestrator::migration_log()` records successful migration reports, while missing-hook attempts are refused before state mutation.
  - Certification: `tools/certify_launch.py` now runs `runtime state migration hooks` in quick/full certification.
  - Verification: `cargo test -p xace-runtime-core x10_022 --lib --target-dir target-codex-task22-runtime`; `cargo test -p xace-runtime-core --lib --target-dir target-codex-task22-runtime`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task22-quick --report-path target-codex-certify-task22-quick\launch_certification_report.json`.

- [ ] X10-023: Add engine-side side-effect rollback.
  - Acceptance: adapter-spawned objects, playback commands, feedback queues, pending edits, and asset binding state roll back after failed runtime mutation.
  - Evidence: installed-engine failure tests.

- [ ] X10-024: Harden bidirectional edit boundaries.
  - Acceptance: engine-originated commits are limited to supported selection/focus/default edit classes unless explicitly expanded; stale edits are rejected by CGS hash, runtime hash, adapter sequence, schema version, and preview ID.
  - Evidence: edit preview, approval, undo, redo, conflict, and recovery tests.

## Phase 4 - Prompt Intelligence With Hard Grammar And Broad Gameplay Generation

Closes audit area: prompt intelligence layer and grammar constraints.

Master task sources: 38-43, 49-58, plus launch thresholds.

- [ ] X10-025: Add provider-level structured output constraints where providers support them.
  - Acceptance: production provider calls request JSON schema or equivalent structured output for mutation transactions; unsupported providers are routed through a stricter repair/quarantine path.
  - Evidence: provider request/response telemetry proves structured constraints were active.

- [ ] X10-026: Make unknown CGS paths hard failures in production.
  - Acceptance: parser path validation no longer allows unknown mutation paths to proceed for production applies.
  - Evidence: parser tests and prompt corpus adversarial cases.

- [ ] X10-027: Normalize prompt test packaging.
  - Acceptance: one Python command runs all prompt-intelligence tests without missing imports such as `pil_retry_policy`.
  - Evidence: CI artifact for prompt Python suite.

- [ ] X10-028: Run the launch provider/runtime prompt benchmark profile.
  - Acceptance: `launch_provider_runtime` executes real provider, compile, runtime, rollback, unsupported blocking, cost, latency, and reproducibility dimensions.
  - Evidence: benchmark report passes thresholds in `docs/PROMPT_LAUNCH_THRESHOLDS.md`.

- [ ] X10-029: Expand gameplay primitive library.
  - Acceptance: reusable schema/system/event/input/asset/save/network primitives cover platformer, RPG, shooter, survival, puzzle, strategy, simulation, inventory, combat, and multiplayer combat.
  - Evidence: every primitive SGC-compiles and runtime-replays.

- [ ] X10-030: Implement schema generation from prompts through typed CGS operations only.
  - Acceptance: new components, systems, events, rules, assets, and defaults are generated as typed operations, not ad hoc JSON patches.
  - Evidence: generated schemas pass validation, SGC, runtime, replay, and rollback.

- [ ] X10-031: Implement generated system definitions from prompts.
  - Acceptance: every accepted generated system has reads, writes, dependencies, phase, version, deterministic ABI, rollback hooks, and user-facing explanation.
  - Evidence: generated systems enter SGC without manual repair.

- [ ] X10-032: Implement composite prompt planning.
  - Acceptance: multi-system prompts produce ordered schema/system/asset/network/save operations with rollback plan and dependency graph.
  - Evidence: complex prompt plans preview, apply, or rollback atomically.

- [ ] X10-033: Add prompt undo/redo with proof links.
  - Acceptance: at least 50 chained prompt mutations undo and redo with matching CGS, SGC plan, runtime, and replay hashes.
  - Evidence: mutation history artifact.

- [ ] X10-034: Add long-session prompt degradation tests.
  - Acceptance: long authoring sessions with context growth, edits, undo, provider failure, and stale state complete without corruption or unbounded cost.
  - Evidence: fixed-length or 8-hour session report.

## Phase 5 - Native Rollback Netcode And Multiplayer Integration

Closes audit area: rollback netcode and multiplayer synchronization.

Master task sources: 102-110, 111.

- [ ] X10-035: Choose multiplayer launch topology.
  - Acceptance: host/client, dedicated server, peer-to-peer, or offline-only scope is explicitly selected; unsupported topologies fail visibly.
  - Evidence: topology matrix and tests.

- [ ] X10-036: Integrate input synchronization into runtime tick advancement.
  - Acceptance: runtime tick progression consumes `InputSynchroniser` lockstep decisions instead of directly applying raw pending engine inputs.
  - Evidence: missing, delayed, synthetic, and late inputs produce deterministic decisions.

- [ ] X10-037: Integrate rollback manager with runtime snapshots and resimulation.
  - Acceptance: authoritative late input or desync triggers restore, deterministic resim, hash validation, and adapter resync.
  - Evidence: rollback count and restored tick recorded in proof artifacts.

- [ ] X10-038: Integrate prediction and reconciliation for supported clients.
  - Acceptance: prediction buffer and reconciliation engine are wired into supported topology and never mutate authoritative state directly.
  - Evidence: prediction correction tests and client/server hash comparison.

- [ ] X10-039: Implement lobby/session lifecycle.
  - Acceptance: create, join, leave, reconnect, late join, ready state, player identity, and teardown work for the chosen topology.
  - Evidence: runtime plus Builder UI tests.

- [ ] X10-040: Add session compatibility checks.
  - Acceptance: schema, SGC plan, adapter version, assets, packages, provider-free metadata, and template mismatches block session start.
  - Evidence: mismatch matrix tests.

- [ ] X10-041: Harden malicious input limits.
  - Acceptance: rate limits, packet validation, sequence checks, replay protection, authority checks, and cheat guard enforcement block bad traffic without desync or crash.
  - Evidence: malicious packet tests.

- [ ] X10-042: Add multiplayer diagnostics panel.
  - Acceptance: peers, ticks, input buffers, latency, rollback count, resync status, packet loss, hash comparisons, and authority owner are visible.
  - Evidence: UI/server tests and chaos report.

- [ ] X10-043: Run network chaos proof.
  - Acceptance: 4 to 16 clients, 60 minutes, packet loss, jitter, reordering, disconnect, reconnect, late join, malformed input, rollback, and resync finish with zero permanent desync for supported scenarios.
  - Evidence: `.xace/proof/network-chaos/<run-id>/`.

- [ ] X10-044: Run long multi-user soak.
  - Acceptance: multi-user sessions with saves, supported prompt changes, adapter reconnects, and runtime restarts complete without corruption or unrecoverable desync.
  - Evidence: soak report.

## Phase 6 - Time-Travel Debugger And Diagnostics

Closes audit area: time-travel debugging and state rollback.

Master task sources: 65, 67-76.

- [ ] X10-045: Implement minimum tick debugger.
  - Acceptance: timeline, pause, step, snapshot list, state diff, mutation history, event trace, and hash-mismatch display work without reading source.
  - Evidence: known divergence can be reproduced and inspected from UI.

- [ ] X10-046: Add reverse-step and time-travel navigation.
  - Acceptance: debugger moves forward and backward across at least 1,000 ticks with matching hashes.
  - Evidence: debugger time-travel tests.

- [ ] X10-047: Add delta-compressed timeline retention.
  - Acceptance: snapshots plus deltas support memory-bounded scrubbing without losing authoritative restore capability.
  - Evidence: memory and restore benchmarks.

- [ ] X10-048: Add debugger conditional breakpoints.
  - Acceptance: break on entity state, component value, event type, mutation type, system ID, RNG call, hash mismatch, and network desync.
  - Evidence: breakpoint tests hit exact ticks.

- [ ] X10-049: Add causality graph.
  - Acceptance: reports trace which prompt, mutation, system, event, RNG call, feedback, or network packet caused a state change.
  - Evidence: combat damage event traced end to end.

- [ ] X10-050: Add RNG seed trace panel.
  - Acceptance: every deterministic RNG call is visible by tick, system, seed, stream position, and result.
  - Evidence: illegal RNG blocked and legal RNG replayed identically.

- [ ] X10-051: Add support diagnostics bundle.
  - Acceptance: one command exports redacted versions, manifests, logs, proof links, config, adapter health, provider readiness, and reproduction commands.
  - Evidence: support bundle smoke test.

- [ ] X10-052: Add exportable debug report.
  - Acceptance: debugger state, replay inputs, hash logs, SGC plan, mutation log, and adapter feedback load in a fresh checkout.
  - Evidence: debug report round-trip test.

## Phase 7 - Engine Adapters, Assets, Import, Export, And Cross-Engine Slice

Closes audit areas: engine-agnostic execution, portability, installed-engine readiness.

Master task sources: 82-101, 122.

- [ ] X10-053: Harden asset reference validation.
  - Acceptance: asset refs, hashes, types, statuses, engine support, and missing files are validated before runtime, export, save, and adapter handoff.
  - Evidence: unresolved refs blocked or given documented fallback.

- [ ] X10-054: Build semantic binding UI.
  - Acceptance: creators can map semantic events to animation, audio, and VFX commands per engine.
  - Evidence: bindings produce runtime playback commands in Godot, Unity, and Unreal tests.

- [ ] X10-055: Add engine-specific binding status.
  - Acceptance: resolved, unresolved, unsupported, missing, and fallback statuses are tracked per engine and surfaced before export/runtime launch.
  - Evidence: Builder tests and adapter reports.

- [ ] X10-056: Define deterministic runtime fallback bindings.
  - Acceptance: missing animation/audio/VFX/prefab/mesh bindings fall back visibly, never crash, and are never reported as resolved.
  - Evidence: adapter proof artifacts.

- [ ] X10-057: Harden import marker validation and read-only inventory.
  - Acceptance: Godot, Unity, and Unreal project markers are detected without modifying projects; scenes/assets/scripts/plugins/input maps are inventoried as references only.
  - Evidence: ambiguous project imports refused with reports.

- [ ] X10-058: Build manual migration wizard.
  - Acceptance: engine entities/assets/scenes can be mapped to CGS semantic bindings and starter components with reversible mappings.
  - Evidence: manual-work report matches actual files.

- [ ] X10-059: Add reversible adapter install/uninstall.
  - Acceptance: install, update, rollback, and uninstall adapters without deleting user engine data.
  - Evidence: before/after checks.

- [ ] X10-060: Rename export to adapter package handoff.
  - Acceptance: UI, docs, API names, and reports avoid "finished game export" claims.
  - Evidence: forbidden wording scan.

- [ ] X10-061: Add export preflight validation.
  - Acceptance: CGS, SGC plan, runtime compatibility, adapter version, assets, bindings, secrets, and target engine must pass before package handoff.
  - Evidence: blocked export matrix.

- [ ] X10-062: Version adapter packages.
  - Acceptance: Godot, Unity, and Unreal packages include version, compatibility matrix, dependency declarations, install/uninstall scripts, rollback support, and checksums.
  - Evidence: package verification in CI.

- [ ] X10-063: Define canonical cross-engine vertical slice.
  - Acceptance: one CGS-owned slice covers movement, combat, health, inventory, save/load, rollback, replay, semantic bindings, animation, audio, VFX, and network-ready input.
  - Evidence: fixture versioned.

- [ ] X10-064: Certify vertical slice in Godot.
  - Acceptance: installed Godot proof includes validation JSON, screenshots or video, logs, and hash report.
  - Evidence: installed-engine proof path.

- [ ] X10-065: Certify vertical slice in Unity.
  - Acceptance: installed Unity proof includes validation JSON, screenshots or video, logs, and hash report.
  - Evidence: installed-engine proof path.

- [ ] X10-066: Certify vertical slice in Unreal.
  - Acceptance: installed Unreal proof includes validation JSON, screenshots or video, logs, and hash report.
  - Evidence: installed-engine proof path.

- [ ] X10-067: Compare cross-engine core hashes.
  - Acceptance: portable runtime-authoritative hashes match; nonportable visual/engine effects are documented as excluded.
  - Evidence: cross-engine comparison report.

## Phase 8 - Save/Load, Migration, Packages, Extensions, And Team Workflows

Closes commercial completeness gaps around durable projects.

Master task sources: 111-116.

- [ ] X10-068: Harden save/load authority.
  - Acceptance: saves include CGS, SGC plan, runtime state, snapshots, assets, bindings, provider-free metadata, and multiplayer state where supported.
  - Evidence: save/load/replay hash equivalence tests.

- [ ] X10-069: Add schema and save migration tooling.
  - Acceptance: old project and save fixtures load or fail with a migration-required report.
  - Evidence: migration fixture suite.

- [ ] X10-070: Version starter templates.
  - Acceptance: every shipped template has ID, semantic version, compatibility contract, migration path, and proof artifact.
  - Evidence: template creation produces a certified project.

- [ ] X10-071: Version packages and extensions.
  - Acceptance: dependency declarations, compatibility matrix, install/update/uninstall/rollback flow, and checksums are enforced.
  - Evidence: package manager rollback tests.

- [ ] X10-072: Define third-party extension API.
  - Acceptance: extension points, sandboxing, determinism requirements, compatibility, security review, and deprecation policy are documented and enforced.
  - Evidence: one sample extension passes validation without bypassing SGC.

- [ ] X10-073: Add team source-control workflows.
  - Acceptance: CGS serialization, diffs, merge conflict visibility, schema branches, and lock files are deterministic and recoverable.
  - Evidence: team workflow tests.

## Phase 9 - Performance, Fuzzing, Soak, CI, Security, And Release Proof

Closes commercial reliability and launch-readiness gaps.

Master task sources: 117-129, 133-150.

- [ ] X10-074: Add scale benchmarks.
  - Acceptance: benchmark 10k entities, 100 systems, 1k events per tick, snapshots, deltas, bridge, save/load, replay, rollback, SGC, prompt planning, and adapters.
  - Evidence: JSON baselines under `benchmarks/<date>/<machine>.json`.

- [ ] X10-075: Define performance budgets.
  - Acceptance: runtime tick, SGC compile, prompt latency, provider cost, adapter apply, network tick, save/load, memory, and UI responsiveness thresholds block regressions.
  - Evidence: CI budget gate.

- [ ] X10-076: Add fuzz harnesses.
  - Acceptance: fuzz CGS, mutations, network packets, provider responses, schema versions, imports, adapter messages, serialization, package manifests, and extension metadata.
  - Evidence: scheduled fuzz artifacts.

- [ ] X10-077: Run 8-hour product soak.
  - Acceptance: prompt apply, SGC, runtime, replay, rollback, save/load, import/export, adapters, network, provider failures, and Builder UI repeat without leak, corruption, secret leak, or unrecoverable state.
  - Evidence: soak report.

- [ ] X10-078: Set up hosted CI.
  - Acceptance: Windows, Linux, macOS, Rust, Python, TypeScript, engine-free certification, artifact retention, secret scanning, benchmark gates, and reproducible build config block merges.
  - Evidence: required CI checks.

- [ ] X10-079: Add installed-engine CI lane.
  - Acceptance: opt-in or scheduled Godot, Unity, and Unreal validation produces proof artifacts for advertised versions.
  - Evidence: installed-engine CI reports.

- [ ] X10-080: Add reproducible builds.
  - Acceptance: toolchains, dependencies, provider test modes, engine versions, adapters, and package hashes are pinned.
  - Evidence: clean checkout builds produce identical artifacts within defined tolerance.

- [ ] X10-081: Add release artifact signing.
  - Acceptance: runtime binaries, Builder packages, adapter packages, installers, checksums, and proof manifests are signed; install/update refuses unsigned artifacts.
  - Evidence: signing verification tests.

- [ ] X10-082: Complete supply-chain review.
  - Acceptance: dependencies, licenses, vulnerabilities, vendored code, generated code, package metadata, and binary artifacts are clean or risk-accepted.
  - Evidence: dependency/license reports.

- [ ] X10-083: Harden secrets and privacy.
  - Acceptance: no keys in source, CGS, logs, snapshots, exports, crash reports, telemetry, screenshots, fixtures, proof artifacts, or support bundles.
  - Evidence: redaction and secret-scan tests.

- [ ] X10-084: Define telemetry opt-in.
  - Acceptance: analytics, crash reports, provider telemetry, performance metrics, and support bundles are privacy-safe, inspectable, revocable, and off until consent.
  - Evidence: telemetry tests.

- [ ] X10-085: Add backup and disaster recovery.
  - Acceptance: project backup, restore, rollback, corrupt-file repair, lost-provider-key behavior, artifact retention, and hosted recovery drills pass.
  - Evidence: disaster drill report.

- [ ] X10-086: Complete external security review.
  - Acceptance: critical/high findings are fixed or formally risk-accepted before commercial launch.
  - Evidence: security review record.

- [ ] X10-087: Create external-user installation flow.
  - Acceptance: fresh machine user can install, configure provider/engine, create project, run verification, and recover without repository knowledge.
  - Evidence: fresh-machine install proof.

- [ ] X10-088: Create onboarding tutorials.
  - Acceptance: tutorials cover prompt authoring, deterministic proof, debugger, asset binding, import/wrap, adapter handoff, multiplayer, save/load, and rollback recovery.
  - Evidence: non-author validation.

- [ ] X10-089: Create generated compatibility matrices.
  - Acceptance: OSes, engines, providers, adapters, templates, packages, multiplayer topology, and unsupported features are generated from certification artifacts.
  - Evidence: matrix generation check.

- [ ] X10-090: Add support workflow.
  - Acceptance: support bundles, issue templates, triage labels, severity levels, response times, escalation, and communication paths are drilled.
  - Evidence: simulated customer blocker resolved.

- [ ] X10-091: Run external creator usability test.
  - Acceptance: target creators install, configure, author, validate, debug, recover, and adapter-handoff without repository help.
  - Evidence: tracked issues closed or signed off.

- [ ] X10-092: Build readiness scoring tool.
  - Acceptance: scorecards are generated from tests, proofs, docs, CI, benchmarks, security, usability, and launch gates; scores below 9 block sign-off.
  - Evidence: scorecard artifact.

- [ ] X10-093: Independently verify readiness scores.
  - Acceptance: separate audit reproduces every 9/10 or 10/10 score from clean checkout.
  - Evidence: independent audit report.

- [ ] X10-094: Prepare public demo proof one.
  - Acceptance: deterministic bug-catching demo shows bad mutation, hash divergence or rollback, exact diagnosis, fix, replay, and proof artifact.
  - Evidence: stranger can reproduce from release docs.

- [ ] X10-095: Prepare public demo proof two.
  - Acceptance: cross-engine vertical-slice demo runs across Godot, Unity, and Unreal with matching portable-core hashes and visible gameplay.
  - Evidence: installed-engine artifacts and visual proof.

- [ ] X10-096: Prepare public demo proof three.
  - Acceptance: prompt-to-gameplay demo runs prompt through real provider, GDE, SGC, runtime, replay, rollback, adapter mirroring, and debug report.
  - Evidence: benchmarked prompt categories and honest unsupported boundaries shown.

- [ ] X10-097: Align all public claims to proof.
  - Acceptance: every website, README, Builder label, tutorial, release note, screenshot, and demo claim maps to a proof artifact.
  - Evidence: claim audit passes.

- [ ] X10-098: Complete private-alpha gate.
  - Acceptance: clean tests, one reproducible local path, no fake confidence, no known corruption path, provider readiness, recovery, and support bundle are signed off.
  - Evidence: private-alpha gate artifact.

- [ ] X10-099: Complete public-beta gate.
  - Acceptance: prompt corpus, installed-engine proof, CI, docs, onboarding, security basics, import/export honesty, debugger minimum, and usability fixes are signed off.
  - Evidence: public-beta gate artifact.

- [ ] X10-100: Complete commercial-launch gate and cut signed release candidate.
  - Acceptance: 9/10+ scorecard, security review, updater/rollback, support, cross-platform replay, chaos/soak/fuzz, demos, public claims, and signed packages are approved.
  - Evidence: tagged release candidate with proof manifest.

## Conditional Commercial Tasks

These are required only if the chosen commercial scope includes paid licensing, hosted services, billing, or auto-updates. If XACE remains local-first/BYOK/offline-usable for the first launch, keep these as explicitly deferred with a signed product-scope decision.

Master task sources: 130-132.

- [ ] CX-001: Licensing and entitlement system.
  - Required if: paid seats, trials, activation, offline grace, team entitlements, or gated features are part of launch.

- [ ] CX-002: Billing and commercial operations.
  - Required if: XACE sells through a billing provider or hosts paid account features.

- [ ] CX-003: Updater and release channels.
  - Required if: XACE ships auto-update, beta/nightly channels, adapter updates, or in-app release management.

## Recommended Execution Order

1. Phase 1 - authoritative CGS/SGC/runtime contract.
2. Phase 2 - deterministic fixed-point state and complete snapshots.
3. Phase 3 - true live hot-swap and atomic mutation safety.
4. Phase 4 - hard prompt grammar and launch provider/runtime benchmark.
5. Phase 5 - runtime-integrated rollback netcode.
6. Phase 6 - debugger and diagnostics.
7. Phase 7 - installed-engine adapter proof and cross-engine slice.
8. Phase 8 - save/load, migration, packages, extension API, team workflows.
9. Phase 9 - scale, fuzz, soak, CI, security, demos, claims, release.

## First Five Tasks To Start With

- [x] Start with X10-001.
- [x] Then X10-002.
- [x] Then X10-003.
- [x] Then X10-004.
- [x] Then X10-005.

Reason:
These five tasks make the runtime trust boundary real. Without that, later work on prompt generation, rollback netcode, hot-swapping, debugger time travel, and engine proof will keep inheriting uncertainty from hashless or fallback execution paths.
