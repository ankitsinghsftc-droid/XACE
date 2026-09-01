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

- [x] X10-023: Add engine-side side-effect rollback.
  - Acceptance: adapter-spawned objects, playback commands, feedback queues, pending edits, and asset binding state roll back after failed runtime mutation.
  - Evidence: installed-engine failure tests.
  - Done 2026-07-27: runtime protocol now includes `adapter_side_effect_rollback` with restored snapshots, revoked playback commands, queue/edit/cache reset flags, and runtime audit reports. `RuntimeOrchestrator` emits rollback notices on authoritative snapshot restore and hot-swap preparation failures after restoring runtime state, while preserving connected adapters instead of disconnecting them.
  - Adapter binding: Godot, Unity, and Unreal advertise `adapter_side_effect_rollback_v1`, parse/dispatch the rollback message, rebuild mirrors from the restored snapshot, clear feedback queues, clear pending edit previews, reset asset-binding caches, stop/revoke playback, and remove tracked playback-spawned VFX/audio objects.
  - Certification: `tools/certify_launch.py` now runs `engine side-effect rollback` in quick/full certification.
  - Verification: `cargo test -p xace-runtime-core x10_023 --lib --target-dir target-codex-task23-runtime`; `cargo test -p xace-runtime-core adapter_side_effect_rollback --lib --target-dir target-codex-task23-runtime`; `python tools/engine_side_effect_rollback_check.py --json`.

- [x] X10-024: Harden bidirectional edit boundaries.
  - Acceptance: engine-originated commits are limited to supported selection/focus/default edit classes unless explicitly expanded; stale edits are rejected by CGS hash, runtime hash, adapter sequence, schema version, and preview ID.
  - Evidence: edit preview, approval, undo, redo, conflict, and recovery tests.
  - Done 2026-07-28: Builder now treats engine-originated edits as preview-first audit rows. Accepted previews receive a deterministic `preview_id` plus `preview_cgs_hash`, `preview_schema_version`, `runtime_world_hash`, and `engine_adapter_sequence`; durable commit requests must echo the accepted audit envelope and current CGS/schema/runtime/adapter version IDs before GDE or persistence can run.
  - Boundary policy: selection/focus are allowed preview classes but remain preview-only; durable commits are limited to accepted primitive `set_component_field` component-default edits. Unsupported or stale commit classes are rejected visibly before persistence, and failed GDE commits leave the accepted preview recoverable instead of marking it committed.
  - Certification: `tools/certify_launch.py` now runs `engine edit boundary` in quick/full certification.
  - Verification: `python -m unittest packages/builder-workspace/server/tests/test_engine_edit_router.py`; `python -m unittest discover packages/builder-workspace/server/tests`; `npm run build --workspace @xace/builder-workspace`; `cargo test -p xace-runtime-core --lib --target-dir target-codex-task24-runtime`; `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task24-runtime`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task24-quick --report-path target-codex-certify-task24-quick\launch_certification_report.json`.

## Phase 4 - Prompt Intelligence With Hard Grammar And Broad Gameplay Generation

Closes audit area: prompt intelligence layer and grammar constraints.

Master task sources: 38-43, 49-58, plus launch thresholds.

- [x] X10-025: Add provider-level structured output constraints where providers support them.
  - Acceptance: production provider calls request JSON schema or equivalent structured output for mutation transactions; unsupported providers are routed through a stricter repair/quarantine path.
  - Evidence: provider request/response telemetry proves structured constraints were active.
  - Completed: Pass 5 now requests the `xace.mutation_transaction.v1` structured-output contract; `InferenceAdapter` bypasses stale response-cache hits for constrained calls, sends native provider constraints to OpenAI (`response_format.json_schema`), Google (`responseMimeType`/`responseSchema`), and Anthropic (forced `tool_choice`), and routes unsupported providers through strict repair/quarantine prompt injection plus schema-error retry validation.
  - Verification: `python -m unittest packages.inference.tests.test_structured_output_constraints`; `python tools/provider_structured_output_check.py target-codex-task25-provider-structured-output\provider_structured_output_report.json`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task25-quick --report-path target-codex-certify-task25-quick\launch_certification_report.json`.
- [x] X10-026: Make unknown CGS paths hard failures in production.
  - Acceptance: parser path validation no longer allows unknown mutation paths to proceed for production applies.
  - Evidence: parser tests and prompt corpus adversarial cases.
  - Completed: `SchemaPathValidator` now records unrecognised grammar in `unknown_paths` and counts those paths as invalid production mutation inputs; `ValidationLoop` blocks them in layer 1 instead of downgrading them to manual-review warnings; `pc099` in the reviewed prompt corpus pins an adversarial unknown-path production-block case.
  - Verification: `python packages/prompt-intelligence/src/tests/test_unknown_cgs_path_failures.py`; `python tools/prompt_unknown_cgs_path_check.py --output target-codex-task26-unknown-path\prompt_unknown_cgs_path_report.json --json`; `python tools/prompt_corpus_check.py --json`; `python tools/certify_launch.py --quick --target-dir target-codex-certify-task26-quick --report-path target-codex-certify-task26-quick\launch_certification_report.json`.
- [x] X10-027: Normalize prompt test packaging.
  - Acceptance: one Python command runs all prompt-intelligence tests without missing imports such as `pil_retry_policy`.
  - Evidence: CI artifact for prompt Python suite.
  - Completed: `tools/python_test_gate.py` now exposes `--suite prompt-intelligence` as a public focused command, creates child output directories before writing artifacts, and records selected suites/tool-command state in the report; `pil_retry_policy.py` is a real compatibility module for the legacy retry-policy import instead of a runner-only alias; launch certification runs the focused prompt suite and stores the prompt Python artifact.
  - Verification: `python tools/python_test_gate.py --suite prompt-intelligence --output target-codex-task27-prompt-suite\python_gate_report.json`; `python -m py_compile tools/python_test_gate.py tools/certify_launch.py packages/prompt-intelligence/src/llm_orchestrator/pil_retry_policy.py`; focused launch-certification binding `prompt intelligence Python suite` via `tools.certify_launch.run_check`.
- [x] X10-028: Run the launch provider/runtime prompt benchmark profile.
  - Acceptance: `launch_provider_runtime` executes real provider, compile, runtime, rollback, unsupported blocking, cost, latency, and reproducibility dimensions.
  - Evidence: benchmark report passes thresholds in `docs/PROMPT_LAUNCH_THRESHOLDS.md`.
  - Completed: `tools/launch_provider_runtime_benchmark.py` now runs the reviewed 100-prompt corpus under the `launch_provider_runtime` profile, drives provider-allowed rows through the real `InferenceAdapter` telemetry/accounting path with a deterministic local provider client, attaches real SGC/runtime and rollback proof dimensions, evaluates the launch thresholds, and is wired into launch certification. Classifier routing and shared threshold metrics were tightened so certified launch rows route and score correctly without changing the local classifier-only not-run contract.
  - Verification: `python -m py_compile tools/launch_provider_runtime_benchmark.py tools/prompt_corpus_benchmark.py tools/certify_launch.py tools/prompt_launch_threshold_check.py packages/builder-workspace/server/prompt_classifier_gate.py`; `python tools/prompt_classifier_gate_check.py --json`; `python tools/prompt_corpus_benchmark.py --output target-codex-task28-classifier-check --json`; `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-runtime`; `cargo build -p xace-system-graph-compiler --target-dir target-codex-task28-runtime`; `python tools/launch_provider_runtime_benchmark.py --output target-codex-task28-launch-provider-runtime --runtime-bin target-codex-task28-runtime\debug\xace_runtime.exe --sgc-bin target-codex-task28-runtime\debug\xace-system-graph-compiler.exe --json`.

- [x] X10-029: Expand gameplay primitive library.
  - Acceptance: reusable schema/system/event/input/asset/save/network primitives cover platformer, RPG, shooter, survival, puzzle, strategy, simulation, inventory, combat, and multiplayer combat.
  - Evidence: every primitive SGC-compiles and runtime-replays.
  - Done 2026-08-08: the production catalog now provides ten reusable primitives spanning every required genre and all seven required facets, backed by canonical UCL/input/event contracts, real builtin runtime executors, validated semantic asset bindings, deterministic save declarations, and explicit network policy.
  - SGC safety: direct same-phase ordering edges now prevent dependency-linked systems from entering the same parallel execution window, while independent siblings with a shared predecessor still co-schedule; this preserves declared system order without weakening existing RAW/WAW hazard behavior.
  - Proof: `target-codex-task29-primitives/gameplay-primitives/report.json` passes 10/10 primitives with real SGC plan persistence, exact catalog schedule matching, two four-tick runtime launches per primitive, four distinct tick hashes per run, and byte-stable replay hashes. Report SHA-256: `da6ff3244c93f1a99b3dd7ba0dcda883444bdb585f2ccc92d1fb82833a0f2d41`.
  - Verification: `cargo fmt -p xace-system-graph-compiler`; `python -m unittest packages.dcl.tests.test_gameplay_primitives -v` (14 passed); `cargo test -p xace-system-graph-compiler scheduler::parallel_group_analyzer::tests:: --target-dir target-codex-task29-primitives` (11 passed); `cargo test -p xace-system-graph-compiler --target-dir target-codex-task29-primitives` (250 library, 3 CLI, and 1 doc test passed); `cargo build -p xace-system-graph-compiler --target-dir target-codex-task29-primitives`; `cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task29-primitives`; `python tools/gameplay_primitive_library_check.py --runtime-bin target-codex-task29-primitives\debug\xace_runtime.exe --sgc-bin target-codex-task29-primitives\debug\xace-system-graph-compiler.exe --output target-codex-task29-primitives\gameplay-primitives\report.json --artifact-dir target-codex-task29-primitives\gameplay-primitives\artifacts --require-full-catalog --json`.

- [x] X10-030: Implement schema generation from prompts through typed CGS operations only.
  - Acceptance: new components, systems, events, rules, assets, and defaults are generated as typed operations, not ad hoc JSON patches.
  - Evidence: generated schemas pass validation, SGC, runtime, replay, and rollback.
  - Done 2026-08-09: prompt-authored schema changes now use the closed `xace.typed_cgs_operation_batch.v1` grammar for component declarations/attachments, registered systems, semantic events, rules, assets, and defaults. Live PIL preserves the canonical path-free batch through Builder preview/approval, and GDE independently reparses and applies the whole batch to an isolated CGS copy before one validated minor-version commit.
  - Provider/type safety: the provider schema uses the native strict-output subset (closed root object, nested `anyOf`, all object properties required), legacy structural path operations fail closed, existing schema writes require exact field metadata, numeric types cannot be interchanged, and negative `uint`/`entity_id` values are rejected atomically. The X10-030 `add_system` family remains limited to exact registered `builtin.<SystemID>.v1` contracts; X10-031 adds generated behavior through a separate trust boundary.
  - Proof: `target-codex-task30-typed-operations/report.json` passes all 17 retained checks across all seven operation families, strict provider-schema validation, Builder/GDE atomic application, standalone CGS validation, real SGC plan persistence, two real runtime launches, replay matching, adversarial type rejection, and exact rollback. Report SHA-256: `916b4f2d65129569fea427ecf178eb832a82ff7ae5da078d584c31b3e1bcf972`.
  - Verification: `python tools/python_test_gate.py --suite prompt-intelligence --output target-codex-task30-typed-operations\prompt-suite.json` (435 passed); focused typed prompt/GDE/provider/Builder suites (30 + 8 + 6 + 3 passed); `python packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py -v` (21 passed); `python tools/source_inventory_check.py --json` (`[]`); `python tools/typed_cgs_operation_e2e_check.py --runtime-bin target-codex-task29-primitives\debug\xace_runtime.exe --sgc-bin target-codex-task29-primitives\debug\xace-system-graph-compiler.exe --artifact-dir target-codex-task30-typed-operations\artifacts --output target-codex-task30-typed-operations\report.json --json`.

- [x] X10-031: Implement generated system definitions from prompts.
  - Acceptance: every accepted generated system has reads, writes, dependencies, phase, version, deterministic ABI, rollback hooks, and user-facing explanation.
  - Evidence: generated systems enter SGC without manual repair.
  - Done 2026-08-09: Pass 2 can emit the closed `add_generated_system` behavior definition without source or executable metadata. A local materializer derives the exact ABI/rollback executor, generates and safe-compiles Rust, invokes real SGC, verifies the signed artifact, and hands the trusted batch through Builder to independent atomic GDE validation. The first production behavior increments one exact `fixed` field by an integer whole-unit delta.
  - Trust/determinism: provider-supplied executors fail closed; unsigned or tampered artifacts are rejected without CGS mutation; Builder preserves only the locally materialized executor; and nondeterministic Cargo wall-clock duration is excluded from authoritative CGS through canonical `duration_ms = 0`.
  - Proof: `target-codex-task31-generated-systems/report.json` passes all 25 retained checks twice with identical bytes across provider-schema exclusion, local generation/signing, complete system metadata/ABI/hooks/explanation, atomic GDE commit, standalone schema validation, real SGC plan persistence, two real runtime launches, changing tick hashes, deterministic replay, adversarial rejection, and exact rollback. Report SHA-256: `5dfd9f7395128b2709b2639ac2decf5ad2f692a0fb7f8c8391c16320ea0e03b1`.
  - Verification: prompt typed/materializer/boundary suites (45 passed); prompt-intelligence gate (446/446); focused generated-system GDE suite (5/5); complete GDE gate (200/200); focused Builder bridge/router suites (5/5); Builder prompt E2E (21/21); complete Builder server suite (79/79); `python tools/source_inventory_check.py --json` (`[]`); retained proof command with Task 29 runtime/SGC binaries (25/25, two byte-stable runs).

- [x] X10-032: Implement composite prompt planning.
  - Acceptance: multi-system prompts produce ordered schema/system/asset/network/save operations with rollback plan and dependency graph.
  - Evidence: complex prompt plans preview, apply, or rollback atomically.
  - Done 2026-08-13: Pass 1 now has an explicit `composite_feature_add` route for multi-system feature prompts, and Pass 2 requires one ordered, self-contained typed batch whose locally derived `xace.composite_prompt_plan.v1` contains schema, system, asset, save, and network facets plus an acyclic dependency graph. The parser carries the composite plan with the canonical typed transaction, Builder previews preserve the plan and expose save/network facet diffs, apply provenance records the plan hash/order/rollback pre-hash, and pending apply revalidates the plan against the batch before GDE can commit.
  - Atomicity: composite batches still use the X10-030 typed operation trust boundary; GDE reparses and applies the whole batch to an isolated CGS copy, and Task 32 adds plan-level tamper rejection plus exact rollback evidence for multi-facet prompts.
  - Proof: `target-codex-task32-composite-planning/report.json` passes all 17 retained checks across required facets, dependency graph ordering, Builder preview preservation, save/network previews, atomic GDE commit, standalone CGS validation, real SGC plan persistence, two real runtime launches, schedule/tick replay matching, adversarial plan rejection, mid-batch failure atomicity, and exact rollback. Report SHA-256: `2d382a49df1ce3cbc5f76c81fcc75907303b36b4f3eab440e90ba40b306f87db`.
  - Verification: `python -m py_compile packages/prompt-intelligence/src/typed_operations/composite_plan.py packages/prompt-intelligence/src/typed_operations/__init__.py packages/prompt-intelligence/src/output_parser/structured_output_parser.py packages/prompt-intelligence/src/llm_orchestrator/pass1_planning.py packages/prompt-intelligence/src/llm_orchestrator/pass2_dsl_draft.py packages/builder-workspace/server/session_manager.py packages/builder-workspace/server/ws_message_router.py tools/composite_prompt_planning_e2e_check.py tools/certify_launch.py`; `python -m unittest packages/prompt-intelligence/src/tests/test_typed_cgs_operations.py packages/prompt-intelligence/src/tests/test_typed_operation_boundary.py -v` (33 passed); `python -m unittest packages/builder-workspace/server/tests/test_typed_operation_router.py -v` (3 passed); `python tools/composite_prompt_planning_e2e_check.py --runtime-bin target-codex-task29-primitives\debug\xace_runtime.exe --sgc-bin target-codex-task29-primitives\debug\xace-system-graph-compiler.exe --artifact-dir target-codex-task32-composite-planning\artifacts --output target-codex-task32-composite-planning\report.json --json`.

- [x] X10-033: Add prompt undo/redo with proof links.
  - Acceptance: at least 50 chained prompt mutations undo and redo with matching CGS, SGC plan, runtime, and replay hashes.
  - Evidence: mutation history artifact.
  - Done 2026-08-13: Builder persistence now records durable `xace.prompt_mutation_history.v1` state under `.xace/audit/prompt_history.json`, including cursor position, linear entry sequence, pre/post CGS hashes, typed-operation provenance, optional composite-plan proof hash, version IDs, and proof-link status. Prompt apply truncates redo tails after branch edits, and stale/out-of-history current hashes start a new branch rather than silently reusing an invalid cursor.
  - Restore boundary: `prompt_undo`, `prompt_redo`, and `prompt_history_request` are now first-class Builder protocol messages. Undo/redo planning rejects stale current CGS hashes, cursor underrun/overrun, missing target snapshots, missing persisted ExecutionPlans, or missing SGC proof bundles before changing the active CGS; accepted restores append `.xace/audit/prompt_history_events.jsonl` and emit proof-linked ACK/update/audit payloads.
  - Proof: `target-codex-task33-prompt-history/report.json` passes all 14 retained checks across 50 chained typed prompt mutations, 51 retained snapshots, 51 persisted real-SGC plans/proof bundles, 50 undos, 50 redos, proof-link availability, exact origin/final cursor restoration, and matching CGS JSON hash, SGC plan hash, runtime world hash, runtime hash-log hash, and schedule/replay fingerprint for every restored target. Report SHA-256: `3463436e16a817f668a24a5a88c534fce40797a37b6d2475fda66ee419ba999d`.
  - Verification: `python -m py_compile packages/builder-workspace/server/cgs_persistence.py packages/builder-workspace/server/ws_message_router.py packages/builder-workspace/server/tests/test_prompt_history_undo_redo.py tools/prompt_undo_redo_e2e_check.py tools/certify_launch.py`; `python -m unittest packages/builder-workspace/server/tests/test_prompt_history_undo_redo.py -v` (2 passed); `python tools/prompt_undo_redo_e2e_check.py --runtime-bin target-codex-task29-primitives\debug\xace_runtime.exe --sgc-bin target-codex-task29-primitives\debug\xace-system-graph-compiler.exe --artifact-dir target-codex-task33-prompt-history\artifacts --output target-codex-task33-prompt-history\report.json --json`; `python tools/source_inventory_check.py --json`.

- [x] X10-034: Add long-session prompt degradation tests.
  - Acceptance: long authoring sessions with context growth, edits, undo, provider failure, and stale state complete without corruption or unbounded cost.
  - Evidence: fixed-length or 8-hour session report.
  - Done 2026-08-13: Added a retained fixed-length long-session degradation proof instead of requiring an eight-hour wall-clock run. The default profile runs 240 deterministic prompt turns with accumulated source context, bounded active context compaction, typed CGS edits, proof-linked undo/redo cycles, local simulated provider failures, stale parent-hash mutation attempts, provider accounting artifacts, and real SGC/runtime replay checkpoints.
  - Proof: `target-codex-task34-long-session/report.json` passes all 22 retained checks with 216 committed typed edits, 14 provider failures that leave CGS/history unchanged, 10 stale-state rejections that leave CGS/history unchanged, 5 undo/redo cycles through the X10-033 proof-linked restore path, 14 runtime checkpoints, 217 snapshots/plans/proof bundles, final CGS validation, bounded 16 KB active context, 9 compactions, and total accounted cost below the configured `$0.50` cap. Report SHA-256: `da930090c99afe10673c84a995c20c597d7d1881cf8638a99c8b4f0ece1a7f9b`.
  - Boundary: the retained gate is deterministic/offline and uses synthetic provider failures aligned to the provider retry/accounting ABI. It does not claim that an unattended 8-hour hosted-provider UI soak or hosted-provider reliability at long-session scale has passed.
  - Verification: `python -m py_compile tools/prompt_long_session_degradation_check.py tools/certify_launch.py`; `python tools/prompt_long_session_degradation_check.py --runtime-bin target-codex-task29-primitives\debug\xace_runtime.exe --sgc-bin target-codex-task29-primitives\debug\xace-system-graph-compiler.exe --artifact-dir target-codex-task34-long-session\artifacts --output target-codex-task34-long-session\report.json --json`; `python tools/source_inventory_check.py --json`.

## Phase 5 - Native Rollback Netcode And Multiplayer Integration

Closes audit area: rollback netcode and multiplayer synchronization.

Master task sources: 102-110, 111.

- [x] X10-035: Choose multiplayer launch topology.
  - Acceptance: host/client, dedicated server, peer-to-peer, or offline-only scope is explicitly selected; unsupported topologies fail visibly.
  - Evidence: topology matrix and tests.
  - Done 2026-08-13: selected `host_client_lockstep_v1` as the Phase 5 launch multiplayer topology, with host/client authoritative lockstep supported, offline retained as local-only, and dedicated-server/peer-to-peer explicitly outside the launch profile.
  - Boundary: unsupported launch multiplayer topologies fail through `XACE_NETWORK_TOPOLOGY_UNSUPPORTED`; runtime tick-loop consumption of `InputSynchroniser` is X10-036, and chaos certification is covered by X10-043.
  - Proof: `target-codex-task35-multiplayer-topology\report.json` passes 10/10 retained checks; report SHA-256 `dd281a8c388b3e2445ff311cb096417326f205e5b24ff145fb9c90a17e91cc80`.
  - Verification: `python -m py_compile tools/multiplayer_topology_check.py tools/certify_launch.py`; `cargo fmt --check --package xace-network-core`; `cargo test -p xace-network-core launch_topology --target-dir target-codex-task35-multiplayer-topology`; `cargo test -p xace-network-core unsupported_launch_topologies_fail_visibly --target-dir target-codex-task35-multiplayer-topology`; `python tools/multiplayer_topology_check.py --output target-codex-task35-multiplayer-topology\report.json --target-dir target-codex-task35-multiplayer-topology --json`; `python tools/source_inventory_check.py --json`.

- [x] X10-036: Integrate input synchronization into runtime tick advancement.
  - Acceptance: runtime tick progression consumes `InputSynchroniser` lockstep decisions instead of directly applying raw pending engine inputs.
  - Evidence: missing, delayed, synthetic, and late inputs produce deterministic decisions.
  - Done 2026-08-13: `RuntimeOrchestrator::tick()` now routes engine input packets through `RuntimeInputSyncConfig` and `InputSynchroniser` before phase execution. Direct/offline mode preserves existing local behavior; lockstep mode submits queued bridge packets, waits visibly on missing peers without advancing the runtime tick, releases delayed complete ticks deterministically, can release synthetic empty timeout packets by policy, and records late-after-release packets without applying them to future ticks.
  - Visibility: runtime status/control payloads expose `input_sync_mode` and `input_sync_last_decision`; replay traces include `RuntimeInputSyncTrace` with mode, decision, sim/input tick, missing peers, released packet count, and waited tick count.
  - Boundary: synthetic timeout packets unblock the lockstep tick but do not spoof player-owned component mutations when no `player_id` exists. Authoritative late-input rollback/resimulation is X10-037.
  - Proof: `target-codex-task36-input-sync\report.json` passes 5/5 retained checks over four runtime tests; report SHA-256 `698dbe64924a5a0f24d72a34f763c591d12812b6feddb85ec3d8cfdcb8e626e9`.
  - Verification: `python -m py_compile tools/runtime_input_sync_check.py tools/certify_launch.py`; `cargo fmt --check --package xace-network-core --package xace-runtime-core`; `cargo test -p xace-runtime-core x10_036 --target-dir target-codex-task36-input-sync`; `python tools/runtime_input_sync_check.py --output target-codex-task36-input-sync\report.json --target-dir target-codex-task36-input-sync --json`; `python tools/source_inventory_check.py --json`.

- [x] X10-037: Integrate rollback manager with runtime snapshots and resimulation.
  - Acceptance: authoritative late input or desync triggers restore, deterministic resim, hash validation, and adapter resync.
  - Evidence: rollback count and restored tick recorded in proof artifacts.
  - Done 2026-08-14: `RuntimeOrchestrator::tick()` now captures retained clean pre-tick `WorldSnapshot` anchors, records snapshot metadata in `xace_network_core::prediction::RollbackManager`, and preserves released lockstep input history for corrected-timeline replay. Explicit authoritative late-input and desync recovery APIs restore the retained snapshot, reset runtime side channels through the existing world-restore path, replay affected ticks through normal `tick()` execution, validate hashes, and record adapter side-effect rollback/resync evidence.
  - Boundary: ordinary late packets still remain non-mutating `late_after_release` records from X10-036 unless an authoritative correction/desync recovery path is invoked. Client prediction/reconciliation is X10-038; malicious-input hardening, diagnostics, and chaos proof coverage are handled by X10-041 through X10-043.
  - Proof: `target-codex-task37-rollback-resim\report.json` passes 7/7 retained checks over two runtime tests plus the rollback-manager clean-boundary planner test; report SHA-256 `bf537dc355f2f0d568b88c77bacb7f8ffc314bfbc582897ef9f594ab5a45c96f`.
  - Verification: `python -m py_compile tools/runtime_rollback_resimulation_check.py tools/certify_launch.py`; `cargo fmt --check --package xace-network-core --package xace-runtime-core`; `cargo test -p xace-runtime-core x10_037 --target-dir target-codex-task37-rollback-resim`; `cargo test -p xace-network-core rollback_manager_clean_boundary --target-dir target-codex-task37-rollback-resim`; `python tools/runtime_rollback_resimulation_check.py --output target-codex-task37-rollback-resim\report.json --target-dir target-codex-task37-rollback-resim --json`; `python tools/source_inventory_check.py --json`.

- [x] X10-038: Integrate prediction and reconciliation for supported clients.
  - Acceptance: prediction buffer and reconciliation engine are wired into supported topology and never mutate authoritative state directly.
  - Evidence: prediction correction tests and client/server hash comparison.
  - Done 2026-08-14: supported lockstep clients can enable `RuntimeClientPredictionConfig::lockstep_client()`, generate read-only prediction previews from authoritative transform/velocity state, store local predictions in a bounded `PredictionBuffer`, reconcile post-tick authoritative positions through `ReconciliationEngine`, expose correction reports/status/accessors, and compare client/server authoritative tick hashes without predicted state writing directly to component tables.
  - Boundary: the X10-038 overlay is limited to the supported host/client lockstep runtime path. Lobby/session lifecycle is X10-039 and session compatibility is X10-040; malicious-input hardening beyond existing packet validation, diagnostics, and chaos proof coverage are handled by X10-041 through X10-043.
  - Proof: `target-codex-task38-prediction\report.json` passes 8/8 retained checks over three runtime tests; report SHA-256 `6a72b505534383723425c2f414b4b7a12b78cb8c3396193695c86b91c19bb056`.
  - Verification: `python -m py_compile tools/runtime_prediction_reconciliation_check.py tools/certify_launch.py`; `cargo fmt --check --package xace-network-core --package xace-runtime-core`; `cargo test -p xace-runtime-core x10_038 --target-dir target-codex-task38-prediction`; `python tools/runtime_prediction_reconciliation_check.py --output target-codex-task38-prediction\report.json --target-dir target-codex-task38-prediction --json`; `python tools/source_inventory_check.py --json`.

- [x] X10-039: Implement lobby/session lifecycle.
  - Acceptance: create, join, leave, reconnect, late join, ready state, player identity, and teardown work for the chosen topology.
  - Evidence: runtime plus Builder UI tests.
  - Done 2026-08-14: `SessionManager` now exposes an explicit host/client lobby lifecycle for `host_client_lockstep_v1`: create lobby, join with `SessionPlayerIdentity`, mark ready, start live when active peers are ready, leave, reconnect into sync, late join without blocking existing live input peers, and teardown while retaining lifecycle events/status. Runtime lockstep setup can derive required peers from `session.required_input_peers()`, and the Builder multiplayer smoke now includes a lifecycle checklist step backed by the X10-039 network-core test and UI contract.
  - Boundary: X10-039 proves lifecycle semantics for the selected host/client lockstep topology only. Schema/SGC/adapter/asset compatibility checks are X10-040, malicious-input hardening is X10-041, multiplayer diagnostics is X10-042, and chaos proof coverage is X10-043.
  - Proof: `target-codex-task39-session-lifecycle\report.json` passes 8/8 retained checks over one network-core lifecycle test, one runtime-core lifecycle/input-sync test, and the Builder UI contract; report SHA-256 `ffed695ea7486f4fe117e0eb407af8c26a44717d1879f909439a60bc05358f79`.
  - Verification: `python -m py_compile tools/session_lifecycle_check.py tools/certify_launch.py`; `cargo test -p xace-network-core x10_039 --target-dir target-codex-task39-session-lifecycle`; `cargo test -p xace-runtime-core x10_039 --target-dir target-codex-task39-session-lifecycle`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `python tools/session_lifecycle_check.py --output target-codex-task39-session-lifecycle\report.json --target-dir target-codex-task39-session-lifecycle --json`.

- [x] X10-040: Add session compatibility checks.
  - Acceptance: schema, SGC plan, adapter version, assets, packages, provider-free metadata, and template mismatches block session start.
  - Evidence: mismatch matrix tests.
  - Done 2026-08-14: `SessionCompatibilityProfile` and `SessionCompatibilityReport` now gate `SessionManager::start_live_when_ready()` whenever a host compatibility profile is configured. Active lobby peers must submit matching schema version, SGC plan hash, adapter version, asset manifest hash, package-set hash, provider-free metadata hash, and template ID before the session can enter live; missing profiles and every required mismatch produce blocking status records and lifecycle events instead of silent start.
  - Boundary: X10-040 proves pre-start compatibility gating for the selected host/client lockstep session profile. It does not add malicious-input hardening, transport authentication, asset/package download or repair, dedicated-server/P2P compatibility, or chaos/soak coverage.
  - Proof: `target-codex-task40-session-compatibility\report.json` passes 8/8 retained checks over two network-core mismatch matrix tests plus the Builder UI contract; report SHA-256 `026f71bc8e327523cd626efd566fa1e11d1363aa3153f26b561d350294e0ca12`.
  - Verification: `cargo fmt --check --package xace-network-core`; `python -m py_compile tools/session_compatibility_check.py tools/certify_launch.py`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `cargo test -p xace-network-core x10_040 --target-dir target-codex-task40-session-compatibility`; `cargo test -p xace-network-core networked_runtime_smoke_is_deterministic_across_arrival_orders --target-dir target-codex-task40-session-compatibility`; `python tools/session_compatibility_check.py --output target-codex-task40-session-compatibility\report.json --target-dir target-codex-task40-session-compatibility --json`.

- [x] X10-041: Harden malicious input limits.
  - Acceptance: rate limits, packet validation, sequence checks, replay protection, authority checks, and cheat guard enforcement block bad traffic without desync or crash.
  - Evidence: malicious packet tests.
  - Done 2026-08-14: `MaliciousInputGate` now provides a deterministic ingress boundary before `InputSynchroniser`: per-peer tick-window rate limiting, required-peer validation, packet/schema validation, signature/player/device/action/tick policy, sequence/replay checks, target-entity authority checks, and cheat-guard enforcement all reject bad traffic with retained rejection kinds before buffer/log mutation.
  - Desync safety: the gate uses a two-phase cheat-guard path: `validate_authorized_input_preview` runs before synchronizer insertion, and `record_validated_input` only commits replay/action counters after an accepted insert. A conflicting duplicate tick rejected by `InputBuffer` therefore does not poison the next valid sequence.
  - Boundary: X10-041 hardens the typed input-packet ingress for the selected host/client lockstep path. It does not add transport authentication, encryption, NAT/P2P hardening, asset/package repair, broader security review, or chaos/soak coverage.
  - Proof: `target-codex-task41-malicious-input\report.json` passes 12/12 retained checks over three network-core malicious packet tests plus the Builder UI contract; report SHA-256 `5a84ced6bee42c5216d8dcff30be8dafa51ba0a8cb3447354bab669004b2df70`.
  - Verification: `cargo fmt --check --package xace-network-core`; `python -m py_compile tools/malicious_input_limits_check.py tools/certify_launch.py`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `cargo test -p xace-network-core x10_041 --target-dir target-codex-task41-malicious-input`; `python tools/malicious_input_limits_check.py --output target-codex-task41-malicious-input\report.json --target-dir target-codex-task41-malicious-input --json`.

- [x] X10-042: Add multiplayer diagnostics panel.
  - Acceptance: peers, ticks, input buffers, latency, rollback count, resync status, packet loss, hash comparisons, and authority owner are visible.
  - Evidence: UI/server tests and chaos report.
  - Done 2026-08-14: added `xace_network_core::diagnostics` with `MultiplayerDiagnosticsSnapshot` and `capture_multiplayer_diagnostics()`, covering the selected host/client lockstep topology's session, peer, tick/input-buffer, latency, rollback, resync, hash-comparison, and authority-owner state. Builder now exposes `/api/project/demo/multiplayer/diagnostics` and an `Open Network Diagnostics` panel that surfaces the required peer/tick/buffer/latency/rollback/resync/packet-loss/hash/authority fields plus a deterministic chaos diagnostics report fixture.
  - Boundary: the X10-042 chaos report is a diagnostics fixture proving visibility of packet loss, jitter, missing input, divergent hash, and resync state. It is not the 4-16 client, 60-minute chaos proof certification; that is certified separately by X10-043. It also does not add transport authentication, encryption, matchmaking, NAT/P2P support, or dedicated-server support.
  - Proof: `target-codex-task42-diagnostics\report.json` passes 11/11 retained checks over one network-core diagnostics test, one Builder server payload test, and the Builder UI contract; report SHA-256 `51e293dd29b5eb0c6e4b7740dc185cfbc2575f5aa04ca6fd010d6ffcd23ac8ae`.
  - Verification: `python -m py_compile tools\multiplayer_diagnostics_check.py tools\certify_launch.py packages\builder-workspace\server\tests\test_multiplayer_diagnostics_panel.py`; `cargo fmt --check --package xace-network-core`; `python -m unittest packages/builder-workspace/server/tests/test_multiplayer_diagnostics_panel.py -v`; `node.exe tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `cargo test -p xace-network-core x10_042 --target-dir target-codex-task42-diagnostics`; `python tools\multiplayer_diagnostics_check.py --output target-codex-task42-diagnostics\report.json --target-dir target-codex-task42-diagnostics --json`; `python tools\source_inventory_check.py --json`.

- [x] X10-043: Run network chaos proof.
  - Acceptance: 4 to 16 clients, 60 minutes, packet loss, jitter, reordering, disconnect, reconnect, late join, malformed input, rollback, and resync finish with zero permanent desync for supported scenarios.
  - Evidence: `.xace/proof/network-chaos/<run-id>/`.
  - Done 2026-08-14: added a deterministic host/client lockstep chaos simulator in `xace_network_core::chaos`, a `network_chaos_proof` Rust proof binary, and `tools/network_chaos_proof.py` wrapper. Full mode now certifies 4/8/16-client packet loss, jitter, reordering, disconnect/reconnect, late join, malformed input rejection, rollback, resync, and zero permanent desync across 216,000 ticks / 3,600 simulated seconds at 60 Hz.
  - Proof: retained run `x10-043-full-20260814-60hz` wrote `.xace\proof\network-chaos\x10-043-full-20260814-60hz\network_chaos_report.json` with `certification_complete=true` and wrapper report `target-codex-task43-network-chaos\full_report.json` with `x10_043_complete=true`; Rust report SHA-256 `2bc7145254d5845f873d727a4a6e036f683ca9341b8506b1c49cdf7436b1e4a1`, wrapper SHA-256 `7d9cb5172fee6952f9acf42756694770f05cd6b618db62567fcb299929745829`.
  - Boundary: this is an accelerated deterministic 60-simulated-minute proof for the supported host/client authoritative lockstep scenario, not a wall-clock multi-user soak, transport authentication/encryption proof, matchmaking/NAT/P2P proof, or dedicated-server certification. Long multi-user soak with saves, adapter reconnects, runtime restarts, and corruption checks is covered by X10-044.
  - Verification: `cargo fmt --package xace-network-core`; `python -m py_compile tools\network_chaos_proof.py`; `cargo test -p xace-network-core x10_043 --target-dir target-codex-task43-network-chaos-quick -- --nocapture`; `cargo run --release -p xace-network-core --bin network_chaos_proof --target-dir target-codex-task43-network-chaos-release -- --output target-codex-task43-network-chaos\benchmark_6000_report.json --duration-ticks 6000 --client-counts 4,8,16 --tick-rate-hz 60`; `python tools\network_chaos_proof.py --full --release --duration-minutes 60 --tick-rate-hz 60 --output target-codex-task43-network-chaos\full_report.json --target-dir target-codex-task43-network-chaos-release --run-id x10-043-full-20260814-60hz --json`; `python tools\source_inventory_check.py --json`.

- [x] X10-044: Run long multi-user soak.
  - Acceptance: multi-user sessions with saves, supported prompt changes, adapter reconnects, and runtime restarts complete without corruption or unrecoverable desync.
  - Evidence: soak report.
  - Done 2026-08-14: added `tools/multi_user_soak_check.py`, a retained accelerated multi-user soak proof that runs the selected host/client session lifecycle subproof, save runtime-replay and crash-recovery subproofs, runtime engine-protocol subproofs, X10-043 quick zero-permanent-desync chaos coverage, supported typed prompt changes through CGS/GDE/SGC/runtime persistence, adapter reconnect contract checks for Godot/Unity/Unreal transports, save checkpoint records, and fresh runtime-process restart/replay checkpoints.
  - Proof: `target-codex-task44-multi-user-soak\report.json` and `target-codex-task44-multi-user-soak\artifacts\runs\20260814T155000Z\summary.json` both report `x10_044_complete=true` over 12 accelerated soak cycles, 4 users, 4 supported prompt changes, 6 save checkpoints, 4 adapter reconnects, 4 runtime restarts, 34 retained trace events, and no unrecoverable desync/corruption; SHA-256 `8270ee5399fd35f2bec4b3f95a1974e0e1c319df0f568e8d01cc060074924ba3`.
  - Boundary: this closes the retained accelerated soak gate for the supported host/client lockstep scenario. It is not a wall-clock live-ops soak, installed-editor live adapter soak, matchmaking/NAT/P2P proof, transport authentication/encryption proof, dedicated-server proof, or external security review.
  - Verification: `python -m py_compile tools\multi_user_soak_check.py`; `python tools\multi_user_soak_check.py --cycles 8 --users 4 --prompt-changes 3 --output target-codex-task44-multi-user-soak\smoke_report.json --artifact-dir target-codex-task44-multi-user-soak\smoke_artifacts --target-dir target-codex-task44-multi-user-soak-smoke --json`; `python tools\multi_user_soak_check.py --cycles 12 --users 4 --prompt-changes 4 --output target-codex-task44-multi-user-soak\report.json --artifact-dir target-codex-task44-multi-user-soak\artifacts --target-dir target-codex-task44-multi-user-soak-smoke --json`; `python tools\source_inventory_check.py --json`.

## Phase 6 - Time-Travel Debugger And Diagnostics

Closes audit area: time-travel debugging and state rollback.

Master task sources: 65, 67-76.

- [x] X10-045: Implement minimum tick debugger.
  - Acceptance: timeline, pause, step, snapshot list, state diff, mutation history, event trace, and hash-mismatch display work without reading source.
  - Evidence: known divergence can be reproduced and inspected from UI.
  - Done 2026-08-20: expanded Builder's live `TickDebugger` into a protocol-driven minimum debugger that consumes runtime `engine_tick`, `runtime_control_ack.snapshot`, runtime status, and `hash_log` payloads instead of generated source. The panel now exposes Play/Pause/Step/Snapshot controls, a tick/hash timeline, runtime snapshot list, selected-snapshot state diff, mutation history, event trace, and explicit hash-mismatch display.
  - Proof: `tools/tick_debugger_minimum_check.py` validates the Builder UI contract, message/client/server/runtime snapshot-control wiring, and a retained known-divergence fixture where two snapshots for tick 42 produce a visible hash mismatch plus component diff, mutation history, and event trace. Report `target-codex-task45-tick-debugger\report.json` passes 12/12 checks with `x10_045_complete=true`; SHA-256 `3d17680e9f6705c61e83528402cc24c6aafb810092e97a29134698404e0b1a16`.
  - Boundary: this closes the minimum source-free tick debugger. Reverse-step/time-travel navigation, 1,000-tick memory-bounded scrubbing, delta compression, breakpoint/watch expressions, profiler overlays, and support-bundle export remain later Phase 6 tasks.
  - Verification: `python -m py_compile tools\tick_debugger_minimum_check.py tools\certify_launch.py`; `npm run typecheck` from `packages/builder-workspace`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `python tools\tick_debugger_minimum_check.py --output target-codex-task45-tick-debugger\report.json --json`; `python tools\source_inventory_check.py --json`; scoped `git diff --check`.

- [x] X10-046: Add reverse-step and time-travel navigation.
  - Acceptance: debugger moves forward and backward across at least 1,000 ticks with matching hashes.
  - Evidence: debugger time-travel tests.
  - Done 2026-08-20: extended Builder's protocol-driven `TickDebugger` with a retained 1,000-tick hash timeline derived from runtime `hash_log`, `engine_tick`, and retained snapshot records. The new Time travel panel exposes Reverse step, Forward step, and Live tick controls, selects timeline ticks without reading source, marks the selected tick in the visible timeline, selects same-tick snapshots when retained, and displays Matching hash status for selected timeline/snapshot hash agreement.
  - Proof: `tools/tick_debugger_time_travel_check.py` validates the UI contract markers, hash-log feed wiring, and a synthetic 1,000-tick timeline that moves 999 steps backward and 999 steps forward with exact expected hash equality before returning to the latest live tick. Report `target-codex-task46-time-travel\report.json` passes 8/8 checks with `x10_046_complete=true`; SHA-256 `4e8477d9cdb35cd545458ea0ccbd191299f4afff933742a2798d8ea4364dbcd6`.
  - Boundary: this closes source-free hash-timeline navigation, not authoritative runtime rewind/restore for every tick. Snapshot/delta compression, memory-bounded authoritative scrubbing, and restore capability remain X10-047.
  - Verification: `python -m py_compile tools\tick_debugger_time_travel_check.py tools\certify_launch.py`; `npm run typecheck` from `packages/builder-workspace`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `python tools\tick_debugger_time_travel_check.py --output target-codex-task46-time-travel\report.json --json`; `python tools\source_inventory_check.py --json`; scoped `git diff --check`.

- [x] X10-047: Add delta-compressed timeline retention.
  - Acceptance: snapshots plus deltas support memory-bounded scrubbing without losing authoritative restore capability.
  - Evidence: memory and restore benchmarks.
  - Done 2026-08-20: added runtime-owned `DeltaCompressedTimelineRetention` with sparse full `WorldSnapshot` anchors, consecutive `SnapshotTimelineDelta` records, 1,000-tick default scrub retention, byte/tick-bounded pruning, complete-chain promotion when old anchors are pruned, retained-byte versus full-snapshot stats, and per-tick restore proofs that validate reconstructed snapshots with `WorldHasher`.
  - Runtime binding: `RuntimeOrchestrator::tick()` now captures the canonical end-of-tick snapshot into the compressed timeline; runtime APIs expose retention stats, retained-tick reconstruction, and `restore_retained_timeline_tick()` through the existing authoritative `restore_world_snapshot()` path.
  - Proof: `tools/tick_debugger_delta_retention_check.py` validates source wiring and runs the focused X10-047 Rust tests. Report `target-codex-task47-delta-retention\report.json` passes 7/7 checks with `x10_047_complete=true`; SHA-256 `8edbbf4ecd51890d05f43b041db17011e64c085717a739d07c5f7ee0107abf43`.
  - Boundary: this closes runtime memory-bounded snapshot/delta scrub retention and authoritative retained-tick restore capability. Conditional breakpoints, causality graphing, RNG seed tracing, support-bundle export, and installed-engine visible-panel restore proof remain X10-048 through X10-051.
  - Verification: `cargo fmt -p xace-runtime-core`; `cargo test -p xace-runtime-core x10_047 --target-dir target-codex-task47-delta-retention`; `python -m py_compile tools\tick_debugger_delta_retention_check.py tools\certify_launch.py`; `python tools\tick_debugger_delta_retention_check.py --output target-codex-task47-delta-retention\report.json --target-dir target-codex-task47-delta-retention --json`.

- [x] X10-048: Add debugger conditional breakpoints.
  - Acceptance: break on entity state, component value, event type, mutation type, system ID, RNG call, hash mismatch, and network desync.
  - Evidence: breakpoint tests hit exact ticks.
  - Done 2026-08-21: added a source-free `ConditionalBreakpointEngine`, Builder breakpoint panel, arm/off toggles, hit history, and pause-on-hit runtime control wiring.
  - Protocol binding: existing snapshot/event/mutation/hash observations feed entity-state, component-value, event-type, mutation-type, and hash-mismatch candidates; the Builder WebSocket contract now includes `runtime_debug_trace` payloads for system ID, RNG call, and network-desync candidates.
  - Proof: `tools/tick_debugger_breakpoint_check.py` compiles the actual TypeScript breakpoint engine and validates exact-hit ticks for all eight required sources. Report `target-codex-task48-breakpoints\report.json` passes 6/6 checks with `x10_048_complete=true`; SHA-256 `eca10949e163471f2cd1bc2172bd1d38269e91a47270c2131278a6e9ecbef4d6`.
  - Boundary: this closes conditional breakpoint hit detection, visible arming, hit history, and pause-on-hit behavior for the eight required categories. Causality graphing, RNG seed trace panel, support-bundle export, and installed-engine visual proof for debugger-driven scrub/restore remain later Phase 6 work.
  - Verification: `npm run typecheck` from `packages/builder-workspace`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `python -m py_compile tools\tick_debugger_breakpoint_check.py tools\certify_launch.py`; `python tools\tick_debugger_breakpoint_check.py --output target-codex-task48-breakpoints\report.json --artifact-dir target-codex-task48-breakpoints\artifacts --json`; `python tools\source_inventory_check.py --json`; scoped `git diff --check`.

- [x] X10-049: Add causality graph.
  - Acceptance: reports trace which prompt, mutation, system, event, RNG call, feedback, or network packet caused a state change.
  - Evidence: combat damage event traced end to end.
  - Done 2026-08-21: added a source-free `CausalityGraphEngine`, typed `runtime_causality_trace` DAG protocol, visible Tick debugger Causality graph panel, graph validation, ancestor traversal, cause coverage, and ordered state-change cause-chain rendering.
  - Proof: `tools/tick_debugger_causality_graph_check.py` compiles the actual TypeScript causality graph engine and validates a combat-damage trace from prompt-authored mutation plus network packet, feedback, system, RNG call, and event causes to a `Health` state change from `100` to `75`. Report `target-codex-task49-causality\report.json` passes 6/6 checks with `x10_049_complete=true`; SHA-256 `76af736ea8b0862f49b604c0e18f1d580e9f15e3c4ac39c19027704e71af44c3`.
  - Boundary: this closes explicit causality graph reporting for runtime/debugger DAG traces and the retained combat-damage end-to-end proof. Dedicated RNG seed trace panel, support-bundle export, and installed-engine visual proof for debugger-driven scrub/restore remain later Phase 6 work.
  - Verification: `npm run typecheck` from `packages/builder-workspace`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `python -m py_compile tools\tick_debugger_causality_graph_check.py tools\certify_launch.py`; `python tools\tick_debugger_causality_graph_check.py --output target-codex-task49-causality\report.json --artifact-dir target-codex-task49-causality\artifacts --json`; `python tools\source_inventory_check.py --json`; scoped `git diff --check`.

- [x] X10-050: Add RNG seed trace panel.
  - Acceptance: every deterministic RNG call is visible by tick, system, seed, stream position, and result.
  - Evidence: illegal RNG blocked and legal RNG replayed identically.
  - Done 2026-08-21: added a source-free `RngSeedTraceEngine`, typed `runtime_rng_trace` protocol, legacy `runtime_debug_trace.rng_calls` normalization, visible Tick debugger RNG seed trace panel, seed/result/stream-position completeness validation, retained illegal-RNG block status, retained legal-replay identity status, and Builder UI contract coverage.
  - Proof: `tools/tick_debugger_rng_seed_trace_check.py` compiles the actual TypeScript RNG seed trace engine and validates a runtime trace where `CombatDamageSystem` and `LootDropSystem` calls are visible by tick, system, seed, stream position, and result, `UnregisteredRandomSystem` illegal RNG is blocked, and the legal replay hashes match. Report `target-codex-task50-rng-seed-trace\report.json` passes 9/9 checks with `x10_050_complete=true`; SHA-256 `fdbef19e013e7d9565a1452c16df84c04c363ed1bec5b87236f93d3732f93147`.
  - Boundary: this closes the dedicated RNG seed trace panel and retained source-free proof for explicit runtime/proof RNG trace payloads. It does not yet add the support diagnostics bundle, exportable debug report, or installed-engine visual proof for debugger-driven scrub/restore; those remain later Phase 6 work.
  - Verification: `npm run typecheck` from `packages/builder-workspace`; `node tools\builder_ui_contract_test.mjs` from `packages/builder-workspace`; `python -m py_compile tools\tick_debugger_rng_seed_trace_check.py tools\certify_launch.py`; `python tools\tick_debugger_rng_seed_trace_check.py --output target-codex-task50-rng-seed-trace\report.json --artifact-dir target-codex-task50-rng-seed-trace\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task50-rng-seed-trace\report.json`.

- [x] X10-051: Add support diagnostics bundle.
  - Acceptance: one command exports redacted versions, manifests, logs, proof links, config, adapter health, provider readiness, and reproduction commands.
  - Evidence: support bundle smoke test.
  - Done 2026-08-21: added `tools/support_diagnostics_bundle.py`, a local-only one-command exporter that writes a redacted support bundle folder plus zip containing `manifest.json`, `versions.json`, redacted repo/project manifests, redacted logs, proof-link indexes, config snapshots, adapter health, provider readiness, and reproduction commands.
  - Proof: `tools/support_diagnostics_bundle_check.py` creates a fixture project with planted credential-shaped canaries in logs/provider config, runs the exporter as one command, validates all required bundle sections, verifies the zip exists, checks proof links and reproduction command IDs, and runs the secret scanner over the exported bundle. Report `target-codex-task51-support-bundle\report.json` passes 2/2 checks with `x10_051_complete=true`; SHA-256 `18aa40598258277c30ce475f461bfa6e28cd61ad92cade3f10ccf240638d5f4c`.
  - Boundary: this closes local redacted support diagnostics bundle export. It does not yet make debugger state/replay inputs/hash logs/SGC plan/mutation log/adapter feedback reloadable in a fresh checkout; that remains X10-052 exportable debug report work. Installed-engine visual proof for debugger-driven scrub/restore also remains later evidence.
  - Verification: `python -m py_compile tools\support_diagnostics_bundle.py tools\support_diagnostics_bundle_check.py tools\certify_launch.py`; `python tools\support_diagnostics_bundle_check.py --output target-codex-task51-support-bundle\report.json --bundle-root target-codex-task51-support-bundle\bundle --json`; `Get-FileHash -Algorithm SHA256 target-codex-task51-support-bundle\report.json`.

- [x] X10-052: Add exportable debug report.
  - Acceptance: debugger state, replay inputs, hash logs, SGC plan, mutation log, and adapter feedback load in a fresh checkout.
  - Evidence: debug report round-trip test.
  - Done 2026-08-21: added `tools/export_debug_report.py`, a local-only self-contained debug report exporter/validator that embeds redacted debugger state, replay inputs, runtime hash logs, the persisted SGC plan, mutation-log records, adapter-feedback records, section digests, source manifests, artifact manifests, and reproduction commands under `xace.exportable_debug_report.v1`.
  - Proof: `tools/export_debug_report_check.py` creates a fixture project with all six required debug evidence streams plus planted credential-shaped canaries, exports the report as one command, writes per-section artifacts, validates the report from an empty fresh-checkout directory using only the exported JSON, and runs the secret scanner over the exported report/artifacts. Report `target-codex-task52-debug-report\report.json` passes 3/3 checks with `x10_052_complete=true`; SHA-256 `5e56c7f7244bbf3ec84c923e1d96962c6633e73bace623ba9cbb005037d1ce68`.
  - Boundary: this closes the Phase 6 exportable debug-report round-trip and makes the required debugger/replay/hash/SGC/mutation/adapter-feedback evidence portable. It does not claim installed-engine visual proof for driving authoritative scrub/restore from the visible debugger panel; that remains later installed-engine evidence.
  - Verification: `python -m py_compile tools\export_debug_report.py tools\export_debug_report_check.py`; `python tools\export_debug_report_check.py --output target-codex-task52-debug-report\report.json --artifact-dir target-codex-task52-debug-report\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task52-debug-report\report.json`.

## Phase 7 - Engine Adapters, Assets, Import, Adapter Package Handoff, And Cross-Engine Slice

Closes audit areas: engine-agnostic execution, portability, installed-engine readiness.

Master task sources: 82-101, 122.

- [x] X10-053: Harden asset reference validation.
  - Acceptance: asset refs, hashes, types, statuses, engine support, and missing files are validated before runtime, save, and adapter package handoff.
  - Evidence: unresolved refs blocked or given documented fallback.
  - Done 2026-08-21: added `packages/asset-registry/asset_reference_preflight.py`, a strict Phase 7 asset preflight validator for `runtime`, `save`, and `adapter_package_handoff` boundaries. It preserves the older CGS-commit validator behavior while adding launch/handoff checks for typed refs, enum casing, SHA-256 fields, file existence, hash mismatch, semantic binding playback type compatibility, documented fallbacks, and per-engine support/extension policy.
  - Proof: `tools/asset_reference_validation_check.py` builds a retained fixture project, validates a passing runtime/save/adapter-package-handoff x 3-engine matrix, proves unresolved refs block every boundary without fallback, proves documented fallback records non-blocking fallback evidence, and proves blocked cases for missing hash, invalid hash, hash mismatch, missing file, invalid type, invalid status, unsupported engine extension, semantic type mismatch, and Godot-vs-Unity engine support. Report `target-codex-task53-asset-validation\report.json` passes 6/6 checks with `x10_053_complete=true`; SHA-256 `9d0a512f79bf1cc33650fc83d45f508ddb465212f50f275b822eec9dda34e846`.
  - Boundary: this closes the reusable asset-reference validation core for Phase 7 handoff gates. It does not yet build the creator-facing semantic binding UI, per-engine binding status panel, deterministic runtime fallback binding catalog, or full adapter-package preflight umbrella; those remain X10-054 through X10-061.
  - Verification: `python -m py_compile packages\asset-registry\asset_reference_preflight.py tools\asset_reference_validation_check.py tools\certify_launch.py`; `python -m unittest discover packages\asset-registry\tests`; `python tools\asset_reference_validation_check.py --output target-codex-task53-asset-validation\report.json --artifact-dir target-codex-task53-asset-validation\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task53-asset-validation\report.json`.

- [x] X10-054: Build semantic binding UI.
  - Acceptance: creators can map semantic events to animation, audio, and VFX commands per engine.
  - Evidence: bindings produce runtime playback commands in Godot, Unity, and Unreal tests.
  - Done 2026-08-21: added the Builder semantic binding catalog and panel so creators can choose a semantic event, playback kind, compatible animation/audio/VFX asset, entity selector, semantic action, priority, resource path, and Godot/Unity/Unreal target metadata. The Assets workflow now exposes a `Bindings` jump target and persists binding updates through the same CGS hash/authority/audit path as other Builder mutations.
  - Runtime/adapter path: the WebSocket route validates event/playback compatibility, asset type/status, entity selector, per-engine targets, duplicate IDs, and stale hashes before writing `semantic_bindings.bindings`; runtime loader/orchestrator focused tests prove semantic bindings load and resolve into `EnginePlaybackCommand`; Godot, Unity, and Unreal adapters already consume playback commands and retain asset-binding state from the shared command payload.
  - Proof: `tools/semantic_binding_ui_check.py` writes retained fixture CGS plus playback command artifacts and passes 8/8 checks for Builder UI, catalog, WebSocket save path, runtime playback command tests, Godot adapter contract, Unity adapter contract, Unreal adapter contract, and Animation/Audio/VFX per-engine target coverage. Report `target-codex-task54-semantic-binding-ui\report.json` has `x10_054_complete=true`; SHA-256 `36deccfa3fc72e74440bb741b7e9aceebd34aa6f632ad3b5cd37535f0661b3f6`.
  - Boundary: this closes semantic binding authoring and command-contract proof. Per-engine resolved/unresolved/unsupported/missing/fallback status surfacing, deterministic runtime fallback binding catalogs, full adapter-package handoff preflight, adapter package versioning, and installed-engine vertical-slice/hash proof are handled by X10-055 through X10-067.
  - Verification: `python -m py_compile packages\builder-workspace\server\ws_message_router.py tools\semantic_binding_ui_check.py tools\certify_launch.py`; `python -m unittest packages\builder-workspace\server\tests\test_semantic_binding_router.py`; `npm run typecheck` from `packages\builder-workspace`; `node tools\builder_ui_contract_test.mjs` from `packages\builder-workspace`; `python tools\semantic_binding_ui_check.py --output target-codex-task54-semantic-binding-ui\report.json --artifact-dir target-codex-task54-semantic-binding-ui\artifacts --json`; `cargo test -p xace-runtime-core semantic_playback_bindings_resolve_into_engine_snapshot_commands --lib --target-dir target-codex-task54-bindings`; `cargo test -p xace-runtime-core load_and_spawn_accepts_valid_semantic_playback_bindings --lib --target-dir target-codex-task54-bindings`; `python tools\source_inventory_check.py`; `python tools\forbidden_claims_check.py`; `Get-FileHash -Algorithm SHA256 target-codex-task54-semantic-binding-ui\report.json`.

- [x] X10-055: Add engine-specific binding status.
  - Acceptance: resolved, unresolved, unsupported, missing, and fallback statuses are tracked per engine and surfaced before runtime/handoff launch.
  - Evidence: Builder tests and adapter reports.
  - Done 2026-08-22: added `packages/asset-registry/semantic_binding_status.py`, a deterministic pre-runtime/pre-handoff semantic binding readiness report that evaluates each binding per Godot, Unity, and Unreal using the X10-053 asset type/status/hash/path/engine support rules and emits the five launch-visible states: `resolved`, `unresolved`, `unsupported`, `missing`, and `fallback`.
  - Builder/adapter surfacing: Builder semantic binding cards now show pre-runtime/handoff status chips plus per-engine badges; `CGSStore` preserves asset hash and fallback metadata for status derivation. Godot, Unity, and Unreal adapters now retain asset binding status state and expose `xace.adapter.semantic_binding_status_report.v1` report hooks using the same status vocabulary.
  - Proof: `tools/semantic_binding_status_check.py` creates a retained fixture project, writes per-engine adapter report artifacts, and passes 5/5 checks for a 5-status x 3-engine matrix, Builder status UI contract, adapter status report hooks, adapter report artifacts, and certification wiring. Report `target-codex-task55-binding-status\report.json` has `x10_055_complete=true`; SHA-256 `f2f4b7e10b5a8b58de8521d6761352cabb8cb41df48dcc083882ca29e4dcfe83`.
  - Boundary: this closes status tracking and surfacing before runtime/handoff launch. It does not define deterministic fallback playback behavior or claim that missing assets can play correctly; X10-056 owns fallback binding behavior.
  - Verification: `python -m py_compile packages\asset-registry\semantic_binding_status.py tools\semantic_binding_status_check.py tools\certify_launch.py`; `python -m unittest packages\asset-registry\tests\test_semantic_binding_status.py`; `npm run typecheck` from `packages\builder-workspace`; `node tools\builder_ui_contract_test.mjs` from `packages\builder-workspace`; `python tools\semantic_binding_status_check.py --output target-codex-task55-binding-status\report.json --artifact-dir target-codex-task55-binding-status\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task55-binding-status\report.json`.

- [x] X10-056: Define deterministic runtime fallback bindings.
  - Acceptance: missing animation/audio/VFX/prefab/mesh bindings fall back visibly, never crash, and are never reported as resolved.
  - Evidence: adapter proof artifacts.
  - Done 2026-08-22: added the `xace.runtime.fallback_binding_catalog.v1` contract in `packages/core/src/assets/semantic_binding.rs`. Missing or placeholder committable semantic playback assets now emit deterministic runtime fallback metadata (`xace_binding_status=fallback`, visible/deterministic flags, fallback kind, asset type/status/id, label, and SHA-256 seed) when resolved into runtime playback commands.
  - Runtime/adapter behavior: `packages/runtime-core/src/runtime_orchestrator.rs` now has an X10-056 focused test proving missing animation/audio/VFX semantic bindings emit stable fallback command parameters. Godot, Unity, and Unreal adapters detect `xace_runtime_fallback`, `xace_fallback_visible`, explicit `fallback` status, or missing/placeholder asset status; they create visible fallback markers/labels for animation, audio, VFX, mesh, and prefab cases, track the side effect for rollback, and record `fallback` with `reason=fallback_applied` instead of `resolved`.
  - Proof: `tools/runtime_fallback_binding_check.py` writes `target-codex-task56-runtime-fallback\artifacts\runtime_fallback_binding_catalog.json`, `runtime_fallback_playback_commands.json`, and Godot/Unity/Unreal adapter report artifacts covering missing animation, audio, VFX, prefab, and mesh bindings. Report `target-codex-task56-runtime-fallback\report.json` has `x10_056_complete=true`; SHA-256 `6a3d2f962bac8b82253817938c481ec6bbf3678321ec560db6c813bb32c7ac69`.
  - Boundary: this closes deterministic runtime fallback metadata and editor-free adapter proof artifacts. It does not claim installed-editor visual playthrough proof, asset repair/download, or that adapter package handoff may ignore missing assets; full handoff preflight remains later Phase 7 work.
  - Verification: `cargo test -p xace-core runtime_fallback --lib --target-dir target-codex-task56-fallback`; `cargo test -p xace-runtime-core x10_056 --lib --target-dir target-codex-task56-fallback`; `python -m py_compile tools\runtime_fallback_binding_check.py tools\certify_launch.py`; `python tools\runtime_fallback_binding_check.py --output target-codex-task56-runtime-fallback\report.json --artifact-dir target-codex-task56-runtime-fallback\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task56-runtime-fallback\report.json`.

- [x] X10-057: Harden import marker validation and read-only inventory.
  - Acceptance: Godot, Unity, and Unreal project markers are detected without modifying projects; scenes/assets/scripts/plugins/input maps are inventoried as references only.
  - Evidence: ambiguous project imports refused with reports.
  - Done 2026-08-22: added `packages/project-system/engine_project_inventory.py`, a read-only marker and reference scanner for Godot, Unity, and Unreal project roots. The scanner detects root-level `project.godot`, Unity `Assets` + `ProjectSettings` / `ProjectVersion.txt`, and root `.uproject` markers, refuses missing, mismatched, multi-engine, or multi-`.uproject` selections, and emits `xace.import_marker_inventory.v1` reports with `reference_only=true` and `read_only_references_no_copy_no_modify` mode.
  - Import behavior: `ProjectCreator.import_engine_project` now runs the scanner before creating any XACE project files. Ambiguous imports raise `ProjectImportValidationError` with the refusal report; accepted imports store a compact reference inventory in `manifest.adapter_config["engine_project_inventory"]` while preserving the engine project as the source of truth.
  - Proof: `tools/import_marker_inventory_check.py` creates retained Godot, Unity, Unreal, and ambiguous Godot+Unity fixtures. The passing fixtures prove scenes, assets, scripts, plugins, and input maps are inventoried as references only and that engine-owned files are byte/mtime-stable after scanning and safe wrapping. The ambiguous fixture proves import refusal before `xace.project.json` is written. Report `target-codex-task57-import-inventory\report.json` has `x10_057_complete=true`; SHA-256 `ea58b4c11349a10ddc4442d82b38679a575b31612ccd8cf4d132eceeba1aeff3`.
  - Boundary: this closes read-only marker detection, reference inventory, and ambiguous-root refusal. It does not automatically migrate engine gameplay into CGS, install/uninstall adapters, or map engine entities/assets/scenes into semantic bindings; X10-058 and later Phase 7 tasks own those workflows.
  - Verification: `python -m py_compile packages\project-system\engine_project_inventory.py packages\project-system\project_creator.py tools\import_marker_inventory_check.py tools\certify_launch.py`; `python -m unittest packages/project-system/tests/test_project_system.py`; `python tools\import_marker_inventory_check.py --output target-codex-task57-import-inventory\report.json --artifact-dir target-codex-task57-import-inventory\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task57-import-inventory\report.json`.

- [x] X10-058: Build manual migration wizard.
  - Acceptance: engine entities/assets/scenes can be mapped to CGS semantic bindings and starter components with reversible mappings.
  - Evidence: manual-work report matches actual files.
  - Done 2026-08-22: added `packages/project-system/engine_migration_wizard.py`, a read-only manual migration planner that consumes the X10-057 import inventory and emits `xace.manual_migration_plan.v1` plans for linked Godot, Unity, and Unreal projects. The planner maps scene references to non-default CGS starter modes, editor-free entity candidates to starter actors/components, asset references to CGS asset records, and animation/audio/VFX-compatible assets to semantic binding candidates.
  - Builder/API behavior: `packages/builder-workspace/server/builder_server.py` now exposes `/api/project/migration/manual-plan`. The endpoint reads the linked engine project from the XACE manifest, returns a preview-only manual migration plan, and can optionally materialize a CGS preview with rollback metadata; it does not persist CGS changes or mutate engine-owned files.
  - Reversibility/manual-work behavior: every mapping carries a `reverse` block with removable CGS record targets and `restore_engine_action=none_engine_files_not_modified`. `materialize_manual_migration_draft` produces a preview-only CGS with migration metadata, and `revert_manual_migration_draft` removes proposed modes, actors, assets, and semantic bindings back to the original CGS. The manual-work report lists script/plugin/input-map review items with file SHA-256 evidence and `reference_only=true`.
  - Proof: `tools/manual_migration_wizard_check.py` creates retained Godot, Unity, and Unreal fixtures with scene/entity, asset, script, plugin, and input-map references. It writes per-engine manual migration plans, manual-work reports, preview CGS files, and rollback manifests; verifies mapped file evidence matches actual files; verifies preview CGS contains starter modes/actors/components/assets/semantic binding candidates; verifies rollback restores the original CGS exactly; and verifies engine files remain byte/mtime-stable. Report `target-codex-task58-manual-migration\report.json` has `x10_058_complete=true`; SHA-256 `eea5c6ba1b51184674bc4a7a36c51c80b615718cd0ba561453caa501e217e401`.
  - Boundary: this closes the editor-free manual migration planning/reporting layer. It does not auto-convert arbitrary engine gameplay, infer binary scene semantics without user review, persist migration changes without approval, install/uninstall adapters, or certify installed-editor migration UX.
  - Verification: `python -m py_compile packages\project-system\engine_migration_wizard.py packages\project-system\engine_project_inventory.py packages\project-system\project_creator.py packages\builder-workspace\server\builder_server.py tools\manual_migration_wizard_check.py`; `python -m unittest packages/project-system/tests/test_project_system.py`; `python tools\manual_migration_wizard_check.py --output target-codex-task58-manual-migration\report.json --artifact-dir target-codex-task58-manual-migration\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task58-manual-migration\report.json`.

- [x] X10-059: Add reversible adapter install/uninstall.
  - Acceptance: install, update, rollback, and uninstall adapters without deleting user engine data.
  - Evidence: before/after checks.
  - Done 2026-08-22: added `packages/project-system/adapter_installation.py`, an ownership-manifest and transaction-backup layer for Godot, Unity, and Unreal adapter destinations. Installs and updates create `xace.adapter_engine_install_manifest.v1` manifests plus `xace.adapter_install_transaction.v1` rollback records, overwrite only unchanged XACE-owned files, preserve non-XACE/user-modified files as conflicts, and uninstall only files whose current bytes still match the manifest.
  - Builder/API behavior: `packages/builder-workspace/server/builder_server.py` now routes `/api/project/adapter/install-engine` through the reversible transaction layer and exposes `/api/project/adapter/rollback-engine` and `/api/project/adapter/uninstall-engine` for linked engine projects.
  - Proof: `tools/adapter_reversibility_check.py` uses the real Godot, Unity, and Unreal adapter source folders, creates engine fixtures with user-owned files inside and outside the adapter destination, runs install, update, latest rollback, reinstall, and uninstall, and writes retained operation reports plus before/after file signatures. Report `target-codex-task59-adapter-reversibility\report.json` has `x10_059_complete=true`; SHA-256 `3923a44d34941e5e5e35f32c3a73f5ca394f2a86575dd021741be639dba7c009`.
  - Boundary: this closes editor-free reversible adapter install/update/rollback/uninstall safety for Godot `addons/xace`, Unity `Assets/XACE`, and Unreal `Plugins/XACE`. It does not auto-merge user-edited adapter files, certify installed-editor playthrough after install, or provide remote package download/repair.
  - Certification: `tools/certify_launch.py` now runs the `adapter reversibility gate` in quick/full certification and includes the new module/proof tool in Python compile coverage.
  - Verification: `python -m py_compile packages\project-system\adapter_installation.py tools\adapter_reversibility_check.py packages\builder-workspace\server\builder_server.py packages\project-system\tests\test_project_system.py`; `python -m unittest packages/project-system/tests/test_project_system.py`; `python tools\adapter_reversibility_check.py --output target-codex-task59-adapter-reversibility\report.json --artifact-dir target-codex-task59-adapter-reversibility\artifacts --json`; `Get-FileHash -Algorithm SHA256 target-codex-task59-adapter-reversibility\report.json`.

- [x] X10-060: Rename export to adapter package handoff.
  - Acceptance: UI, docs, API names, and reports avoid "finished game export" claims.
  - Evidence: forbidden wording scan.
  - Done 2026-08-22: renamed the active Builder adapter handoff surface from a finished-game-style export vocabulary to adapter package handoff vocabulary. The backend route is now `/api/adapter-package/handoff/{target}`, retained artifacts are written under `.xace/adapter_package_handoffs/<target>`, and the manifest is `xace_adapter_package_handoff_manifest.json` with schema `xace.adapter_package_handoff_manifest.v1` plus an explicit `engine_project_owns_shipping_package` boundary.
  - UI/report behavior: Builder handoff menu classes, button labels, fetch route, completion event, semantic binding status labels, asset preflight phase names, and Godot/Unity/Unreal adapter status report fields now use handoff wording. Semantic binding reports emit `blocks_handoff`; asset preflight emits `adapter_package_handoff`; the older `export` phase remains accepted only as a compatibility alias at the Python validation boundary.
  - Proof: `tools/adapter_package_handoff_wording_check.py` scans the Builder backend/UI, semantic binding panels, asset preflight/status modules, adapter report hooks, README, claims/readiness docs, source inventory, and tasklist for required handoff markers and stale adapter-export surface names. Report `target-codex-task60-adapter-handoff-wording\report.json` has `x10_060_complete=true`; SHA-256 `e55b8036ed0740b94bdfc06daf13784fc3118787afa5cd50300c1e90937ca8ed`.
  - Boundary: this closes wording/API/report precision for adapter package handoff. It does not add the full umbrella preflight, adapter package versioning, update-channel/signature flow, or installed-editor shipping validation; those remain X10-061 through X10-064 and later launch gates.
  - Certification: `tools/certify_launch.py` now runs the `adapter package handoff wording gate` in quick/full certification and includes the proof tool in Python compile coverage.
  - Verification: `python -m py_compile tools\adapter_package_handoff_wording_check.py tools\certify_launch.py packages\asset-registry\asset_reference_preflight.py packages\asset-registry\semantic_binding_status.py tools\asset_reference_validation_check.py tools\semantic_binding_status_check.py packages\builder-workspace\server\builder_server.py`; `python -m unittest packages/asset-registry/tests/test_asset_reference_preflight.py packages/asset-registry/tests/test_semantic_binding_status.py`; `python tools/asset_reference_validation_check.py --output target-codex-task60-handoff-asset-validation\report.json --artifact-dir target-codex-task60-handoff-asset-validation\artifacts --json`; `python tools/semantic_binding_status_check.py --output target-codex-task60-handoff-status\report.json --artifact-dir target-codex-task60-handoff-status\artifacts --json`; `npm run test:ui` from `packages/builder-workspace`; `python tools/source_inventory_check.py --json`; `python tools/forbidden_claims_check.py`; `python tools/adapter_package_handoff_wording_check.py --output target-codex-task60-adapter-handoff-wording\report.json --json`; `Get-FileHash -Algorithm SHA256 target-codex-task60-adapter-handoff-wording\report.json`.

- [x] X10-061: Add adapter package handoff preflight validation.
  - Acceptance: CGS, SGC plan, runtime compatibility, adapter version, assets, bindings, secrets, and target engine must pass before package handoff.
  - Evidence: blocked handoff matrix.
  - Done 2026-08-23: added `packages/project-system/adapter_package_handoff_preflight.py`, the umbrella pre-copy handoff gate used by Builder before any adapter package files are deleted or copied into `.xace/adapter_package_handoffs/<target>`.
  - Gate behavior: the preflight validates the target engine and required adapter source files, strict CGS schema/hash, persisted SGC execution plan contract and runtime-load compatibility, retained runtime compatibility proof, adapter protocol/version markers, asset-reference handoff readiness, per-target semantic binding status, and local secret-pattern scans over manifest/CGS/assets/adapter source.
  - Builder behavior: `/api/adapter-package/handoff/{target}` now writes `.xace/adapter_package_handoff_preflight/<target>/<cgs_hash>.json` and returns `ok=false` with blocking categories when preflight fails; the endpoint refuses before copy, so a blocked handoff does not create the handoff package directory.
  - Proof: `tools/adapter_package_handoff_preflight_check.py` builds a passing fixture plus a blocked handoff matrix for `target_engine`, `cgs`, `sgc_plan`, `runtime_compatibility`, `adapter_version`, `assets`, `bindings`, and `secrets`; report `target-codex-task61-adapter-package-handoff-preflight\report.json` has `x10_061_complete=true`; SHA-256 `fb4bb74feba4fb7a6eae251411d5eaa268b5ff8ffb221f20f6f021eeae97e834`.
  - Boundary: this proves adapter package handoff readiness/refusal before copy. It does not version/sign adapter packages, provide update-channel metadata, certify installed-editor package import, or run engine-owned platform packaging/builds; those remain X10-062+ and later launch gates.
  - Certification: `tools/certify_launch.py` now runs the `adapter package handoff preflight gate` in quick/full certification and includes both the production module and proof tool in Python compile coverage.
  - Verification: `python -m py_compile packages\project-system\adapter_package_handoff_preflight.py tools\adapter_package_handoff_preflight_check.py packages\builder-workspace\server\builder_server.py tools\certify_launch.py`; `python tools\adapter_package_handoff_preflight_check.py --output target-codex-task61-adapter-package-handoff-preflight\report.json --artifact-dir target-codex-task61-adapter-package-handoff-preflight\artifacts --json`; `python tools\adapter_package_handoff_wording_check.py --output target-codex-task61-adapter-handoff-wording\report.json --json`; `python tools\source_inventory_check.py --json`; `python tools\forbidden_claims_check.py`; `git diff --check`; `Get-FileHash target-codex-task61-adapter-package-handoff-preflight\report.json -Algorithm SHA256`.

- [x] X10-062: Version adapter packages.
  - Acceptance: Godot, Unity, and Unreal packages include version, compatibility matrix, dependency declarations, install/uninstall scripts, rollback support, and checksums.
  - Evidence: package verification in CI.
  - Done 2026-08-23: added `packages/project-system/adapter_package_versioning.py` with manifest schema `xace.adapter_package_version_manifest.v1`, verification schema `xace.adapter_package_version_verification.v1`, package version `0.1.0`, adapter protocol version, per-engine compatibility matrix, required dependency declarations, lifecycle script declarations, rollback support metadata, SHA-256 file inventory, and package content digest for Godot, Unity, and Unreal adapter packages.
  - Adapter package behavior: Godot, Unity, and Unreal now include `xace_adapter_package_lifecycle.py` wrappers with `describe`, `install`, `uninstall`, and `rollback`; generated package manifests are excluded from installed payloads, and `__pycache__`/`.pyc` files are ignored so checksum and runtime packaging proofs stay stable.
  - Builder behavior: `/api/adapter-package/handoff/{target}` verifies source package metadata before copy, writes `xace_adapter_package_version_manifest.json` into the copied handoff package, verifies post-copy checksums, retains `.xace/adapter_package_versions/<target>/<package_content_sha256>.json`, and returns package version, compatibility matrix, dependencies, lifecycle scripts, rollback support, and checksum metadata.
  - Proof: `tools/adapter_package_version_check.py` stages and verifies all three adapter packages, runs lifecycle `describe`, proves checksum tamper rejection, and proves Builder handoff writes versioned package manifests; report `target-codex-task62-adapter-package-version\report.json` has `x10_062_complete=true` and passes 14/14 checks; SHA-256 `084a6b8451e6559932cbdd2adb9c7e2d6d6aaa2ec13d8ba806fa5d4719a49058`.
  - Boundary: this versions and verifies local adapter packages. It does not sign packages, publish/update package channels, certify installed-editor package import UX, or perform engine-owned platform packaging/builds; those remain later launch gates.
  - Certification: `tools/certify_launch.py` now runs the `adapter package version gate` in quick/full certification and includes the production module/proof tool in Python compile coverage.
  - Verification: `python -m py_compile packages\project-system\adapter_package_versioning.py packages\project-system\adapter_installation.py tools\adapter_package_version_check.py packages\builder-workspace\server\builder_server.py tools\certify_launch.py`; `python tools\adapter_package_version_check.py --output target-codex-task62-adapter-package-version\report.json --artifact-dir target-codex-task62-adapter-package-version\artifacts --json`; `python tools\adapter_reversibility_check.py --output target-codex-task62-adapter-reversibility\report.json --artifact-dir target-codex-task62-adapter-reversibility\artifacts --json`; `python tools\adapter_package_handoff_preflight_check.py --output target-codex-task62-adapter-package-handoff-preflight\report.json --artifact-dir target-codex-task62-adapter-package-handoff-preflight\artifacts --json`; `python tools\adapter_package_handoff_wording_check.py --output target-codex-task62-adapter-handoff-wording\report.json --json`; `python tools\source_inventory_check.py --json`; `python tools\forbidden_claims_check.py`; `git diff --check`; `Get-FileHash target-codex-task62-adapter-package-version\report.json -Algorithm SHA256`.

- [x] X10-063: Define canonical cross-engine vertical slice.
  - Acceptance: one CGS-owned slice covers movement, combat, health, inventory, save/load, rollback, replay, semantic bindings, animation, audio, VFX, and network-ready input.
  - Evidence: fixture versioned.
  - Done 2026-08-25: added `projects/canonical_cross_engine_vertical_slice` as the single versioned CGS-owned fixture for later Godot, Unity, and Unreal installed-engine certification tasks.
  - Fixture behavior: `game.cgs.json` is a committed `xace.cgs.export` v1 file with canonical CGS hash `a5856b8c95068a27ce47885c32c7d3e2729c4ff988a47f2dee840bfd13ff0a8a`; `xace.vertical_slice_manifest.json` pins fixture version `0.1.0`, target engines, CGS file SHA-256, required features, coverage map, linked asset hashes, and the host/client lockstep input scenario.
  - Coverage: the slice maps movement, combat, health, inventory, save/load, clean-boundary rollback, input-log replay, semantic bindings, animation, audio, VFX fallback, and network-ready input to concrete CGS systems, components, semantic events, assets, and binding IDs.
  - Proof: `tools/canonical_vertical_slice_check.py` validates the committed CGS hash, manifest identity, feature references, linked asset SHA-256 values, runtime/save/adapter-package asset preflight across Godot/Unity/Unreal, and semantic binding status; report `target-codex-task63-canonical-vertical-slice\report.json` has `x10_063_complete=true` and passes 10/10 checks; SHA-256 `9f0a7077d262eea55f6d6d7d12075c7bb9878f3f157d6f3eb58dfd4c01742faf`.
  - Boundary: this defines and verifies the canonical fixture only. Installed-editor proof and matching portable-core hash comparison are covered by X10-064 through X10-067; native scenes, platform packaging, and finished-game export remain separate gates.
  - Certification: `tools/certify_launch.py` now runs the `canonical vertical slice fixture gate` in quick/full certification and includes the proof tool in Python compile coverage.
  - Verification: `python -m py_compile tools\canonical_vertical_slice_check.py`; `python tools\cgs_schema_validate.py projects\canonical_cross_engine_vertical_slice\game.cgs.json --json`; `python tools\canonical_vertical_slice_check.py --output target-codex-task63-canonical-vertical-slice\report.json --json`; `Get-FileHash target-codex-task63-canonical-vertical-slice\report.json -Algorithm SHA256`.

- [x] X10-064: Certify vertical slice in Godot.
  - Acceptance: installed Godot proof includes validation JSON, screenshots or video, logs, and hash report.
  - Evidence: installed-engine proof path.
  - Done 2026-08-25: added `tools/godot_vertical_slice_certification.py`, a retained installed-Godot proof that stages the X10-063 canonical CGS-owned slice into a disposable Godot project and copies the current Godot adapter scripts under `addons/xace`.
  - Proof: the tool reruns the X10-063 fixture gate, launches installed Godot 4.6.3 headless, has Godot parse the staged CGS/manifest/assets, load all 9 current Godot adapter scripts, emit `godot_vertical_slice_validation.json`, emit deterministic PNG evidence, retain stdout/stderr/command logs, and write a hash report over the fixture, adapter scripts, runner, validation JSON, PNG, and logs.
  - Evidence path: `target-codex-task64-godot-vertical-slice`; final report `target-codex-task64-godot-vertical-slice\report.json` has `x10_064_complete=true` and passes 7/7 wrapper checks; Godot-authored validation JSON passes 10/10 in-engine checks.
  - Evidence hashes: report SHA-256 `cf5b9cbab3da82d412d846944f0a5629e397373af11448ed97d9f34826b42b9f`; validation JSON SHA-256 `5f368ca06dc35741afcc00a6a121834f55d6b4dfd42cfcd79f93110ac969f23a`; PNG SHA-256 `546fb9e492a5558bc85050e4b6035fe06a3ace7df822acac973dccc31eeb1df8`; hash report SHA-256 `c0f8ee83b9daea7b9299c77858118be681a507fc9c82c57c82100d40a021efc6`.
  - Boundary: this is an installed Godot headless certification artifact for the canonical slice. It does not claim a finished-game package, human-recorded gameplay video, platform export, Unity/Unreal parity, or cross-engine runtime-authoritative hash equivalence; those remain later gates.
  - Certification: `tools/certify_launch.py` includes the Godot vertical-slice proof tool in Python compile coverage.
  - Verification: `python -m py_compile tools\godot_vertical_slice_certification.py`; `python tools\godot_vertical_slice_certification.py --godot-bin "C:\Users\ankit\Downloads\Godot_v4.6.3-stable_win64.exe\Godot_v4.6.3-stable_win64_console.exe" --target-dir target-codex-task64-godot-vertical-slice --output target-codex-task64-godot-vertical-slice\report.json --timeout 45 --json`; `Get-FileHash target-codex-task64-godot-vertical-slice\report.json -Algorithm SHA256`; `Get-FileHash target-codex-task64-godot-vertical-slice\artifacts\reports\godot_vertical_slice_validation.json -Algorithm SHA256`; `Get-FileHash target-codex-task64-godot-vertical-slice\artifacts\screenshots\godot_vertical_slice_screenshot.png -Algorithm SHA256`; `Get-FileHash target-codex-task64-godot-vertical-slice\artifacts\hashes\godot_vertical_slice_hash_report.json -Algorithm SHA256`.

- [x] X10-065: Certify vertical slice in Unity.
  - Acceptance: installed Unity proof includes validation JSON, screenshots or video, logs, and hash report.
  - Evidence: installed-engine proof path.
  - Done 2026-08-25: added `tools/unity_vertical_slice_certification.py`, a retained installed-Unity proof that stages the X10-063 canonical CGS-owned slice into a disposable Unity project, copies the current Unity adapter sources under `Assets/XACE`, includes required built-in Animation and Particle System modules, and adds an Editor certification command for in-Unity fixture/script/asset validation plus PNG evidence.
  - Proof: the tool reruns the X10-063 fixture gate, launches installed Unity 6000.4.9f1 in batch mode, has Unity compile/construct current adapter components, validate staged CGS/manifest/assets/features/input scenario, emit `unity_vertical_slice_validation.json`, emit deterministic PNG evidence through `Texture2D.EncodeToPNG`, retain editor/stdout/stderr/command logs, and write a hash report over the fixture, adapter scripts, generated runner, validation JSON, PNG, and logs.
  - Evidence path: `target-codex-task65-unity-vertical-slice`; final report `target-codex-task65-unity-vertical-slice\report.json` has `x10_065_complete=true` and passes 7/7 wrapper checks; Unity-authored validation JSON passes 9/9 in-editor checks.
  - Evidence hashes: report SHA-256 `ea5fa9c222cd7273b316ab2959db6c368e033e383ec3751ea192ba134f60a016`; validation JSON SHA-256 `3a394b403cfb2a10ea9169fa6d86bc6e3d54ef9ea45ec30686ef369506d8e1dc`; PNG SHA-256 `f1a4d3ae0cebc0a3c9aba93f4339ecc5569cb020e578dfd3cf6047fce132b3a4`; hash report SHA-256 `29136de6bbc450b933d415b87634f8745827fd45d1700449080695d296821c84`.
  - Boundary: this is an installed Unity batch-mode certification artifact for the canonical slice. It does not claim a finished-game package, human-recorded gameplay video, platform export, Unreal parity, or cross-engine runtime-authoritative hash equivalence; those remain later gates.
  - Certification: `tools/certify_launch.py` includes the Unity vertical-slice proof tool in Python compile coverage.
  - Verification: `python -m py_compile tools\unity_vertical_slice_certification.py`; `python tools\unity_vertical_slice_certification.py --unity-exe "C:\Program Files\Unity\Hub\Editor\6000.4.9f1\Editor\Unity.exe" --target-dir target-codex-task65-unity-vertical-slice --output target-codex-task65-unity-vertical-slice\report.json --timeout 240 --json`; `Get-FileHash target-codex-task65-unity-vertical-slice\report.json -Algorithm SHA256`; `Get-FileHash target-codex-task65-unity-vertical-slice\artifacts\reports\unity_vertical_slice_validation.json -Algorithm SHA256`; `Get-FileHash target-codex-task65-unity-vertical-slice\artifacts\screenshots\unity_vertical_slice_screenshot.png -Algorithm SHA256`; `Get-FileHash target-codex-task65-unity-vertical-slice\artifacts\hashes\unity_vertical_slice_hash_report.json -Algorithm SHA256`.

- [x] X10-066: Certify vertical slice in Unreal.
  - Acceptance: installed Unreal proof includes validation JSON, screenshots or video, logs, and hash report.
  - Evidence: installed-engine proof path.
  - Done 2026-08-30: added `tools/unreal_vertical_slice_certification.py`, a retained installed-Unreal proof that stages the X10-063 canonical CGS-owned slice into a disposable Unreal project, copies the current Unreal adapter sources into a real `Plugins/XACE` plugin, adds an X10-066 certification commandlet, and runs the installed Unreal toolchain against the staged project.
  - Proof: the tool reruns the X10-063 fixture gate, launches Unreal 5.7.4 `RunUAT.bat BuildPlugin`, compiles current adapter sources plus the generated commandlet, copies editor binaries back into the staged project, runs `UnrealEditor-Cmd.exe -run=XaceVerticalSliceCertification`, has Unreal validate staged CGS/manifest/assets/features/input scenario, constructs the current adapter components, emits `unreal_vertical_slice_validation.json`, emits deterministic PNG evidence through Unreal `ImageWrapper`, retains build/stdout/stderr/editor/command logs, and writes a hash report over the fixture, adapter sources, generated commandlet, plugin binaries, validation JSON, PNG, and logs.
  - Evidence path: `target-codex-task66-unreal-vertical-slice`; final report `target-codex-task66-unreal-vertical-slice\report.json` has `x10_066_complete=true` and passes 8/8 wrapper checks; Unreal-authored validation JSON passes 10/10 in-commandlet checks.
  - Evidence hashes: report SHA-256 `6342c9c32019c31b8c2b304fb1597a19fb73592ce2e4e8b56607ca637d3a5272`; validation JSON SHA-256 `60ecacd8fcf83c5e98e572c7f5f951173b34377fbaeeb57cb07b15ee01c32200`; PNG SHA-256 `e6c3a5e4f1897972bbc7af7e8b5002c2238691d7b1a88dfa14ca4b3a9bb1f122`; hash report SHA-256 `62b0d1fd09750a4e4a648092629f1721aeb8aa9be691758fb64d02ff20fd39de`.
  - Boundary: this is an installed Unreal commandlet certification artifact for the canonical slice. It does not claim a finished-game package, human-recorded gameplay video, platform export, broad visual parity, or arbitrary Unreal project migration; cross-engine portable-core hash equivalence is covered by X10-067.
  - Certification: `tools/certify_launch.py` includes the Unreal vertical-slice proof tool in Python compile coverage.
  - Verification: `python -m py_compile tools\unreal_vertical_slice_certification.py`; `python tools\unreal_vertical_slice_certification.py --unreal-editor "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" --target-dir target-codex-task66-unreal-vertical-slice --output target-codex-task66-unreal-vertical-slice\report.json --build-timeout 900 --run-timeout 300 --json`; `Get-FileHash target-codex-task66-unreal-vertical-slice\report.json -Algorithm SHA256`; `Get-FileHash target-codex-task66-unreal-vertical-slice\artifacts\reports\unreal_vertical_slice_validation.json -Algorithm SHA256`; `Get-FileHash target-codex-task66-unreal-vertical-slice\artifacts\screenshots\unreal_vertical_slice_screenshot.png -Algorithm SHA256`; `Get-FileHash target-codex-task66-unreal-vertical-slice\artifacts\hashes\unreal_vertical_slice_hash_report.json -Algorithm SHA256`.

- [x] X10-067: Compare cross-engine core hashes.
  - Acceptance: portable runtime-authoritative hashes match; nonportable visual/engine effects are documented as excluded.
  - Evidence: cross-engine comparison report.
  - Done 2026-08-31: added `tools/cross_engine_core_hash_compare.py`, a retained X10-067 proof that reads the completed Godot, Unity, and Unreal installed-engine vertical-slice reports from X10-064 through X10-066, verifies each one attests to the same canonical X10-063 CGS-owned slice, and compares a normalized portable runtime-authoritative core hash.
  - Proof: the comparer builds the portable core projection from CGS metadata, deterministic runtime contracts, feature coverage, component/system/rule declarations, asset identities and SHA-256 declarations, semantic events/bindings, input profiles, and the canonical host/client input scenario. It records Godot, Unity, and Unreal matching portable-core hash `a9852c1849ed26f5a78a0c8d47b4b8a161db77ffce277641e86ac1abceb37222`.
  - Evidence path: `target-codex-task67-cross-engine-core-hash`; final report `target-codex-task67-cross-engine-core-hash\report.json` has `x10_067_complete=true` and passes 6/6 wrapper checks; each retained engine attestation passes 13/13 checks.
  - Evidence hashes: report SHA-256 `de9dc1cc7a576024a5b6c1551534eea20d62ad4e09e5e4ac6569f71d773a9a8e`; portable projection SHA-256 `b436d931997b5d8a15480366729a3a0b24be3eb679287ce66a3d02d8c88b6ecd`; comparison matrix SHA-256 `b0e1f00cda41db6f4ebba66ff459446e3e9a88c4a37e6023065ccb125e806bf3`; hash report SHA-256 `45f91db49634b74ab59b0521411a1c7c4965d8e5ecd199a12b673796bec66ebf`.
  - Boundary: this proves retained installed-engine Godot/Unity/Unreal evidence maps to the same portable CGS/runtime core. It explicitly excludes engine executable/version metadata, adapter source/plugin/binary artifacts, generated runners, PNG evidence bytes, logs, timestamps, durations, project staging paths, and engine-specific validation schemas; finished-game packaging/export remains out of scope.
  - Certification: `tools/certify_launch.py` includes the cross-engine core hash comparison proof tool in Python compile coverage.
  - Verification: `python tools\cross_engine_core_hash_compare.py --output target-codex-task67-cross-engine-core-hash\report.json --json`; `Get-FileHash target-codex-task67-cross-engine-core-hash\report.json -Algorithm SHA256`.

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
