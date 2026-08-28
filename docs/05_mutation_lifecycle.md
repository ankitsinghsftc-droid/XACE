# 05 Mutation Lifecycle

Current production-readiness status: deterministic queued application,
snapshot-backed apply-time rollback, static CGS conflict analysis, and
Builder prompt-apply cross-layer recovery are implemented for the covered
runtime and prompt mutation paths.

All structural entity/component changes flow through `MutationGate`. Systems
enqueue mutation requests during phase execution, and the `PhaseOrchestrator`
calls `MutationGate::apply_all_with_runtime_state()` at phase boundaries so
entity state, component tables, event state, RNG state, and queued mutations are
captured in one rollback transaction.

The public `MutationGate::apply_all()` test/helper path and the runtime-state
path both delegate to the same private transaction implementation. The old
unreachable direct-apply body has been removed, and
`tools/mutation_gate_apply_path_check.py` verifies that there is exactly one
real apply implementation.

The gate applies queues in this fixed order:

1. spawn
2. add component
3. modify component
4. remove component
5. destroy

Safe claim today:

- XACE has a single mutation gateway for structural runtime world changes.
- Mutation requests are validated before enqueueing.
- Queued operations apply in deterministic order at phase boundaries.
- Apply-time failures restore the captured entity/component/queue state and
  optional runtime event/RNG state when provided by the orchestrator.
- Failure diagnostics report the operation index, operation type, entity,
  component, path, source error, and rollback status.
- Certified prompt applies run PIL preview approval, GDE commit, SGC compile,
  persistence, runtime reload/replay validation, adapter validation, and UI
  completion as one recovery-backed transaction.
- Prompt-apply failures after GDE commit restore the pre-apply CGS, persisted
  plan/proof/snapshot artifacts, GDE state, cached runtime status, runtime
  reload target, pending prompt/UI state, and adapter-visible session edit log
  before any `cgs_update` success is emitted.
- Runtime `reload_cgs` hot-swaps accepted CGS/SGC schedule changes at a clean
  tick boundary. The runtime validates requested disk version IDs, loads the
  incoming CGS/plan into scratch stores, swaps the active registry/schedule, and
  preserves live tick, entity IDs, component rows, engine bridge state, pending
  input queues, and existing tick hash log.
- Hot-swap compatibility is classified before live mutation. The runtime labels
  candidate changes as `additive`, `migratable`, `state_transforming`, or
  `reset_required`; only fully additive candidates can proceed through the live
  hot-swap path today.
- Engine-originated Builder edits are preview-first and audit-bound. Durable
  engine edit commits are limited to accepted primitive component-default audit
  rows and must echo the accepted `preview_id`, CGS hash, schema version,
  runtime world hash, and adapter sequence before GDE or persistence can run.

Do not overclaim yet:

- "Every CGS/prompt/schema mutation is conflict-safe." X10-018 now blocks
  static CGS dependency cycles, state access hazards, incompatible component
  migrations, and generated-system ABI mismatches before persistence, and
  X10-019 makes the Builder prompt apply path atomic across GDE, SGC,
  persistence, runtime validation, adapter validation, and UI completion. X10-020
  adds state-preserving runtime hot-swap for compatible/additive schedule
  changes, X10-021 classifies/enforces hot-swap compatibility, X10-022 adds
  deterministic migration hooks, and X10-023 adds adapter side-effect rollback
  notices for restored runtime state.
- "Engine-side visual/audio side effects roll back with runtime state." X10-023
  now covers the protocol/runtime restore notice plus Godot, Unity, and Unreal
  adapter cleanup for spawned mirror objects, playback commands, feedback
  queues, pending edit previews, and asset-binding caches. Installed editor
  execution remains part of the global installed-engine proof gate.
- "Live schema hot-swap handles every schema change." X10-020 proves the
  state-preserving runtime swap path for compatible/additive schedule changes;
  X10-021 now refuses migratable, state-transforming, and reset-required changes
  before live mutation; X10-022 adds deterministic state migrations. X10-024
  hardens the Builder/live-engine edit boundary but does not open structural
  engine-originated CGS mutation classes.

Current failure contract:

If `apply_all()` or `apply_all_with_runtime_state()` fails during queued
operation application, the gate restores the pre-batch rollback image, restores
queued mutations instead of discarding them, verifies the rollback hash when
entity/component state is available, stores `MutationApplyFailureDiagnostic`,
and returns a structured `XaceError`.

Production gate:

1. Capture a complete pre-batch snapshot before applying a mutation batch.
2. Restore entity/component state and replay-visible runtime state on failure.
3. Verify the restored hash equals the pre-batch hash.
4. Report failing operation index/type/entity/component and rollback status.
5. Keep `tools/mutation_gate_apply_path_check.py` and focused mutation-gate
   tests in launch certification.

Prompt apply atomicity gate:

1. Capture pre-apply CGS, version IDs, pending prompt/UI state, adapter edit log,
   and runtime status before GDE commit.
2. On SGC compile/skip, CGS save, snapshot, plan, proof, runtime reload, replay,
   or adapter validation failure, restore all captured local layers and ask the
   runtime-control path to reload the pre-apply version IDs when connected.
3. Emit `xace.prompt_apply_recovery.v1` with `gde_restored`,
   `ui_status_restored`, `adapter_visible_effects_restored`,
   `session_restore`, and `runtime_restore` fields.
4. Audit failures as `rejected_recovered` with
   `rollback_status=restored_pre_apply`.
5. Keep `tools/prompt_apply_recovery_check.py` in launch certification.
