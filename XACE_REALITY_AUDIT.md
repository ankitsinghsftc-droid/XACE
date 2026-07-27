# XACE Reality Audit

## 1. One-paragraph truth summary

XACE today is an in-progress, schema-driven gameplay-core platform: it has real Rust runtime infrastructure for canonical game state, built-in gameplay systems, deterministic tick hashing, mutation rollback, replay/hash validation, a real System Graph Compiler, a Builder UI/server, prompt-assisted CGS mutation plumbing, and source-level Godot/Unity/Unreal adapters. It is not yet a full game engine, not an arbitrary prompt-to-game system, not a proven UE5/Unity/Godot replacement, and not production-ready multiplayer infrastructure. The strongest real product is not "AI generates any game"; it is "AI and humans can mutate a schema-constrained gameplay core that can be deterministically compiled, simulated, validated, replayed, and mirrored into engines." The hardest gaps are runtime loading of persisted SGC execution plans, real arbitrary gameplay-system support, complete multiplayer rollback/desync recovery, clean full-workspace tests, installed-engine proof artifacts, and cross-platform determinism proof.

## 2. What XACE is

- A schema-first gameplay-core platform centered on Canonical Game Schema (CGS), shared contracts, and deterministic runtime execution. Evidence: `packages/core/src`, `docs/CGS_SCHEMA_EXPORT_FORMAT.md`, `docs/schemas/xace-cgs-export.schema.json`, `packages/runtime-core/src`.
- A Rust runtime that can load CGS, run a built-in phase plan, execute supported built-in systems, apply mutations, snapshot state, compute world hashes, expose runtime status, and bridge to engine clients. Evidence: `packages/runtime-core/src/runtime_orchestrator.rs`, `packages/runtime-core/src/cgs_loader.rs`, `packages/runtime-core/src/builtin_systems.rs`, `packages/runtime-core/src/engine_bridge.rs`.
- A local deterministic simulation and validation framework. Evidence: `RuntimeOrchestrator::tick` in `packages/runtime-core/src/runtime_orchestrator.rs:273`, `PhaseOrchestrator::tick_with_guard` in `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs:159`, `DeterminismGuard` and `ReplayValidator` under `packages/runtime-core/src/determinism_guard`.
- A mutation transaction system with apply-time rollback. Evidence: `MutationGate::apply_all_with_runtime_state` in `packages/runtime-core/src/mutation_gate/mutation_gate.rs:397`.
- A real System Graph Compiler for dependency analysis, cycle detection, scheduling, and parallelization safety analysis. Evidence: `SgcPipeline::compile` and `SgcPipeline::compile_and_verify` in `packages/system-graph-compiler/src/sgc_pipeline.rs:40` and `:72`, CLI entry in `packages/system-graph-compiler/src/main.rs:55`.
- A Builder workspace with a TypeScript UI and Python server that can manage sessions, apply GDE mutations, invoke SGC, and run a constrained prompt pipeline. Evidence: `packages/builder-workspace/src`, `packages/builder-workspace/server/session_manager.py`, especially `SessionManager.run_pil` at `:331`, `compile_sgc_plan` at `:477`, and `_apply_via_gde` at `:767`.
- A set of engine-side adapter sources, not a finished engine replacement. Evidence: `adapters/godot/xace_adapter.gd`, `adapters/godot/xace_delta_applicator.gd`, `adapters/unity/XaceTransport.cs`, `adapters/unity/XaceDeltaApplicator.cs`, `adapters/unreal/XaceTransport.cpp`, `adapters/unreal/XaceDeltaApplicator.cpp`.
- A collection of proof and certification scripts for local smoke testing, prompt contract testing, runtime bridge testing, asset playback testing, provider readiness gating, and launch certification. Evidence: `tools/certify_launch.py`, `tools/prompt_pipeline_smoke.py`, `tools/runtime_bridge_smoke.py`, `tools/asset_playback_smoke.py`, `tools/provider_readiness_smoke.py`.

## 3. What XACE is not

- Not a full game engine. The repo has runtime, schema, adapter, Builder, and proof infrastructure, but no complete renderer/editor/physics/content pipeline that replaces Unity, Unreal, or Godot.
- Not proven for arbitrary "any game" prompts. The prompt proof path is explicitly scenario-constrained, and `tools/prompt_pipeline_smoke.py:129` labels its SGC scope as `"fake SGC wiring test only"`.
- Not a complete UE5 replacement. Unreal integration exists as adapter source in `adapters/unreal`, but the core value is engine-side mirroring and feedback, not replacing Unreal's editor, renderer, physics, asset system, networking stack, or packaging pipeline.
- Not a production-ready multiplayer platform. `packages/network-core` has meaningful primitives, but the audited network test run failed in `packages/network-core/tests/test_desync_detection.rs:86`.
- Not proven to work across all engines in live installed editors. `tools/certify_launch.py:1164` prints that installed-engine validation is skipped unless `--installed-engines` is passed.
- Not yet a runtime for arbitrary compiled SGC plans. `packages/system-graph-compiler` compiles plans, but `packages/runtime-core/src/cgs_loader.rs:363` builds a runtime phase plan from CGS and `is_builtin_runtime_system` at `:452` filters execution to built-in runtime systems.
- Not proven production-ready. The targeted `xace-runtime-core` and `xace-system-graph-compiler` tests passed in this audit, but `cargo test --workspace` failed because `xace-engine-adapter` had failing tests.
- Not a complete finished-game export/import tool. The repo supports schema export, adapter packaging, asset/linking primitives, and launch smokes, but not a verified finished-game export/import pipeline.
- Not studio-grade debugging yet. There are tick/debug panels, runtime status, hashes, traces, and feedback plumbing, but no evidence of a mature debugger comparable to engine-native profilers/debuggers.

## 4. Reliable capabilities today

| Capability | Evidence in code/docs/tests | Reliability level | Notes |
|---|---|---|---|
| CGS schema and shared gameplay contracts | `packages/core/src`, `docs/CGS_SCHEMA_EXPORT_FORMAT.md`, `docs/schemas/xace-cgs-export.schema.json`, `tools/cgs_schema_validate.py` | Mostly working | Good foundation, but schema breadth and migration guarantees are not yet externally proven. |
| Runtime ticking from CGS for supported built-ins | `RuntimeOrchestrator::tick` in `packages/runtime-core/src/runtime_orchestrator.rs:273`, `packages/runtime-core/src/builtin_systems.rs`; `cargo test -p xace-runtime-core --lib` passed 589 tests | Mostly working | Works locally for built-in systems. Arbitrary CGS systems are filtered out unless they map to built-in runtime systems. |
| Built-in gameplay systems | `packages/runtime-core/src/builtin_systems.rs`; tests for input, movement, interaction, inventory, AI, damage, death appeared in the passing runtime test run | Mostly working | Real gameplay primitives exist, but this is a small curated system set, not arbitrary gameplay generation. |
| Deterministic world hashing | `packages/runtime-core/src/determinism_guard/world_hasher.rs`, `PhaseOrchestrator::tick_with_guard` at `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs:159`; runtime tests passed | Mostly working | Strong local evidence. Hashing covers core world state; broader runtime side channels and cross-platform/engine CI proof are not fully proven. |
| Local replay/hash validation | `RuntimeOrchestrator::record_replay_hash_log` at `packages/runtime-core/src/runtime_orchestrator.rs:474`, `validate_recorded_replay_from_cgs` at `:499`; runtime tests passed | Mostly working | Good local proof. Not yet evidence of durable replay validation across machines or engines. |
| Mutation rollback/recovery | `MutationGate::apply_all_with_runtime_state` at `packages/runtime-core/src/mutation_gate/mutation_gate.rs:397`; runtime tests passed | Mostly working | Real apply-time rollback exists. Product claims should stay local until fuzzing, concurrency, and production workloads are proven. |
| Snapshot restore | `packages/runtime-core/src/snapshot_engine/snapshot_engine.rs`, `RuntimeOrchestrator::restore_world_snapshot` in `runtime_orchestrator.rs`; runtime tests passed | Partial | Entity/component state restore is real. Event/mutation queue and broader runtime side effects are more limited. |
| System Graph Compiler | `SgcPipeline::compile` and `compile_and_verify` in `packages/system-graph-compiler/src/sgc_pipeline.rs:40` and `:72`; `cargo test -p xace-system-graph-compiler` passed | Proven | Real compiler and CLI exist for graph/scheduling validation. The runtime integration is not complete because persisted plans are not loaded as the execution source. |
| Runtime execution of persisted SGC plans | `packages/runtime-core/src/cgs_loader.rs:8` through `:11` says the standalone runtime still executes a CGS-derived built-in phase plan and does not load `.xace/execution_plans/*.plan.json` | Not found | This is one of the most important product gaps. SGC proof exists, but runtime authority still comes from built-in-filtered CGS loading. |
| SGC proof validation in Builder | `packages/builder-workspace/server/sgc_plan_validator.py`, `SessionManager.compile_sgc_plan` at `packages/builder-workspace/server/session_manager.py:477` | Mostly working | Builder-side validation is meaningful. Runtime still executes a built-in-filtered plan. |
| Actual parallel runtime execution | `packages/runtime-core/src/phase_orchestrator/parallel_executor.rs:18` through `:21`, `execute_parallel` at `:151` | Partial | Deterministic merge semantics exist, but the code comments say full thread-pool parallelism is conceptual/toggleable, not a proven production parallel executor. |
| Prompt pipeline | `SessionManager.run_pil` at `packages/builder-workspace/server/session_manager.py:331`, `tools/prompt_pipeline_smoke.py` | Partial | Scenario-constrained and useful. Not arbitrary prompt-to-game. The smoke uses a fake SGC wiring helper at `tools/prompt_pipeline_smoke.py:252`. |
| GDE schema mutations | `packages/gde`, `_apply_via_gde` in `packages/builder-workspace/server/session_manager.py:767` | Partial | Real mutation path exists. Needs broader prompt corpus, transaction proof, and runtime proof for generated changes. |
| Builder UI | `packages/builder-workspace/src`, Vite build passed in quick certification | Partial | Functional local app surface exists. Not audited as polished workflow UX or public creator product. |
| Provider readiness and BYOK-style gating | `packages/builder-workspace/server/provider_settings.py`, `credential_store.py`, `tools/provider_readiness_smoke.py` | Partial | Readiness gating and credential abstractions exist. The audit did not prove real hosted provider calls with real credentials. |
| Engine adapter protocol | `packages/runtime-core/src/engine_protocol.rs`, `packages/engine-adapter/src`, `adapters/*` | Partial | Real protocol and adapter source exist. Full workspace adapter tests failed, and installed-engine validation was skipped. |
| Godot adapter | `adapters/godot/xace_adapter.gd:60`, `send_input_actions` at `:72`, `xace_delta_applicator.gd:26` | Partial | Concrete GDScript adapter exists. Current audit did not run a real Godot editor certification. |
| Unity adapter | `adapters/unity/XaceTransport.cs:31`, `Connect` at `:146`, `SendInputPacket` at `:194`, `XaceDeltaApplicator.cs:14` | Partial | Concrete C# adapter exists. Current audit did not run a real Unity editor certification. |
| Unreal adapter | `adapters/unreal/XaceTransport.cpp:140`, `SendInputPacket` at `:194`, `UXaceDeltaApplicatorComponent` in `adapters/unreal/XaceDeltaApplicator.cpp:40` | Partial | Concrete C++ adapter exists. Current audit did not run a real Unreal editor certification. |
| Delta compression and sync | `packages/engine-adapter/src/delta_sync`, failing tests in `delta_compressor.rs:545` and `test_delta_sync_integration.rs:562` | Partial | There is substantial code, but audited tests show compression behavior is currently broken. |
| Multiplayer/network primitives | `packages/network-core/src`, `tools/networked_runtime_smoke.py`; failing test in `packages/network-core/tests/test_desync_detection.rs:86` | Experimental | Good direction, not production proof. Desync/resync correctness is not clean. |
| Asset linking and playback | `packages/core/src/assets`, `tools/asset_playback_smoke.py`, adapter playback command handlers | Partial | Useful primitives exist. End-to-end real-engine asset behavior was not proven in this audit. |
| Save/replay/checkpoint concepts | `packages/save-engine`, `tools/save_runtime_replay.py` in quick certification | Partial | Local smoke coverage exists. Production save compatibility and migration depth are unclear. |
| Documentation honesty | `README.md`, `docs/XACE_PRODUCT_CLAIMS_MATRIX.md`, `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md` | Mostly working | Key docs are unusually honest, but there are stale contradictions and many stub design docs. |
| Public launch certification smoke | `tools/certify_launch.py --quick` passed 13 checks in this audit | Mostly working | Editor-free quick certification passed. It explicitly skipped installed-engine validation. |

## 5. Strongest features / possible moat

| Area | Status | Evidence | Moat assessment |
|---|---|---|---|
| Deterministic gameplay logic | Mostly implemented locally | `RuntimeOrchestrator::tick`, `PhaseOrchestrator::tick_with_guard`, `DeterminismGuard`, passing `xace-runtime-core` tests | Strong possible moat if XACE becomes the verification layer for AI-authored gameplay. Normal code generation is easier to copy than deterministic proof infrastructure. |
| Rollback from bad mutations | Mostly implemented locally | `MutationGate::apply_all_with_runtime_state` in `packages/runtime-core/src/mutation_gate/mutation_gate.rs:397` | Strong if sold as safe live mutation/recovery. Needs fuzzing and hostile-input proof before production claims. |
| Replay validation | Mostly implemented locally | `record_replay_hash_log` and `validate_recorded_replay_from_cgs` in `runtime_orchestrator.rs` | Strong technical direction. Needs persisted artifacts, CI, cross-platform proof, and real bug-catching demos. |
| Multiplayer correctness | Partial/experimental | `packages/network-core`, `tools/networked_runtime_smoke.py`; failing desync test | Potential moat, not current moat. Multiplayer correctness is valuable, but XACE has not proved it yet. |
| Schema-driven gameplay | Mostly implemented as foundation | CGS docs, `packages/core`, `packages/schema-factory`, GDE mutation path | Valuable if schemas become the stable contract between AI, runtime, tests, and engines. Less valuable if it is only a file format. |
| Engine portability | Partial | `adapters/godot`, `adapters/unity`, `adapters/unreal`, engine protocol, runtime bridge smoke | Strategic moat only after a public proof shows the same gameplay core running in at least two real installed engines. |
| Unity/Godot/Unreal integration | Partial | Concrete adapter source in all three folders | Source exists; installed-engine validation was not run in this audit. Claim adapter availability, not full cross-engine support. |
| Debugging tools | Partial | Builder UI panels under `packages/builder-workspace/src`, runtime status/hash summaries, observability package | Could matter if debugging is tied to deterministic replay and mutation history. Generic UI debugging will be undercut by AI and engine-native tools. |
| Tick debugger | Partial | UI/runtime status plumbing exists, `RuntimeTickSummary` and `world_hash` in runtime status | Promising but not proven as a studio-grade debugger. Public demo should show it catching a real determinism issue. |
| Asset linking | Partial | asset refs in core, playback commands in adapters, `tools/asset_playback_smoke.py` | Useful but not yet a moat. Engine-native asset workflows are deep and hard to replace. |
| Prompt pipeline | Partial | `SessionManager.run_pil`, `tools/prompt_pipeline_smoke.py`, prompt contract docs | Weak moat by itself. Future models can generate code/UI/templates. The value is only if prompt output is constrained, validated, replayed, and recoverable. |
| SGC compiler | Implemented | `packages/system-graph-compiler/src/sgc_pipeline.rs`, passing targeted SGC tests | One of the strongest pieces. The missing piece is making runtime execution actually consume persisted SGC execution plans. |
| Simulation validation | Mostly implemented locally | runtime-core tests, replay validation, quick cert runtime bridge/save smokes | Strong direction, especially against future AI-generated code. Needs more external proof. |
| Versioning/migration | Partial | `packages/schema-factory`, `packages/save-engine`, schema version fields in CGS/SGC paths | Important but not yet proven as production-grade migration infrastructure. |
| Recovery from bad mutations | Mostly implemented locally | MutationGate rollback tests, blocked unsupported prompt scenario in `tools/prompt_pipeline_smoke.py` | Real value. Make it a first-class public demo. |

## 6. Weakest assumptions / model-risk

### AI can directly generate gameplay code

Risk: high. Stronger Claude/GPT-style models will keep getting better at generating Unity C#, Unreal C++, Godot scripts, ECS systems, tests, and gameplay prototypes directly. If XACE is positioned as "the AI that writes gameplay," it will be competing against general models and engine-specific copilots on their easiest terrain.

Surviving angle: XACE should not merely generate gameplay code. It should constrain, compile, simulate, hash, replay, rollback, and certify gameplay changes. The valuable claim is "generated gameplay that survives deterministic validation," not "generated gameplay."

### AI can directly generate UE5 projects

Risk: high. Models will increasingly scaffold UE5 projects, Blueprints, plugins, replication examples, GAS-style abilities, and editor tooling. A broad "XACE replaces Unreal" or "XACE makes UE5 projects from prompts" story will be weak.

Surviving angle: use Unreal as a rendering/content host while XACE owns a deterministic gameplay core and validation artifacts. The adapter in `adapters/unreal` supports this direction more than it supports engine replacement.

### AI can generate debugging tools

Risk: medium to high. Generic inspectors, log parsers, overlays, and debug panels can be generated quickly by future models.

Surviving angle: XACE debugging must be attached to privileged runtime facts: tick hashes, mutation transactions, replay divergence, SGC schedules, rollback snapshots, and cross-engine state comparison. Generic UI panels are not enough.

### AI can generate multiplayer templates

Risk: high for templates, lower for proof. Future models can generate client prediction, input buffers, lockstep examples, rollback loops, and reconciliation code.

Surviving angle: multiplayer correctness is not the same as multiplayer code. XACE could matter if it proves desync detection, rollback replay, deterministic lockstep, and authoritative simulation. Today this is not proven because `packages/network-core/tests/test_desync_detection.rs:86` failed in the audited run.

### AI can reduce need for XACE UI/workflow

Risk: high. If developers can ask their IDE/engine assistant for changes directly, a separate Builder UI becomes less necessary unless it provides proof, guardrails, and repeatable validation.

Surviving angle: Builder should become a control plane for schema diffs, validation, replay, proof artifacts, engine sync, and mutation recovery. It should not be mainly a chat box with panels.

### AI makes XACE valuable as infrastructure instead

This is the best future for XACE. As AI generates more code, the need for deterministic validation, rollback, replay, schema contracts, migration, and cross-engine correctness may increase. XACE survives if it becomes the safety and proof layer under AI game development.

## 7. Claims XACE can safely make today

Safe claim: XACE is an in-progress schema-driven gameplay-core platform.

Evidence: `README.md`, `Cargo.toml`, `packages/core`, `packages/runtime-core`, `packages/system-graph-compiler`, `packages/builder-workspace`.

Caveat: "In-progress" must stay in the claim.

Safe claim: XACE can run a local Rust gameplay runtime from CGS for supported built-in systems and produce deterministic world hashes.

Evidence: `RuntimeOrchestrator::tick` in `packages/runtime-core/src/runtime_orchestrator.rs:273`, `PhaseOrchestrator::tick_with_guard` in `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs:159`, passing `cargo test -p xace-runtime-core --lib`.

Caveat: Supported built-ins only; not arbitrary generated gameplay systems.

Safe claim: XACE has a real System Graph Compiler CLI/library for validating and scheduling system graphs.

Evidence: `SgcPipeline::compile_and_verify` in `packages/system-graph-compiler/src/sgc_pipeline.rs:72`, CLI in `packages/system-graph-compiler/src/main.rs:55`, passing `cargo test -p xace-system-graph-compiler`.

Caveat: Runtime does not yet use persisted SGC plans as the authoritative execution plan.

Safe claim: XACE has apply-time mutation rollback for local runtime state.

Evidence: `MutationGate::apply_all_with_runtime_state` in `packages/runtime-core/src/mutation_gate/mutation_gate.rs:397`, passing runtime mutation tests.

Caveat: Do not call it production-grade live-edit safety until fuzzing, concurrency, external workloads, and engine effects are proven.

Safe claim: XACE has engine adapter source for Godot, Unity, and Unreal.

Evidence: `adapters/godot/xace_adapter.gd`, `adapters/unity/XaceTransport.cs`, `adapters/unreal/XaceTransport.cpp`.

Caveat: Current audit did not prove installed-editor execution across those engines.

Safe claim: XACE has a constrained prompt-to-CGS mutation path with certified scenario smokes.

Evidence: `SessionManager.run_pil` in `packages/builder-workspace/server/session_manager.py:331`, `tools/prompt_pipeline_smoke.py`.

Caveat: The smoke explicitly uses fake SGC wiring; do not claim arbitrary prompt-to-game.

Safe claim: XACE quick editor-free launch certification currently passes.

Evidence: `python tools/certify_launch.py --quick --target-dir target-codex-reality-audit-certify` passed 13 checks in this audit.

Caveat: Installed engine validation was skipped, and the full Rust workspace test suite did not pass.

## 8. Claims XACE must not make yet

- "Build any game from prompt."
- "Turns arbitrary prompts into production gameplay."
- "Production-ready multiplayer for all game types."
- "Works across all engines."
- "Runs the same finished game across Unity, Godot, and Unreal."
- "Replaces Unity, Unreal, or Godot."
- "Complete UE5 replacement."
- "Runtime executes arbitrary SGC-compiled gameplay systems."
- "Fully production-ready deterministic runtime across platforms."
- "Studio-grade debugging."
- "Finished-game export."
- "Import existing engine gameplay automatically."
- "Secure hosted provider/BYOK system fully validated in production."
- "All tests pass."
- "Commercial launch ready."

## 9. Launch proof readiness

### Build a multiplayer combat system rapidly

Current readiness %: 30%.

Evidence: `packages/runtime-core/src/builtin_systems.rs` includes combat-relevant built-ins such as movement, AI, damage, and death. `packages/network-core` contains session, prediction, rollback, desync, and replication primitives. `tools/networked_runtime_smoke.py` is part of quick certification. Prompt/GDE plumbing exists through `SessionManager.run_pil` and `_apply_via_gde`.

Missing pieces: clean `network-core` tests, real authoritative combat demo, real client prediction/reconciliation loop, rollback replay proof under combat load, latency/loss simulation, engine-side input and visual proof, and a prompt corpus that builds combat without handholding.

Exact files/modules involved: `packages/runtime-core/src/builtin_systems.rs`, `packages/network-core/src`, `packages/network-core/tests/test_desync_detection.rs`, `packages/runtime-core/src/engine_bridge.rs`, `packages/builder-workspace/server/session_manager.py`, `tools/networked_runtime_smoke.py`, `examples/zombie-chase`.

What must be done before public demo: fix the failing desync/resync test, define one narrow combat schema, run two simulated clients against one authoritative runtime, show deterministic replay after rollback, then mirror the same session into at least one real engine adapter.

### Catch a rollback/determinism bug before engine integration

Current readiness %: 65%.

Evidence: `cargo test -p xace-runtime-core --lib` passed 589 tests. `RuntimeOrchestrator::record_replay_hash_log` and `validate_recorded_replay_from_cgs` exist. `MutationGate::apply_all_with_runtime_state` performs rollback on apply failure. `PhaseOrchestrator::tick_with_guard` wires determinism guard hooks into runtime ticking.

Missing pieces: polished public repro, persisted proof artifacts, cross-platform repeat, regression fixture, and a small UI/debugger flow that explains the mismatch without requiring source-code reading.

Exact files/modules involved: `packages/runtime-core/src/runtime_orchestrator.rs`, `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs`, `packages/runtime-core/src/determinism_guard`, `packages/runtime-core/src/mutation_gate`, `packages/runtime-core/src/snapshot_engine`, `tools/determinism_proof.py`, `tools/mutation_atomicity_proof.py`.

What must be done before public demo: create one intentionally bad mutation/system ordering case, show the hash divergence or rollback failure before engine integration, show the exact blocked/rolled-back transaction, and show the same CGS succeeding after the fix.

### Run the same gameplay logic across Unity and Godot

Current readiness %: 45%.

Evidence: Unity adapter source exists in `adapters/unity/XaceTransport.cs` and `adapters/unity/XaceDeltaApplicator.cs`. Godot adapter source exists in `adapters/godot/xace_adapter.gd` and `adapters/godot/xace_delta_applicator.gd`. Runtime engine protocol exists in `packages/runtime-core/src/engine_protocol.rs`. `tools/three_engine_runtime_smoke.py` and runtime bridge smoke exercise editor-free paths.

Missing pieces: a current installed Unity and Godot certification run, the same CGS driving both engines, side-by-side hash/status proof, matching input mapping, matching asset binding, packaged adapter setup docs, and a video/demo artifact.

Exact files/modules involved: `adapters/unity`, `adapters/godot`, `packages/runtime-core/src/engine_protocol.rs`, `packages/runtime-core/src/tcp_server.rs`, `packages/engine-adapter/src`, `tools/three_engine_runtime_smoke.py`, `tools/certify_launch.py`.

What must be done before public demo: run `tools/certify_launch.py --installed-engines` for at least Unity and Godot, capture reports, then run one CGS scene with identical runtime tick hashes and visible mirrored state in both engines.

## 10. Codebase architecture map

Main folders and modules:

- `packages/core`: shared Rust contracts for schema, UCL components, events, mutations, runtime snapshots, deltas, wire messages, and asset references.
- `packages/runtime-core`: main deterministic runtime. It loads CGS, builds a phase plan, runs built-in systems, applies mutations, snapshots world state, computes hashes, records replay hash logs, bridges engine clients, and exposes runtime/control servers.
- `packages/system-graph-compiler`: SGC compiler and CLI. It constructs system graphs, detects cycles, resolves dependencies, segments phases, checks conflicts, schedules systems, and evaluates parallelization safety.
- `packages/engine-adapter`: shared adapter protocol, transports, FFI, delta sync, compression, and resync logic. This area currently has failing tests.
- `packages/engine-feedback`: feedback message validation, routing, logging, replay, visibility queries, and aggregation.
- `packages/network-core`: networking primitives for sessions, authority, input buffering, prediction, rollback bookkeeping, desync detection, and replication.
- `packages/save-engine`: save/checkpoint/replay/migration/cloud-oriented primitives.
- `packages/observability`: metrics, traces, tick ring buffers, crash handling, health checks, and debugging support.
- `packages/schema-factory`: Python schema registry, validation, diffs, versioning, migrations, and blueprint tooling.
- `packages/gde`: Python Game Definition Engine for schema mutation planning/execution, path addressing, consistency validation, and CGS management.
- `packages/prompt-intelligence`: prompt intake, context retrieval, safety guards, mutation planning, LLM orchestration, code generation scaffolds, and validation-loop concepts.
- `packages/inference`: provider/model routing, caching, budget control, and provider abstraction.
- `packages/builder-workspace`: Builder UI in TypeScript plus Python server/session manager.
- `adapters/godot`: Godot GDScript runtime bridge, entity manager, input collector, delta applicator, debug HUD, and setup files.
- `adapters/unity`: Unity C# transport, delta applicator, input collector, console widget, setup menus, and bootstrap scripts.
- `adapters/unreal`: Unreal C++ transport, delta applicator, input collector, console widget, live validation commandlet, and module files.
- `tools`: certification, smoke tests, launch helpers, schema validators, prompt pipeline checks, provider readiness checks, determinism/mutation proofs, and engine/dev scripts.
- `examples/zombie-chase` and `projects/zombie_chase`: demo/reference project material.
- `docs`: product claims, readiness plans, schema/export docs, and design docs. Some docs are strong; several are stubs or stale.

Data flow:

1. A user or prompt starts in Builder UI/server.
2. Builder routes prompt work through provider/PIL/GDE paths: `SessionManager.run_pil`, `_apply_via_gde`, and CGS session persistence.
3. CGS is validated and passed to SGC through `SessionManager.compile_sgc_plan`.
4. SGC compiles and validates an execution plan.
5. Builder can persist/validate SGC proof bundles, but the runtime currently loads CGS and builds a built-in-filtered phase plan in `packages/runtime-core/src/cgs_loader.rs`.
6. Runtime ticks through `RuntimeOrchestrator::tick`, `PhaseOrchestrator::tick_with_guard`, built-in systems, mutation gate, event bus, snapshot engine, and determinism guard.
7. Runtime emits snapshots/deltas/playback commands through engine protocol/bridge.
8. Godot/Unity/Unreal adapters connect to runtime, send input/feedback, and mirror runtime state into engine objects.
9. Feedback can flow back into runtime/Builder through engine feedback message paths.
10. Proof tools and smokes validate parts of this path, but not yet the whole product promise end to end.

Where AI/prompting enters: `packages/prompt-intelligence`, `packages/inference`, `packages/builder-workspace/server/session_manager.py`, and `tools/prompt_pipeline_smoke.py`.

Where schemas are compiled/validated: CGS validation lives in `packages/core`, `packages/schema-factory`, `docs/schemas`, and `tools/cgs_schema_validate.py`; system graphs are compiled in `packages/system-graph-compiler`; Builder-side SGC validation is in `packages/builder-workspace/server/sgc_plan_validator.py`.

Where engine adapters live: engine-side source is under `adapters/godot`, `adapters/unity`, and `adapters/unreal`; shared protocol/adapter logic is under `packages/engine-adapter` and runtime bridge/protocol code under `packages/runtime-core/src`.

Where tests live: Rust unit/integration tests are embedded under package `src` files and `tests` folders; Python smoke/proof tests are under `tools`; Builder tests are under `packages/builder-workspace`; determinism fixtures live under `tests/determinism`.

## 11. Test and proof quality

Unit tests: strong in `xace-runtime-core` and `xace-system-graph-compiler`. In this audit, `cargo test -p xace-runtime-core --lib` passed 589 tests, and `cargo test -p xace-system-graph-compiler` passed its targeted suite. Many Rust packages have meaningful embedded tests.

Integration tests: meaningful but uneven. `tools/certify_launch.py --quick` passed 13 editor-free checks, including runtime binary, SGC binary, SGC CLI smoke, Builder Python modules, Builder TypeScript production build, forbidden-claims check, prompt pipeline smoke, provider readiness smoke, onboarding smoke, asset playback smoke, runtime bridge smoke, networked runtime smoke, and save runtime replay. The prompt smoke is explicitly not full SGC proof.

Golden tests: present for determinism/hash/replay-style behavior, especially in runtime-core. Missing: public, durable, cross-machine golden artifacts for launch claims.

Engine tests: source and optional certification paths exist. Current audit did not run installed Godot/Unity/Unreal validation. `tools/certify_launch.py` explicitly skips that without `--installed-engines`.

Multiplayer tests: partial and currently not clean. `packages/network-core` has real tests, but `cargo test -p xace-network-core` failed in `packages/network-core/tests/test_desync_detection.rs:86`.

Determinism tests: good local runtime evidence. Runtime-core tests passed, including deterministic torture coverage. Missing: cross-platform CI matrix, installed-engine determinism comparison, and long-running soak proof.

Rollback tests: good local MutationGate proof. Missing: network rollback world restore proof, hostile mutation fuzzing, and engine-side side-effect rollback proof.

Real-world demo tests: incomplete. `examples/zombie-chase` and project/demo material exist, and quick certification passes editor-free smokes, but this audit did not verify a real public demo path in an installed engine.

Current failing proof points:

- `cargo test --workspace --target-dir target-codex-reality-audit` failed because `xace-engine-adapter` tests failed.
- `cargo test -p xace-engine-adapter --lib` failed 2 tests: `compression_ratio_high_when_mostly_unchanged` in `packages/engine-adapter/src/delta_sync/delta_compressor.rs:545` and `compressor_eliminates_unchanged_fields_at_100_entities` in `packages/engine-adapter/src/tests/test_delta_sync_integration.rs:562`.
- `cargo test -p xace-network-core` failed `resync_engine_retries_and_acknowledges_sessions` in `packages/network-core/tests/test_desync_detection.rs:86`.

Missing test/proof categories:

- Real installed Unity/Godot/Unreal certification reports.
- Full clean workspace test run.
- Cross-platform determinism matrix.
- Long-running multiplayer desync/rollback soak.
- Real hosted provider prompt test with non-fake SGC proof.
- Larger prompt corpus with expected CGS diffs.
- Security review for hosted/provider/credential paths.
- Performance budgets for runtime, adapters, Builder, and networking.
- External demo scripts that a stranger can run without repo knowledge.

## 12. Production readiness score

| Area | Score | Reason |
|---|---:|---|
| Core architecture | 7/10 | Coherent schema-runtime-compiler-adapter architecture. The main architectural gap is SGC-to-runtime execution authority. |
| Determinism | 6/10 | Strong local runtime evidence, real hashing/replay hooks, passing runtime tests. Not yet cross-platform or engine-proven. |
| Rollback | 5/10 | MutationGate rollback is real. Network rollback and engine side-effect rollback are not production-proven. |
| Multiplayer | 3/10 | Useful primitives exist, but network-core has a failing desync/resync test and no full public multiplayer proof. |
| Engine portability | 4/10 | Three adapter source trees exist. Installed-engine validation was skipped, and adapter package tests are not clean. |
| Prompt pipeline | 4/10 | Constrained prompt path works for smoke scenarios. Fake SGC wiring and lack of arbitrary prompt support limit claims. |
| UI/UX | 4/10 | Builder builds and has relevant panels. It is not yet proven as a polished public workflow or expert debugger. |
| Debugging | 4/10 | Runtime status, hashes, feedback, observability, and UI panels exist. Studio-grade debugging is not proven. |
| Docs | 5/10 | README and claims matrix are honest and useful. Some docs are stale or stub-only. |
| Testing | 5/10 | There are many serious tests and smokes. The full workspace is not clean, and engine/multiplayer proofs are incomplete. |
| Demo readiness | 4/10 | Good ingredients for a narrow proof demo. Not ready for broad public "build a game" demo. |
| Commercial launch readiness | 3/10 | Too many caveats for commercial launch: failing tests, skipped installed engines, narrow prompt proof, partial multiplayer, and unclear hosted-provider proof. |

## 13. Strategic recommendation

Pick **B. Deterministic gameplay infrastructure** as the primary direction.

The strongest evidence in the code is not that XACE can out-generate future AI models. It is that XACE can become the deterministic validation layer beneath AI-assisted game development: CGS as the contract, SGC as the scheduler/proof compiler, runtime-core as the deterministic simulator, MutationGate as the recovery mechanism, replay/hash validation as the trust artifact, and engine adapters as the presentation layer.

The best product sentence is: XACE is a deterministic gameplay-core infrastructure layer that lets AI and humans change gameplay safely, validate it before engine integration, and mirror it into multiple engines.

Secondary directions that fit this:

- **C. Multiplayer/rollback validation layer**: high-value if the failing network/desync work is fixed and proven.
- **D. Engine-portable gameplay logic layer**: strategically powerful, but only after real Unity/Godot or Unity/Unreal proof.
- **E. Game-dev workflow platform**: viable only if the workflow is centered on proof, replay, rollback, schemas, and engine sync.

Avoid **A. AI game generator** as the main identity. Future models will attack that directly, and XACE does not currently prove arbitrary prompt-to-game anyway.

## 15. Final verdict

Is XACE still worth finishing?

Yes, but only if it is finished as deterministic gameplay infrastructure, not as a broad AI game generator. The codebase has enough real runtime/compiler/rollback/replay/adapter work to be worth continuing. It does not have enough proof to support the bigger marketing story yet.

What is the strongest version of XACE?

The strongest version is a proof-oriented gameplay-core layer: CGS -> SGC -> deterministic runtime -> mutation rollback -> replay/hash validation -> engine adapters. In that version, AI models generate proposed changes, but XACE decides whether those changes are valid, deterministic, recoverable, and portable.

What is the weakest version that will likely die?

The weakest version is a chat-first "build any game from prompt" tool with a custom UI and broad engine-replacement language. Future AI models and engine-native assistants will crush that positioning, especially if XACE cannot prove arbitrary gameplay, production multiplayer, and installed-engine portability.

What should be demonstrated publicly first?

Demonstrate catching a rollback/determinism bug before engine integration. That is closest to what the code already proves, and it is harder for generic AI generation to trivialize. The demo should show a bad mutation or nondeterministic system, the exact detected divergence or rollback, the proof artifact/hash, and the fixed run.

What should be stopped immediately?

Stop building or implying broad "any game from prompt" claims, engine replacement language, finished-game export claims, arbitrary generated-system runtime claims, production multiplayer claims, and UI polish that does not strengthen proof/replay/rollback/validation. The next work should close proof gaps: runtime loading of persisted SGC plans, clean workspace tests, network desync fix, installed-engine certification, and one public deterministic validation demo.
