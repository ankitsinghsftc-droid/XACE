> XACE is now in finish-and-prove mode. No new feature families should be added until the existing launch-critical systems are integrated, hardened, validated under production-shaped pressure, and represented honestly in documentation and product claims.

# XACE Production Readiness Master Plan

Audit date: 2026-06-06

This is the single authoritative finish-and-prove plan for XACE production readiness. It is deliberately stricter than the existing launch map. It distinguishes interfaces, partial implementations, smoke-tested wiring, local validation, integrated production paths, and externally proven product claims.

No implementation work should start until this file is used as the execution contract.

The commercial launch model that this plan must target is frozen in
`docs/XACE_COMMERCIAL_SCOPE.md`. Scope changes to local-first status, BYOK
prompting, supported engine targets, paid tiers, licensing assumptions, update
channels, telemetry defaults, or support workflow require a newer signed scope
record.

## A. Executive Summary

XACE's current honest product boundary is a developer platform for canonical gameplay schemas, deterministic-ish runtime foundations, mutation-gated CGS editing, semantic engine adapter contracts, AI-assisted supported CGS mutations, project creation, adapter installation/export, and local certification tooling.

What appears strong:

- The repository has real Rust/Python/TypeScript modules for CGS, GDE, runtime core, adapters, provider settings, prompt apply, network primitives, save/snapshot primitives, asset references, and certification tooling.
- The Godot, Unity, and Unreal adapter source trees exist and expose handshake, input, delta application, and feedback paths.
- The Builder has a real local server/UI workspace under `packages/builder-workspace`, project creation/open/import endpoints, provider readiness gating, and prompt apply through GDE when available.
- Runtime tick flow exists in `packages/runtime-core/src/runtime_orchestrator.rs` and `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs`.
- Snapshot, replay, hashing, RNG, network, save, and feedback modules have unit/smoke tests.
- `tools/certify_launch.py` provides a useful editor-free certification command and optional installed-engine validation hooks.
- Task 156 completed an open CGS export format design: `docs/CGS_SCHEMA_EXPORT_FORMAT.md`, `docs/schemas/xace-cgs-export.schema.json`, and the standalone no-dependency validator `tools/cgs_schema_validate.py`.

What is incomplete or unproven:

- Live deterministic enforcement is now integrated into the local runtime tick path and has a Windows proof bundle, but cross-engine and cross-platform determinism proof is still pending.
- `MutationGate` now has local apply-time atomic rollback for entity/component/queue state and orchestrator-provided event/RNG state, plus local five-operation/stress proof artifacts under `.xace/proof/mutation-atomicity/20260613T023553Z/`.
- SGC CLI repair and validation are complete at local integration-test level. The CLI now accepts the CGS SystemDefinition-compatible JSON envelope, emits structured JSON errors, Builder validates mutation-safety/rollback compatibility before accepting plans, Builder writes canonical schema-backed `.xace/execution_plans/<cgs_hash>.plan.json` artifacts with component access sets, system metadata, loadability metadata, and proof references, Builder persists SGC proof bundles under `.xace/proof/sgc/<hash>/`, the standalone runtime can require and compatibility-check persisted SGC plans before tick zero, CGS-derived compatibility mode rejects unsupported systems with proof instead of filtering them, and the runtime registry can execute supported generated systems through a deterministic ABI covering inputs, reads, writes, events, RNG, errors, and rollback hooks. Generated Rust source now has a local safe compile/sign/register gate covering SystemSpec/runtime ABI validation, unsupported generated-system rejection, deterministic static checks, Cargo sandbox checking, real SGC compilation, signed compile artifacts, and runtime signature/policy verification. Runtime ticks now preserve loaded SGC group metadata and can prove per-tick schedule snapshots match the persisted plan across replay. `tools/sgc_runtime_proof.py` writes retained `.xace/proof/sgc-runtime/<run-id>/` proof for a real CGS-to-SGC-to-runtime tick-hash replay path, and `tools/cgs_end_to_end_proof.py` writes retained `.xace/proof/cgs-e2e/<run-id>/` proof for generated CGS creation, real SGC compile, strict runtime load, deterministic tick replay, runtime replay validation, rollback failure restoration, and adapter snapshot output. Prompt certification invokes the real SGC binary for accepted structural prompt proof, the hosted CI workflow is configured to retain `.xace/proof/cgs-e2e-ci/`, and a 100-system compile benchmark is in place; broader production runtime integration remains gated by plugin/external executor contracts, release-wide artifact signing, and release CI artifact review.
- Prompt proof is narrow, but Tasks 35 through 37 plus Tasks 42, 44, 45, 46,
  47, 48, 50, 51, 52, 53, 54, 55, 56, 57, and 58 now give it a shared product
  boundary, deterministic pre-PIL gate, bounded clarification loop for
  ambiguous classifier routes, structured preview approval before persistence,
  covered prompt-apply rollback recovery, structured apply validation feedback,
  reviewed corpus and local benchmark artifacts, measurable threshold gates,
  covered prompt-security attack artifacts, inference-adapter provider-call
  boundary enforcement, provider timeout/retry and token/cost proof, exact
  provider health/stale-policy proof, opt-in BYOK live-provider proof gating,
  automatic model route-evidence gates, explicit Builder provider UX states for
  no key, invalid key, stale health proof, quota failure, rate limit, and
  provider outage, and a deterministic no-LLM path for certified player-speed
  value edits with zero provider, provider-readiness, PIL, or LLM calls.
  `docs/prompt_capability_matrix.json` and `docs/PROMPT_CAPABILITY_MATRIX.md`
  define the certified supported, constrained, clarification-required, blocked,
  unsupported, and experimental prompt categories, Builder serves the same
  matrix through `GET /api/prompt/capability-matrix`, and
  `tools/prompt_capability_matrix_check.py` keeps docs, Builder, and prompt
  fixtures aligned. Task 46 through Task 58 proof remains local deterministic
  evidence unless explicitly described as live BYOK proof; live BYOK provider
  reports, hosted-provider/runtime threshold execution, and broader security
  review remain pending.
- Import currently wraps an engine project with a new XACE project and records `engine_project_path`; it does not reverse-engineer engine-native gameplay into CGS.
- Export currently copies adapter source into `.xace/exports/<target>`; it is not final platform packaging.
- Provider settings now store API keys through an OS credential backend: Windows Credential Manager, macOS Keychain, and Linux Secret Service/libsecret via `secret-tool`. The JSON settings file stores metadata, fingerprints, and credential references only. Linux can use an unsafe file fallback only when explicitly enabled for development/testing. Hosted model IDs start unresolved unless inference-owned provider discovery or user entry supplies an exact model. Builder, PIL, GDE, and tools now have a CI/certification gate preventing provider execution outside `packages/inference`; provider calls through `InferenceAdapter` also record timeout, retry, rate-limit, backoff, failure-category, final-outcome, deterministic user-facing error telemetry, and redacted prompt/completion/cache token, cost, model, tier, latency, request ID, cache, deterministic, and failure accounting artifacts for local simulated paths.
- Multiplayer modules provide primitives, not a complete user-facing multiplayer flow with chaos proof.
- Cross-engine portability is not proven as a single CGS-owned vertical slice with movement, combat, inventory, save/load, rollback, replay, semantic bindings, and multiplayer across Godot, Unity, and Unreal.

Contradictions requiring correction:

- Determinism comments claim runtime-wide enforcement; live runtime code does not yet enforce it.
- MutationGate comments and implementation now agree on local apply-time rollback; remaining work is broader transaction/audit coverage beyond the local proof artifact.
- Prompt smoke names must read as contract/scenario smoke, not broad prompting proof; actual proof is only deterministic supported scenarios and GDE apply wiring.
- SGC "real integration" is no longer blocked by a non-compiling CLI, missing Builder proof persistence, wiring-only prompt certification, absent persisted-plan runtime loading, missing strict runtime compatibility checks, the absence of any generated-system registry execution path, the absence of a local generated-system execution ABI, the absence of a local safe generated-code compile/sign/register gate, the absence of local unsupported generated-system rejection, the absence of runtime schedule snapshot/replay proof for persisted plans, the absence of a local retained CGS-to-SGC-to-runtime proof command, or the absence of a local end-to-end CGS proof covering rollback failure and adapter snapshot output. It is still not a broad production runtime claim for arbitrary generated, plugin, or external systems until those executor contracts, release-wide signing, and release CI artifact review are complete.
- Engine live validation language in docs must not imply full portability, finished-game export, or arbitrary engine project import.

Before users should rely on XACE, the P0 finish work must remove split-brain state risks, enforce live determinism or narrow the claim, guarantee or narrow MutationGate atomicity, complete SGC integration proof, remove fake confidence, replace credential handling, and correct public claims.

A credible initial launch can be a narrow, honest creator/developer alpha: supported templates, supported prompt mutations, local Builder, CGS persistence, one primary engine path plus adapter proofs, guarded errors, and reproducible certification artifacts.

World-class studio readiness is much larger: years of compatibility discipline, OS/keychain security, CI matrices, cross-platform deterministic replay proof, deep debugging, source-control discipline, robust multiplayer topologies, engine-native import/migration workflows, large-scale performance baselines, and external security review.

## B. Repository Reality Audit

Evidence commands run during this audit:

- `rg --files -g '!target*/**' -g '!**/target/**' -g '!node_modules/**'`
- `Get-Content docs/LAUNCH_READINESS_MAP.md`
- `Get-Content` on runtime, mutation, determinism, prompt, provider, project, adapter, and certification files.
- `cargo test -p xace-system-graph-compiler --target-dir target-codex-production-plan-sgc`

Focused SGC result:

- Updated after Task 34. The binary target builds, `tools/sgc_cli_smoke.py` passes the success and structured error-output contract, and `tools/sgc_cli_integration.py` covers compile success/failure, 20 generated systems, cycle, unknown dependency, conflict serialization, runtime-load validation contract, adapter version fields, and a 100-system compile benchmark. Builder sends the CGS SystemDefinition-compatible input envelope, validates the returned plan for mutation safety and rollback compatibility, surfaces actionable SGC failures in the Builder error path, writes canonical schema-backed `.xace/execution_plans/<cgs_hash>.plan.json` artifacts with component access sets, system metadata, adapter/migration loadability metadata, and proof references, and persists `.xace/proof/sgc/<hash>/` bundles. The standalone runtime now supports `--require-sgc-plan`, compatibility-checks persisted plans against CGS/runtime identity before tick zero, uses persisted SGC groups as its schedule in strict mode, rejects stale parsed persisted plans with `.xace/proof/sgc-migration/<cgs_hash>.json` invalidation reports and no silent downgrade, rejects unsupported CGS-derived systems with `.xace/proof/runtime-compatibility/<cgs_hash>.json` instead of filtering them, rejects persisted parallel component hazards, registers/executes generated systems through a deterministic ABI that normalizes executor specs, validates inputs/events/RNG/errors/rollback hooks, and currently supports numeric mutation plus RNG event emission. Generated Rust source now passes through a local safe compile/sign/register gate with unsupported-API rejection, deterministic static checks, Cargo sandbox checking, real SGC compilation, signed compile artifacts, and runtime signature/policy verification. Runtime schedule snapshots preserve SGC group IDs, execution indexes, parallel flags, serialization constraints, dependency metadata, component access sets, and per-tick world hashes, and the real-binary schedule smoke proves those snapshots match the persisted plan across replay. `tools/sgc_runtime_proof.py` creates retained `.xace/proof/sgc-runtime/<run-id>/` evidence by invoking the real SGC binary, persisting the emitted plan, loading it through the real runtime in strict SGC mode, and comparing tick hash logs across replay. `tools/cgs_end_to_end_proof.py` creates retained `.xace/proof/cgs-e2e/<run-id>/` evidence for generated CGS creation, real SGC compilation, strict runtime load, deterministic replay, runtime replay validation, rollback failure restoration, and adapter snapshot output; `.github/workflows/xace-scope.yml` retains the same proof shape under `.xace/proof/cgs-e2e-ci/`. SGC `parallel=true` groups are explicitly treated as parallel-eligible schedule metadata under the current standalone runtime policy `deterministic_sequential`, with `parallel_group_worker_threads=false` exposed in startup/status/snapshot reports and covered by unit and benchmark evidence. This does not yet prove broad production integration for arbitrary generated, plugin, or external systems because those executor contracts and release-wide signing remain pending.

Reality table:

| Area | Claimed Capability | Actual Evidence | Implementation Status | Missing Work | Risk Level | Blocks Alpha? | Blocks Beta? | Blocks Launch? | Blocks Studio Readiness? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CGS | Canonical gameplay schema | `packages/core/src/schema/**`, `game.cgs.json`, `packages/project-system/project_templates.py`, `packages/builder-workspace/server/cgs_persistence.py`, `docs/CGS_SCHEMA_EXPORT_FORMAT.md`, `tools/cgs_schema_validate.py` | Partial implementation, local persistence, and open export format contract documented | Implement exporter that stamps `format`/`format_version` and canonical 64-char hash; schema validation depth, migrations, authority/versioning, claims audit | High | Yes, if corruptible | Yes | Yes | Yes |
| GDE | Safe mutation apply | `packages/gde/src/**`, `SessionManager.apply_via_gde()`, server tests | Partial integrated path | Harden conflict handling and transaction proof; direct Builder CGS fallback has been removed from the product path | High | Yes | Yes | Yes | Yes |
| Runtime | Tick-driven ECS runtime | `runtime_orchestrator.rs`, `phase_orchestrator.rs`, `builtin_systems.rs` | Locally runnable partial runtime | Determinism integration, scale, live authority, error model | High | Yes | Yes | Yes | Yes |
| Live tick path | Authoritative per-tick lifecycle | `RuntimeOrchestrator::tick()`, `PhaseOrchestrator::tick()` | Integrated tick path exists | DeterminismGuard, hashes, replay hooks, atomic rollback, network authority | Critical | Yes | Yes | Yes | Yes |
| MutationGate | Only mutation path and atomicity | `mutation_gate.rs` | Apply-time rollback implemented locally with hash validation, diagnostics, nested-transaction rejection, stress tests, and proof artifacts | Broader transaction/audit integration and CI retention | Critical | Yes | Yes | Yes | Yes |
| Snapshots | Capture/restore world | `snapshot_engine.rs`, `world_snapshot.rs`, snapshot tests | Partial local implementation | Queue/RNG/event state completeness, live retained snapshots, cross-runtime proof | High | No, if claim narrowed | Yes | Yes | Yes |
| Replay | Hash validation | `replay_validator.rs`, determinism tests | Isolated implementation | Live record/replay integration, input log, artifact format | High | No | Yes | Yes | Yes |
| Hashing | Per-world deterministic hash | `world_hasher.rs`, `snapshot_serializer.rs`, `runtime_orchestrator.rs` | Canonical 64-char SHA-256 live hash log integrated and exposed locally | Cross-engine/cross-platform hash compare harness | High | Yes, if determinism claimed | Yes | Yes | Yes |
| DeterminismGuard | Runtime enforcement | `determinism_guard.rs`, `phase_orchestrator.rs`, `runtime_orchestrator.rs` | Live tick/session ownership and boundary hooks integrated locally | External/runtime adapter proof and long-run CI artifact retention | Critical | Yes | Yes | Yes | Yes |
| RNG interception | Block illegal RNG | `rng_interceptor.rs`, `deterministic_rng.rs`, code checker | Runtime windows, `SystemContext` deterministic RNG, static gate, and failure tests exist | Native sandbox limits must remain non-overclaimed | High | Yes, if determinism claimed | Yes | Yes | Yes |
| Network-core | Lockstep, rollback, replication primitives | `packages/network-core/src/**`, tests | Primitive modules and tests | User-facing topology, runtime/adapter flow, chaos tests | High | No, if multiplayer not claimed | Yes | Yes | Yes |
| Rollback | Rollback bookkeeping | `network-core/src/prediction/rollback_manager.rs`, snapshots | Partial primitive | Live snapshot ring, restore validation, UX | High | No | Yes | Yes | Yes |
| Resync | Desync recovery | `network-core/src/synchronisation/resync_engine.rs`, adapter delta recovery | Partial primitive | End-to-end runtime/client proof | High | No | Yes | Yes | Yes |
| Replication | Interest/relevance | `network-core/src/replication/**` | Partial primitive | Integrated sessions, perf, mismatch handling | High | No | Yes | Yes | Yes |
| Engine adapters | Godot/Unity/Unreal bridge | `adapters/godot`, `adapters/unity`, `adapters/unreal`, `engine-adapter` | Adapter source and validation hooks exist | Versioned packages, installed-editor proof artifacts, long-run proof | Medium-High | No, if scoped | Yes | Yes | Yes |
| Godot integration | Live adapter | `adapters/godot/*.gd`, `tools/xace_godot_dev.py`, cert runner | More complete than others locally | Product packaging, user install, visual proof, cross-platform | Medium | No | Yes | Yes | Yes |
| Unity integration | Live adapter | `adapters/unity/*.cs`, editor validation command | Source and commandlet path | Installed Unity matrix, package import proof | Medium | No | Yes | Yes | Yes |
| Unreal integration | Live adapter | `adapters/unreal/*.cpp/.h`, commandlet validation | Source and commandlet path | Unreal version matrix, plugin packaging, automation reliability | Medium | No | Yes | Yes | Yes |
| Import | Existing engine project import | `ProjectCreator.import_engine_project()`, `/api/project/import-engine` | Wraps engine project and creates starter CGS | Assisted migration, honest detection/mapping, no reverse-engineering overclaim | High | Yes, if import advertised | Yes | Yes | Yes |
| Export | Adapter export | `/api/export/{target}` in `builder_server.py` | Copies adapter files only | Packaging boundary UX, preflight, engine-owned build handoff | Medium | No | Yes | Yes | Yes |
| Bidirectional edit loop | Runtime/editor edits | `engine_edit`, `engine_edit_commit`, `set_preview_component_field()` | Narrow preview field edits | Authority/version/conflict model, multi-step proof | High | No | Yes | Yes | Yes |
| SGC | System graph compiler | `packages/system-graph-compiler/src/**`, `tools/sgc_cli_integration.py`, `tools/runtime_sgc_plan_loader_smoke.py`, `tools/runtime_sgc_schedule_snapshot_smoke.py`, `tools/sgc_runtime_proof.py`, `tools/cgs_end_to_end_proof.py`, `tools/generated_system_safe_compile_smoke.py`, `sgc_plan_validator.py`, `tools/prompt_pipeline_smoke.py`, `docs/SGC_EXECUTION_PLAN_CONTRACT.md` | CLI input/error contract, persisted-plan schema/contract, Builder proof persistence, strict runtime persisted-plan loading and compatibility checks, stale-plan migration invalidation proof, no-silent-filtering CGS-derived compatibility proof, local generated-system ABI validation, local safe generated-code compile/sign/register gate, local unsupported generated-system rejection, runtime schedule snapshot/replay proof for persisted plans, retained local CGS-to-SGC-to-runtime tick-hash replay proof command, retained end-to-end CGS proof command with rollback failure and adapter snapshot output, explicit deterministic sequential runtime policy for SGC-parallel-eligible groups, two generated executor kinds registered/executed through the real runtime registry, real-binary prompt certification, plan validation, actionable failure surfacing, CI artifact-retention workflow, and 100-system benchmark exist locally | Plugin/external executor contracts, release-wide artifact signing, and release CI artifact review | Critical | Yes | Yes | Yes | Yes |
| Prompt pipeline | AI-assisted authoring | `PILPipeline`, deterministic prompt contract, provider gate, real-SGC prompt smoke, `docs/prompt_capability_matrix.json`, `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/prompt_corpus_100.jsonl`, `docs/prompt_corpus_manifest.json`, `docs/PROMPT_CORPUS.md`, `docs/prompt_launch_thresholds.json`, `docs/PROMPT_LAUNCH_THRESHOLDS.md`, `docs/prompt_security_cases.jsonl`, `docs/PROMPT_SECURITY_TESTS.md`, `docs/INFERENCE_ADAPTER_BOUNDARY.md`, `docs/HOSTED_PROVIDER_PROOF_GATE.md`, `docs/PROVIDER_ROUTE_EVIDENCE_POLICY.md`, `docs/PROVIDER_TIMEOUT_RETRY_POLICY.md`, `docs/PROVIDER_TOKEN_COST_ACCOUNTING.md`, `docs/PROVIDER_HEALTH_STALE_POLICY.md`, Builder `/api/prompt/capability-matrix`, `prompt_classifier_gate.py`, classifier clarification session/resolution records, prompt diff preview approval records, deterministic simple-edit records, prompt apply recovery reports, prompt apply feedback reports, prompt security reports, inference boundary reports, provider retry reports, provider accounting reports, provider health/stale-policy reports, hosted-provider proof reports when opted in, provider route-evidence reports, provider UX state tests, `tools/prompt_corpus_check.py`, `tools/prompt_corpus_benchmark.py`, `tools/deterministic_simple_edit_benchmark.py`, `tools/prompt_launch_threshold_check.py`, `tools/prompt_security_check.py`, `tools/inference_adapter_boundary_check.py`, `tools/hosted_provider_proof_gate.py`, `tools/provider_route_evidence_check.py`, `tools/provider_timeout_retry_check.py`, `tools/provider_token_cost_accounting_check.py`, `tools/provider_readiness_smoke.py` | Partial; supported examples, shared Task 35 matrix, Task 36 classifier gate, Task 37 bounded clarification loop, Task 42 structured approval gate, Task 44 covered rollback recovery, Task 45 structured apply feedback, Task 46 reviewed corpus, Task 47 local benchmark reports, Task 48 thresholds, Task 50 prompt-security attack cases, Task 51 inference boundary, Task 52 provider retry telemetry, Task 53 provider accounting, Task 54 provider health/stale-policy proof, Task 55 opt-in proof gate, Task 56 route-evidence gate, Task 57 provider UX-state coverage, and Task 58 deterministic simple-edit proof certify routing, no persistence without approval, no partial CGS/artifact/UI-success state on covered failures, non-generic Builder failure surfacing, versioned corpus coverage, generated JSON/Markdown/accounting benchmark artifacts, fail-below-threshold behavior, blocked/quarantined covered attack cases, CI failure for direct provider execution outside `packages/inference`, deterministic timeout/rate-limit/server/schema/quality provider-call telemetry, exact token/cost/request accounting, blocked stale/missing/invalid/untested provider settings, no live provider calls before opt-in, stale/unbenchmarked automatic route rejection, explicit no-key/invalid-key/stale-proof/quota/rate-limit/outage Builder states, and zero provider/provider-readiness/PIL/LLM calls for certified player-speed value edits | Live hosted provider/runtime threshold pass and broader security review | High | Yes, for prompt feature | Yes | Yes | Yes |
| Provider/model routing | BYOK and routing | `provider_settings.py`, `packages/inference/**`, `docs/INFERENCE_ADAPTER_BOUNDARY.md`, `docs/HOSTED_PROVIDER_PROOF_GATE.md`, `docs/PROVIDER_ROUTE_EVIDENCE_POLICY.md`, `docs/PROVIDER_TIMEOUT_RETRY_POLICY.md`, `docs/PROVIDER_TOKEN_COST_ACCOUNTING.md`, `docs/PROVIDER_HEALTH_STALE_POLICY.md`, `tools/inference_adapter_boundary_check.py`, `tools/hosted_provider_proof_gate.py`, `tools/provider_route_evidence_check.py`, `tools/provider_timeout_retry_check.py`, `tools/provider_token_cost_accounting_check.py`, `tools/provider_readiness_smoke.py` | Partial; readiness gate, exact provider health/stale-policy proof, opt-in live proof command, route-evidence gate for automatic choices, inference-adapter boundary, local provider timeout/retry telemetry proof, local provider token/cost accounting proof, and Builder provider UX states exist | Archived live hosted reports and hosted cost/reliability thresholds | High | Yes | Yes | Yes | Yes |
| Credentials storage | OS credential vault | `provider_settings.py`, `credential_store.py`, `STORAGE_NOTE`, `tools/security_secret_scan.py`, `tools/inference_adapter_boundary_check.py` | Locally implemented with platform tests plus provider-call boundary scanning | Secret scanning/redaction across logs/exports/snapshots/telemetry and real platform validation on all OSes | Critical | Yes | Yes | Yes | Yes |
| Templates | Starter projects | `project_templates.py` | Useful starter templates | Versioned compatibility and validation | Medium | No | Yes | Yes | Yes |
| Packages | Workspace/package surface | Cargo workspace, npm workspace | Partial | Versioning, install/update/rollback contracts | Medium | No | Yes | Yes | Yes |
| Asset registry | Asset references | `packages/asset-registry/**`, `packages/core/src/assets/**` | Partial and path mismatch resolved | Keep canonical path, tests/docs/imports | High | No | Yes | Yes | Yes |
| Semantic bindings | Events to playback | `semantic_binding.rs`, runtime playback command tests | Partial local path | Missing reference UX, engine mapping proof | Medium | No | Yes | Yes | Yes |
| Animation integration | Semantic triggers | `animation_component.rs`, adapter playback commands | Semantic only | Engine-native graph binding UI/proof | Medium | No | Yes | Yes | Yes |
| Audio integration | Semantic triggers | `audio_manifest.py`, feedback handlers, playback commands | Semantic only | Audio routing/binding proof | Medium | No | Yes | Yes | Yes |
| VFX integration | Semantic triggers | asset playback smoke, Vfx commands | Semantic only | Particle/VFX binding proof | Medium | No | Yes | Yes | Yes |
| UI flows | Builder app | `packages/builder-workspace/src/**` | Partial usable UI | Full UX pass, blocked states, visual validation | Medium | Yes for alpha | Yes | Yes | Yes |
| Lobby flows | Multiplayer lobby template | `multiplayer_lobby` template, network-core | Metadata starter only | Real lobby create/join/leave/reconnect UX | High | No if not claimed | Yes | Yes | Yes |
| Debugging tools | Tick/debug panels | `tick_debugger.ts`, runtime stats, feedback logs | Partial UI and logs | Timeline, diff, trace, reports | Medium | No | Yes | Yes | Yes |
| Certification | Launch checks | `tools/certify_launch.py` | Useful editor-free and optional engine checks | CI integration, artifact persistence, SGC inclusion, chaos/soak/fuzz | High | Yes | Yes | Yes | Yes |
| CI | Repeatable checks | No primary CI workflow observed in source audit | Not production-ready | GitHub/hosted CI, matrices, artifacts | High | No for private alpha | Yes | Yes | Yes |
| Benchmarks | Performance budgets | `packages/runtime-core/benches.rs` | Hash, snapshot capture, and RNG window benchmark target compiles | Run in CI and define regression budgets | High | No | Yes | Yes | Yes |
| Regression suites | Tests/smokes | `tests/**`, package tests, determinism proof tool | Partial plus local determinism proof/failure injection suite | Fuzz, corpus, CI, cross-platform and engine matrix | High | Yes for P0 | Yes | Yes | Yes |
| Documentation | Product claims | `docs/**`, `LAUNCH_READINESS_MAP.md`, README absent from audit output except file exists | Overclaim risk | Claims matrix and doc correction | Critical | Yes | Yes | Yes | Yes |

## C. Architectural Contradictions

### 1. Determinism Language Versus Live Enforcement

Finding:

- `determinism_guard.rs`, `world_hasher.rs`, `replay_validator.rs`, and `rng_interceptor.rs` implement strong-looking isolated pieces.
- `phase_orchestrator.rs` comments say per-tick step 3 computes `world_hash` via DeterminismGuard.
- Earlier audit state: `PhaseOrchestrator::tick()` ran systems, applied `MutationGate`, dispatched events, incremented `current_tick`, and returned `TickResult` without live guard/hash/replay/RNG integration.
- Batch 5-8 status: `RuntimeOrchestrator` now owns the live guard/interceptor/hash path for ticking sessions, phase/system boundaries call guard hooks, per-tick 64-char SHA-256 world hashes are logged, replay record/validate and snapshot restore hash validation are covered locally, and proof artifacts are generated under `.xace/proof/determinism/`.
- Remaining proof gap: cross-engine and cross-platform hash comparison is still pending.

Plan:

1. Complete: `RuntimeOrchestrator::tick()` emits a per-tick world hash from the same canonical hash path used by replay.
2. Complete: the canonical CGS/world/proof hash format is a 64-character lowercase SHA-256 digest. Short hash prefixes may appear only as non-authoritative UI/log/cache-key display labels.
3. Complete: `DeterminismGuard` ownership is in the live tick owner.
4. Complete: SGC execution-plan systems are registered with the guard before ticking.
5. Complete: guard hooks run around tick start, phase start, system execution, phase end, and tick end.
6. Complete: `RngInterceptor::open_window()` is integrated into sequential and SGC-parallel-eligible system execution paths.
7. Complete locally: generated systems that bypass deterministic RNG are statically rejected before runtime loading.
8. Complete locally: `SystemTime`, `Instant`, OS RNG, hash map iteration, unordered serialization, and unsupported floating-point edge cases are rejected for generated systems.
9. Complete locally: replay recording and validation modes are available through runtime control.
10. Complete locally: evidence is generated under `.xace/proof/determinism/<run-id>/`; latest run: `.xace/proof/determinism/20260612T041429Z/`.

### 2. MutationGate Atomicity Contradiction

Finding:

- Earlier audit state: `MutationGate::apply_all()` mutated `EntityStore` and `ComponentTableStore` as it went and discarded remaining queues on error without restoring already-applied state.
- Batch 9 status: `apply_all()` now delegates to an atomic rollback path that captures entity store, component tables, queues, and optional orchestrator-provided event/RNG state before applying the batch.
- Batch 10 status: nested/concurrent apply transactions are explicitly rejected, apply-time entity/JSON checks fail inside the transaction, five-operation op3 failure, stress, malformed JSON, missing entity, and component-table failure tests assert exact rollback, and proof artifacts exist under `.xace/proof/mutation-atomicity/20260613T023553Z/`.
- On apply-time failure, the rollback path restores the captured state, validates that the post-rollback canonical world hash equals the pre-batch hash, preserves a structured failure diagnostic, and returns an actionable `XaceError`.

Plan:

1. Complete: immediately correct docs/comments so no user or engineer reads old behavior as atomic.
2. Complete: implement pre-apply rollback capture around each batch in the production path.
3. Complete locally: on failure, restore exact entity store, component tables, queues, event state, RNG/interceptor state, and replay-visible state available to the mutation apply call.
4. Complete: verify restored hash equals pre-batch hash.
5. Complete: include failing operation index, type, path/entity/component, and rollback status in diagnostics.
6. No longer needed for the local apply path: the contract is implemented rather than narrowed.
7. Complete locally: five-operation proof artifact and stress tests exist; latest proof run: `.xace/proof/mutation-atomicity/20260613T023553Z/`.

### 3. AI Capability Claims Versus Prompt Proof

Finding:

- `tests/fixtures/prompt_pipeline_contract.py` proves three supported prompts: set player speed, add inventory component, add pickup actor.
- It blocks one too-broad arbitrary full-game prompt.
- `test_prompt_pipeline_e2e.py` uses a fake-SGC wiring-test-only helper, isolated to Builder server tests. `tools/prompt_pipeline_smoke.py` uses `DeterministicPromptPipeline` and the real compiled SGC binary.
- Task 35 now defines the shared prompt capability matrix in `docs/prompt_capability_matrix.json`, documents it in `docs/PROMPT_CAPABILITY_MATRIX.md`, and exposes it from Builder through `GET /api/prompt/capability-matrix`.
- Task 36 now gates prompts with `prompt_classifier_gate.py` before PIL, mutation planning, or provider calls. Easy certified prompts may continue; ambiguous, unsupported, and adversarial prompts return classifier-bearing `pil_result` responses without pending transactions.
- Task 37 now turns ambiguous classifier routes into bounded prompt clarification sessions. Builder records the selected resolution, blocks `pil_apply` while a classifier clarification is pending, and does not generate a mutation from ambiguous wording without that recorded answer.
- Task 42 now attaches structured prompt diff previews covering CGS, system, asset, SGC, runtime, and cost sections, and rejects `pil_apply` persistence without the matching explicit approval or an audited test-mode override.
- Provider readiness gates prompts before PIL, automatic model routing is evidence-gated, and an opt-in BYOK hosted-provider proof command exists, but real hosted provider prompt-through-runtime proof was not run in this audit.

Safe claim today:

- XACE has a guarded prompt apply path for a small certified set of deterministic CGS mutation scenarios.
- XACE has shared product wording for certified supported, constrained, clarification-required, blocked, unsupported, and experimental prompt categories.
- XACE classifier-gates prompts before PIL/provider execution for the currently certified routing set.
- XACE records bounded user resolutions for ambiguous classifier routes before any CGS mutation generation can proceed.
- XACE shows structured prompt mutation previews and blocks persistence until the matching preview approval is supplied or an audited test-mode override is used.
- XACE can block at least one obviously unsupported broad prompt in smoke tests.
- XACE has a reviewed, versioned 100-prompt corpus fixture for later benchmark tooling.
- XACE has local classifier-only prompt benchmark thresholds and the benchmark fails when the selected threshold profile is missed.
- XACE does not yet prove arbitrary complex gameplay creation from natural language.

Plan:

1. Rename or label deterministic prompt smoke as "contract/scenario smoke", not broad capability proof.
2. Complete locally: prompt capability matrix with categories: certified supported, constrained, clarification-required, blocked, unsupported, experimental.
3. Complete locally: production certification uses the real SGC binary for the prompt contract/scenario proof.
4. Complete locally: add prompt classifier gate before mutation planning or provider calls.
5. Complete locally: add bounded clarification loops for ambiguous supported or constrained requests.
6. Complete locally: add structured diff preview and explicit approval gate before prompt persistence.
7. Complete locally: add covered prompt rollback recovery for failed prompt apply paths.
8. Implemented locally: add real hosted provider proof behind explicit BYOK test gates. Live BYOK proof reports still need to be run and archived.
9. Complete locally: build a reviewed 100-prompt corpus fixture, run benchmark tooling, and enforce local classifier thresholds before public authoring claims. Still run hosted provider/runtime threshold proof before launch claims.

### 4. Engine Portability Versus Engine Ownership

Current portable items:

- CGS-owned gameplay logic shape, component defaults, semantic events, runtime state snapshots/deltas, basic movement/interaction/inventory/combat template data, semantic asset references, input packets, and adapter playback commands.

Not automatically portable today:

- Animation graphs, materials, shaders, terrain, UI layouts, native scripts, physics tuning, particles, scene hierarchies, editor-authored content, packaging configuration, engine build settings, platform storefronts, and arbitrary native gameplay code.

Plan:

1. Publish "gameplay-core portability" as the contract.
2. Require a cross-engine vertical slice proof before claiming Godot/Unity/Unreal portable gameplay core.
3. Build assisted rebinding flows for animation/audio/VFX/assets instead of promising automatic finished-game migration.
4. Treat import as assisted migration unless specific engine-native reverse mapping is implemented and proven.

## D. Technical Debt Consolidation Plan

1. Duplicate builder roots:
   - Evidence: `workspace/builder` and `packages/builder-workspace`.
   - Decision: `packages/builder-workspace` is canonical. `workspace/builder` was archived after comparing unique files and confirming it contained only placeholders.
   - Batch 3 status: complete. Active root npm scripts and workspace metadata now point at `packages/builder-workspace`; the legacy placeholder files were removed and `docs/WORKSPACE_BUILDER_ARCHIVE.md` records the diff.
   - Tests: `npm run build` in canonical workspace, smoke launcher, route tests.

2. Asset registry naming mismatch:
   - Evidence: old space-containing asset registry path; docs/tools mentioned both spellings.
   - Decision: Use `packages/asset-registry` as the canonical path.
   - Batch 3 status: complete. The package directory was renamed to `packages/asset-registry`, and code/docs/tool references now use the hyphenated path.
   - Steps: update imports, `sys.path`, tests, docs, `tools/asset_playback_smoke.py`, `tools/certify_launch.py`.
   - Evidence: asset unit tests and certification pass.

3. Hardcoded/fallback model IDs:
   - Evidence: old `provider_settings.py` defaults embedded hosted model IDs and zeroed pricing descriptors.
   - Plan: Treat models as provider-discovered or user-entered; unresolved model selection blocks visibly until the user selects a model or refreshes a real provider list. Do not silently choose stale IDs.
   - Batch 3 status: complete for stale defaults. Hosted provider definitions now start at `unresolved`, the UI/project defaults expose unresolved/explicit model resolution, and health tests/adapter creation fail visibly until a real model is selected or discovered.

4. Secret handling:
   - Earlier evidence: `STORAGE_NOTE` said local obfuscation, not OS key vault.
   - Plan: Replace `_protect_secret()` file storage with platform credential APIs. Preserve settings file only for non-secret provider/model metadata and key fingerprints.
   - Required platforms: Windows Credential Manager, macOS Keychain, Linux Secret Service/libsecret with fallback refusal or explicit dev-only unsafe mode.
   - Batch 14 status: complete locally. `credential_store.py` implements Windows Credential Manager, macOS Keychain, Linux `secret-tool`, and explicit `XACE_DEV_UNSAFE_CREDENTIAL_FALLBACK=1` dev-only unsafe file storage for tests/local fallback. `ProviderSettingsStore` now writes credential references/fingerprints to JSON and stores API keys in the credential backend.

5. Fake SGC smoke path:
   - Evidence: `test_prompt_pipeline_e2e.py::_fake_sgc_wiring_test_only_script()` remains isolated to Builder server wiring tests.
   - Task 18 status: production prompt certification uses the real `xace-system-graph-compiler` binary and fails if unavailable.

6. Determinism/network modules ahead of integration:
   - Evidence: live tick path omits guard and network topology UX.
   - Plan: Connect one production path per capability; delete or mark non-production modules that cannot be wired in P0/P1.

7. Documentation overclaiming:
   - Evidence: existing launch map is candid in places but older docs/comments still use strong determinism/atomicity language.
   - Plan: run claims audit across docs/comments/UI/tests and downgrade unsupported claims.

## E. Launch Blockers And Completion Workstreams

Each workstream uses this status scale:

- Interface exists
- Partial implementation exists
- Mocked/fake implementation exists
- Smoke-tested wiring exists
- Locally validated implementation exists
- Integrated implementation exists
- Production-grade implementation exists
- Externally proven product claim

### Workstream 1: Single Source Of Truth And Split-Brain Prevention

Current state: Locally validated implementation exists. Batch 11 added Builder/GDE authoring authority guards: mutation paths now carry state version IDs, CGS transactions receive monotonic IDs, stale submitted `cgs_hash` writes are rejected before commit, and validated mutation audit JSONL is persisted under `.xace/audit/`. Batch 12 added formal state-authority rules, process-visible CGS write locking, version-aware runtime reload refusal, and engine-edit conflict handling that permits only primitive component-default merges after newer CGS mutations. Batch 13 adds crash recovery for leftover temp files, snapshot index verification/rebuild, latest-valid-snapshot restore, direct GDE stale-parent conflict rejection, and removal of the production Builder direct CGS fallback.

Repository areas: `cgs_persistence.py`, `session_manager.py`, `ws_message_router.py`, `runtime_orchestrator.rs`, `control_server.rs`, adapters, `project_manifest.py`.

Missing work:

1. Complete locally: define authority: disk CGS is durable authoring source; GDE owns transactional authoring mutation; runtime owns live simulation state; engine owns presentation/native editor state; Builder displays authoritative versions.
2. Complete locally: add version IDs on mutation paths: `cgs_hash`, `schema_version`, `execution_plan_version`, `runtime_world_hash`, `runtime_tick`, `engine_adapter_sequence`.
3. Complete locally: add mutation sequencing with monotonically increasing transaction IDs.
4. Complete locally: reject stale writes where submitted `cgs_hash` differs from current disk/GDE hash.
5. Complete locally: add file/process lock around CGS writes and snapshot index updates.
6. Complete locally: add runtime reload handshake that refuses provided CGS/schema/runtime-plan version mismatches.
7. Complete locally: add conflict detection for engine edit commits versus newer CGS mutations.
8. Complete locally: define merge rules only for primitive component default edits; structural edits require GDE/PIL path.
9. Complete locally: add crash recovery: temp file cleanup, snapshot index verification, latest valid CGS restore.
10. Complete locally: add transaction ledger and rich mutation dataset under `.xace/audit/`.

Tests: conflicting edits, stale clients, runtime divergence, engine-side edits, interrupted writes, partial failure recovery, snapshot index corruption.

Failure injection: kill process during save, stale websocket apply, runtime reload during mutation, adapter disconnect during edit commit.

Benchmarks: write lock overhead, snapshot index growth.

Proof artifacts: `.xace/proof/state-authority/*.json`, audit log, stale-write test logs. Current local evidence: `docs/STATE_AUTHORITY_RULES.md`, `packages/builder-workspace/server/state_authority.py`, `packages/builder-workspace/server/tests/test_cgs_persistence_authority.py`, `packages/builder-workspace/server/tests/test_session_manager_authority.py`, `packages/builder-workspace/server/tests/test_engine_edit_router.py`, `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`, `cargo test -p xace-runtime-core control_protocol`, `tools/prompt_pipeline_smoke.py --skip-runtime`.

Exit criteria: every mutation path includes input version, output version, lock/transaction boundary, and recoverable failure behavior.

Dependencies: GDE transaction hardening, CGS persistence, runtime reload protocol.

Risk: Critical.

Complexity: High.

Launch tier: P0 for alpha correctness; P1/P2 for multi-user/team depth.

### Workstream 2: Hard Deterministic Enforcement

Current state: Integrated local live enforcement exists. `RuntimeOrchestrator` owns the guard/interceptor/hash path for ticking sessions, generated-system static checks reject known nondeterministic constructs, and local Windows proof artifacts exist under `.xace/proof/determinism/20260612T041429Z/`.

Repository areas: `determinism_guard/**`, `time_controller/**`, `phase_orchestrator/**`, `runtime_orchestrator.rs`, `snapshot_engine/**`, `prompt-intelligence/src/code_generation/determinism_code_checker.py`.

Missing work:

1. Complete: wire `DeterminismGuard` into the live tick owner.
2. Complete: add guard hooks to every tick/phase/system boundary.
3. Complete: integrate `RngInterceptor` windows into sequential and SGC-parallel-eligible execution.
4. Complete: expose deterministic RNG through `SystemContext`.
5. Complete locally: block or statically reject direct `rand`, `SystemTime`, `Instant`, unordered map iteration, nondeterministic serialization, and unsupported floating-point operations in generated systems.
6. Complete: compute canonical 64-char world hash every tick.
7. Complete: record hash log and expose via runtime status/control.
8. Complete: add replay record/validate commands.
9. Complete: add snapshot restore validation into live restore.
10. Pending: add cross-engine and cross-platform hash compare harnesses.

Tests: 10,000 tick deterministic torture, illegal RNG, clock access, unordered iteration, replay restore/corruption, float edge case, serialization, partial mutation failure, SGC-parallel-eligible execution policy.

Failure injection: intentionally nondeterministic generated system, corrupted replay hash, illegal RNG, `SystemTime`, `Instant`, unordered iteration, float edge case, nondeterministic serialization, SGC-parallel policy drift, wrong schema/plan version.

Benchmarks: hash time per tick, snapshot capture overhead, RNG window overhead via `cargo bench -p xace-runtime-core --bench determinism_overheads`.

Proof artifacts: local determinism proof bundle generated by `tools/determinism_proof.py`; latest run `.xace/proof/determinism/20260612T041429Z/`.

Exit criteria: supported runtime cannot tick through a D-rule violation without a fatal/actionable diagnostic in strict mode.

Dependencies: SGC repair, system execution context, canonical snapshot/hash decision.

Risk: Critical.

Complexity: High.

Launch tier: P0 if deterministic runtime is claimed; otherwise claims must be narrowed until complete.

### Workstream 3: True Mutation Atomicity

Current state: Local apply-time atomic rollback exists. `MutationGate` captures pre-batch entity/component/queue state, `PhaseOrchestrator` passes event/RNG state into the apply transaction, rollback validates hash equality, diagnostics identify the failing operation and rollback status, and Batch 10 proof artifacts demonstrate five-op/stress rollback locally.

Repository areas: `mutation_gate/**`, `snapshot_engine/**`, `phase_orchestrator.rs`, `tests/determinism/test_mutation_transaction_atomicity.rs`.

Missing work:

1. Complete: correct misleading comments immediately.
2. Complete: capture pre-batch snapshot including queues/event/RNG state.
3. Complete: apply operation batch.
4. Complete: on failure, restore pre-batch state exactly.
5. Complete: validate hash equality after rollback.
6. Complete: return diagnostics with failing operation index.
7. Complete locally: ensure operations after failing op do not apply.
8. Complete locally: nested/concurrent apply transactions are explicitly rejected, and malformed JSON, missing-entity-mid-batch, component-table failure, stress, and five-operation op3 failure cases are covered.

Tests: local apply-time duplicate component failure, hash equality, queue preservation, post-failure operation suppression; still pending five-op op3-fails artifact, malformed JSON, missing entity mid-batch, replay after rollback.

Failure injection: force table update failure after prior success.

Benchmark: snapshot-per-batch overhead.

Proof artifacts: pre/post hash report, state diff report showing zero diff.

Exit criteria: failed transaction leaves no entity/component/event/queue/replay-visible changes.

Dependencies: snapshot completeness.

Risk: Critical.

Complexity: Medium-High.

Launch tier: P0.

### Workstream 4: SGC Production Integration Proof

Current state: SGC library exists and the CLI has been repaired enough to build, accept a CGS SystemDefinition-compatible JSON input envelope, pass small and generated-system fixtures, emit structured JSON errors for failure modes, and benchmark 100-system compilation. Builder can send that envelope, validates returned plans for mutation safety, rollback compatibility, and the persisted `.xace/execution_plans/<cgs_hash>.plan.json` contract before accepting them, writes canonical persisted plans with component access sets, system metadata, adapter/migration loadability metadata, and proof references, surfaces actionable compiler/validation failures, and stores SGC proof bundles under `.xace/proof/sgc/<hash>/`. Prompt certification now requires and invokes the real SGC binary for accepted structural prompt proof. Runtime execution-plan loading and compatibility validation are implemented for strict SGC-authority runs, CGS-derived compatibility mode rejects unsupported systems with proof instead of filtering them, and the runtime registry executes generated systems through a deterministic ABI covering inputs, reads, writes, events, RNG, errors, and rollback hooks for the currently supported executor kinds. Generated Rust source now has a local safe compile/sign/register gate with SystemSpec/runtime ABI validation, unsupported generated-system rejection, deterministic static checks, Cargo sandbox checking, real SGC compilation, signed compile artifacts, and runtime signature/policy verification. Runtime ticks preserve the loaded SGC schedule ABI and local replay checks prove schedule snapshots match persisted plans and per-tick world hashes. Retained proof commands now store `.xace/proof/sgc-runtime/<run-id>/` evidence for real CGS-to-SGC-to-runtime strict loading and tick-hash replay plus `.xace/proof/cgs-e2e/<run-id>/` evidence for generated CGS creation, real SGC compilation, strict runtime load, deterministic replay, runtime replay validation, rollback failure restoration, and adapter snapshot output. Plugin/external executor registration and release-wide artifact signing are not complete.

Repository areas: `packages/system-graph-compiler/**`, `session_manager.recompile_sgc()`, `ws_message_router.py`, `cgs_persistence.py`, prompt tests.

Missing work:

1. Complete locally: harden the CLI input schema against real CGS system definitions and `SystemDefinition`.
2. Complete locally: expand robust JSON error output for Builder-facing diagnostics.
3. Complete locally: production prompt smoke uses the real SGC binary.
4. Complete locally: define, validate, and canonically write the persisted `.xace/execution_plans/<cgs_hash>.plan.json` contract, including schema/cgs/plan hash ownership, component access sets, system metadata, proof references, migration policy, and runtime load refusal rules.
5. Complete locally: standalone runtime can require, compatibility-check, and load the persisted SGC `ExecutionPlan`; CGS-derived compatibility mode no longer filters unsupported systems; supported generated systems normalize through the generated-system ABI and execute through the real runtime registry.
6. Complete locally: generated Rust source passes through SystemSpec/runtime ABI validation, deterministic static checks, Cargo sandbox checking, real SGC compilation, signed compile-artifact creation, and runtime signature verification before generated-code-backed executor metadata registers.
7. Complete locally: unsupported generated-system rejection blocks nondeterministic sources, filesystem/network/process access, engine-only API calls, unsafe/FFI/threading escapes, and missing rollback hooks with exact local reason codes before SGC/runtime load.
8. Complete locally: runtime ticks preserve loaded SGC phases, groups, execution indexes, system order, dependency metadata, component access sets, serialization constraints, and parallel flags; persisted parallel component hazards are rejected; schedule snapshots match the persisted plan across replay; SGC `parallel=true` groups execute under the reported deterministic sequential policy with no worker threads.
9. Complete locally: stale parsed persisted plans are rejected before tick zero with `xace.sgc.plan_migration.v1` invalidation proof artifacts and no silent downgrade.
10. Complete locally: `tools/sgc_runtime_proof.py` creates retained `.xace/proof/sgc-runtime/<run-id>/` evidence for CGS creation, real SGC compile, persisted strict runtime load, tick hash logging, and replay comparison with no fake wiring.
11. Complete locally: validate mutation safety and rollback compatibility before accepting a plan.
12. Complete locally: expose compilation failures in Builder UX with `code`, `message`, and `action`.
13. Complete locally in Builder proof bundles and in the Task 34 retained end-to-end CGS proof; release-wide artifact signing remains.

Tests: CLI compile success/failure, 20 generated systems, cycle, unknown deps, conflict serialization, runtime-load validation contract, runtime compatibility mismatch checks, adapter compatibility fields, generated-system safe compile/sign/register and adversarial rejection smoke, runtime schedule snapshot smoke, SGC runtime proof command, Builder failed-SGC UX, and 100-system benchmark.

Failure injection: invalid phase, duplicate ID, bad reads/writes, compiler crash.

Benchmark: compile time for 100 systems.

Proof artifacts: `.xace/proof/sgc/<hash>/input.json`, `plan.json`, `metadata.json` with validation report; `.xace/proof/sgc-runtime/<run-id>/summary.json` with SGC/runtime commands, persisted plan, schedule reports, and tick hash replay evidence; generated-system compile artifacts embed source, ABI, executor, sandbox, unsupported-policy, SGC plan, and signature hashes; real CLI smoke validates stdout success JSON and stderr error JSON.

Exit criteria: real prompt-to-SGC-to-runtime path succeeds for certified categories, runtime loads the persisted SGC `ExecutionPlan`, and unsupported inputs fail clearly through the structured error contract.

Dependencies: prompt classification, runtime execution plan loading.

Risk: Critical.

Complexity: Medium-High.

Launch tier: P0/P1.

### Workstream 5: Prompt Pipeline Capability And Honesty

Current state: Partial pipeline exists; certified smoke covers three scenarios; shared Task 35 capability matrix, Task 36 classifier gate, Task 37 bounded clarification loop, Task 42 structured diff approval gate, Task 44 covered rollback recovery, Task 45 structured apply feedback, Task 46 reviewed corpus, Task 47 local benchmark reports, Task 48 local thresholds, Task 50 prompt-security attack cases, Task 51 inference-adapter boundary enforcement, Task 52 provider timeout/retry telemetry proof, Task 53 provider token/cost accounting proof, Task 54 provider health/stale-policy proof, Task 55 opt-in hosted-provider proof gate, Task 56 automatic route-evidence gate, Task 57 provider UX states, and Task 58 deterministic no-LLM simple-edit path are complete locally; arbitrary authoring and live hosted-provider acceptance remain unproven.

Repository areas: `prompt-intelligence/**`, `provider_settings.py`, `ollama_adapter.py`, `tests/fixtures/prompt_pipeline_contract.py`, `prompt_classifier_gate.py`, classifier clarification, deterministic simple-edit, and prompt approval state in `session_manager.py`, prompt apply routing in `ws_message_router.py`, `packages/inference/**`, `docs/prompt_capability_matrix.json`, `docs/PROMPT_CAPABILITY_MATRIX.md`, `docs/prompt_corpus_100.jsonl`, `docs/prompt_corpus_manifest.json`, `docs/PROMPT_CORPUS.md`, `docs/prompt_launch_thresholds.json`, `docs/PROMPT_LAUNCH_THRESHOLDS.md`, `docs/prompt_security_cases.jsonl`, `docs/PROMPT_SECURITY_TESTS.md`, `docs/INFERENCE_ADAPTER_BOUNDARY.md`, `docs/PROVIDER_TIMEOUT_RETRY_POLICY.md`, `docs/PROVIDER_TOKEN_COST_ACCOUNTING.md`, `docs/PROVIDER_HEALTH_STALE_POLICY.md`, `tools/prompt_corpus_check.py`, `tools/prompt_corpus_benchmark.py`, `tools/deterministic_simple_edit_benchmark.py`, `tools/prompt_launch_threshold_check.py`, `tools/prompt_security_check.py`, `tools/inference_adapter_boundary_check.py`, `tools/provider_timeout_retry_check.py`, `tools/provider_token_cost_accounting_check.py`, `tools/provider_readiness_smoke.py`, `prompt_input.ts`, `diff_viewer.ts`, `model_selector.ts`.

Missing work:

1. Complete locally: shared prompt capability matrix used by docs and Builder.
2. Complete locally: add prompt classifier before mutation generation/provider calls.
3. Complete locally: add clarification flow for ambiguous supported prompts.
4. Complete locally: show structured prompt diffs and require approval before persistence.
5. Add complexity thresholds and tier routing.
6. Block unsupported broad/unsafe prompts beyond the covered fixture set.
7. Complete locally: add structured compilation/runtime/apply validation feedback.
8. Complete locally for covered prompt-apply failures: add rollback/error recovery. Broader long-session/provider/corpus recovery remains launch work.
9. Add long-session reliability checks.
10. Complete locally: build reviewed 100-prompt corpus fixture.
11. Complete locally: run 100-prompt benchmark tooling, generate JSON/Markdown reports, and enforce local classifier thresholds. Still execute hosted provider/runtime threshold profile.
12. Complete locally: add prompt-security attack cases and artifacts proving covered cases are blocked or quarantined. Still run broader security review and hosted provider/runtime threshold profile.
13. Complete locally: enforce the inference-adapter boundary for Builder, PIL, GDE, and tools, including hosted CI failure on direct provider execution outside `packages/inference`.
14. Complete locally: add redacted provider token/cost accounting artifacts for prompt benchmarks and provider telemetry, exact provider health/stale-policy gating before PIL, an opt-in BYOK hosted-provider proof gate, automatic route-evidence gating, and no-key/invalid-key/stale-proof/quota/rate-limit/outage Builder UX states.

Tests: easy/medium/advanced/ambiguous/unsupported/adversarial corpus, prompt-security attack corpus, real provider gated tests, no mutation on blocked prompts.

Failure injection: invalid provider response, malformed transaction, compile fail, runtime fail.

Benchmark: token/cost/latency/retry/human review time.

Proof artifacts: corpus JSONL, benchmark result matrix, prompt security report, inference boundary report, provider retry report, provider accounting report, and provider logs with redacted secrets.

Exit criteria: UI never implies "create any gameplay system" and all accepted prompts produce validated outcomes or clear blocks.

Dependencies: provider readiness, SGC repair, GDE hardening.

Risk: High.

Complexity: High.

Launch tier: P0 for truthfulness; P1 for launch workflow.

### Workstream 6: Multiplayer Productization And Chaos Hardening

Current state: Network primitives exist; product flow is not complete.

Repository areas: `packages/network-core/**`, `runtime_bridge_smoke.py`, adapters, Builder network/lobby UI if present.

Missing work:

1. Choose launch topology: recommended host-authoritative lockstep for small local/online sessions, no host migration unless implemented.
2. Implement lobby create/join/leave/reconnect/late join.
3. Add player identity and ready states.
4. Add version/schema/asset mismatch handling.
5. Integrate desync detection, rollback, resync, replication with runtime and adapters.
6. Add visible UX states and diagnostics.
7. Add cheating/malicious input limits appropriate for scope.

Tests: 4-16 clients, 60 minutes, loss/jitter/reordering/disconnect/reconnect/late join/version mismatch/malformed input.

Failure injection: packet loss, stale inputs, malicious packet, host loss if supported.

Benchmarks: replication bandwidth, rollback span, client CPU.

Proof artifacts: chaos logs, per-client hashes, desync reports.

Exit criteria: zero permanent desync for supported topology; unsupported topologies explicitly blocked.

Dependencies: live determinism, snapshot/rollback.

Risk: High.

Complexity: High.

Launch tier: P1 if multiplayer is advertised; otherwise P2.

### Workstream 7: Tick Debugger And Advanced Debugging

Current state: Basic UI panels/logs exist.

Repository areas: `tick_debugger.ts`, `runtime_stats.ts`, `engine_viewport.ts`, runtime status/control, feedback logs.

Missing work:

1. Minimum debugger: tick timeline, pause, step, snapshot list, state diff, mutation history, event trace, hash mismatch display.
2. Add exportable debug report.
3. Add adapter feedback diagnostics.
4. Add actionable error messages tied to entity/component/system IDs.
5. Later: time travel, reverse step, breakpoints, causality graph, RNG trace.

Tests: replay inspection, hash mismatch diagnosis, conflict display, report export.

Failure injection: corrupted snapshot, desync, adapter feedback invalid.

Benchmarks: debugger overhead.

Proof artifacts: screenshots, debug report fixtures.

Exit criteria: a creator can identify what changed and why after a failed prompt/runtime run.

Dependencies: determinism hashes, snapshots, event/mutation logs.

Risk: Medium.

Complexity: Medium.

Launch tier: P1 minimum; P2/P3 advanced.

### Workstream 8: Import Reality And Existing Engine Projects

Direct answer:

When an existing Unity, Godot, or Unreal project is imported into XACE today, XACE does not fully account for gameplay work already implemented inside the engine. `ProjectCreator.import_engine_project()` creates a new XACE project from a starter template and records the engine project path in adapter config. Gameplay must be rebuilt, represented, or mapped manually into CGS unless future assisted migration logic is added.

Current state: Wrap/import exists; reverse engineering does not.

Repository areas: `project_creator.py`, `/api/project/import-engine`, adapter install helpers.

Detected/imported today:

- Engine project folder existence.
- Chosen engine type.
- XACE starter CGS/template.
- Adapter config with `engine_project_path`.

Not currently imported:

- Native gameplay scripts, scenes, animation controllers, materials, shaders, UI, audio routing, physics setup, terrain, packaging.

Missing work:

1. Add engine project marker validation for each engine.
2. Inventory engine-native assets/scenes/scripts as references without claiming conversion.
3. Map user-selected entities/assets to CGS semantic bindings.
4. Add manual migration wizard.
5. Protect against overwriting or data loss.
6. Add reversible adapter install/uninstall.

Tests: Unity/Godot/Unreal sample imports, missing markers, read-only projects, adapter install rollback.

Failure injection: invalid project folder, existing XACE files, partial adapter copy.

Proof artifacts: import report, manifest diff, user migration checklist.

Exit criteria: import UX says exactly what was imported, ignored, mapped, and remains manual.

Dependencies: project-system, adapter install, asset registry.

Risk: High.

Complexity: Medium.

Launch tier: P1 if import is a public promise.

### Workstream 9: Bidirectional Edit Loop

Current state: Narrow live preview edit and commit path exists.

Repository areas: `ws_message_router.py`, `RuntimeOrchestrator::set_preview_component_field()`, runtime control, adapters.

Missing work:

1. Define supported edit types: selection/focus and primitive component fields initially.
2. Require runtime accepted audit row before commit.
3. Add version tracking and stale conflict rejection.
4. Add preview, approval, undo, recovery.
5. Add engine-to-XACE and XACE-to-engine update rules.
6. Add unsupported edit warnings.
7. Add multi-step journeys in tests.

Tests: live edit -> commit -> CGS save -> runtime reload -> adapter update, stale commit rejection, unsupported structural edit.

Failure injection: runtime disconnect between preview and commit.

Benchmarks: edit latency.

Proof artifacts: audit log and screenshots.

Exit criteria: normal user can safely roundtrip supported edits without corrupting CGS/runtime.

Dependencies: single source of truth, GDE.

Risk: High.

Complexity: Medium.

Launch tier: P1.

### Workstream 10: Cross-Engine Gameplay-Core Migration

Current state: Adapter source and validation tooling exist; complete vertical slice proof is not yet recorded in this plan.

Repository areas: `adapters/**`, `tools/certify_launch.py`, `tools/three_engine_runtime_smoke.py`, templates, runtime.

Missing work:

1. Define one CGS-owned vertical slice with movement, combat, health, inventory, save/load, rollback, replay, semantic asset bindings, animation/audio/VFX triggers.
2. Run in Godot, Unity, and Unreal with installed engines.
3. Compare runtime hashes and adapter reports.
4. Record visual proof.
5. Document what auto-ports versus what must be rebound.

Tests: cross-engine certification, hash compare, adapter command validation.

Failure injection: missing binding, asset mismatch, adapter version mismatch.

Benchmarks: adapter apply time per engine.

Proof artifacts: engine validation JSON, screenshots/video, hash logs.

Exit criteria: one CGS gameplay-core slice runs across all three engines with documented manual setup.

Dependencies: installed engines, adapter packaging, semantic binding workflow.

Risk: High.

Complexity: High.

Launch tier: P1/P2 depending launch promise.

### Workstream 11: Export And Finished-Game Shipping Boundary

Current state: Adapter source export exists.

Repository areas: `/api/export/{target}`, adapter install helpers, `builder_server.py`.

Honest boundary:

- XACE exports adapters/config/runtime artifacts.
- Engines own final packaging/builds.

Missing work:

1. Rename export UX to "Export/install adapter package" unless full packaging exists.
2. Add preflight validation.
3. Add engine handoff instructions.
4. Capture packaging failures if invoking engine builds in future.
5. Add export cleanliness scan for secrets.

Tests: export each target, manifest content, no secrets, install into sample engine project.

Failure injection: target folder existing, permission failure, unknown target.

Proof artifacts: export manifest, file list, hash.

Exit criteria: no UI/docs imply XACE alone ships a finished game.

Dependencies: credential redaction, adapter packaging.

Risk: Medium.

Complexity: Medium.

Launch tier: P1.

### Workstream 12: Animation, Audio, VFX, Assets, Creator Workflows

Current state: Semantic binding and asset import/link pieces exist; engine-native workflows remain external.

Repository areas: `packages/core/src/assets/**`, `packages/asset-registry/**`, `asset_playback_smoke.py`, adapters, Builder asset panels.

Missing work:

1. Canonicalize asset registry path.
2. Validate asset references and missing refs.
3. Add creator binding UI for event -> animation/audio/VFX command.
4. Add engine-specific binding status.
5. Define fallback behavior.
6. Test packaging/export includes needed references, not secrets.

Tests: missing asset, wrong type, semantic event playback, per-engine adapter command.

Failure injection: deleted asset, renamed file, unsupported asset kind.

Benchmarks: asset registry scan time.

Proof artifacts: asset manifest, binding report, playback smoke logs.

Exit criteria: reliable semantic rebinding workflow; no claim of full asset production.

Dependencies: asset path consolidation, adapters.

Risk: Medium.

Complexity: Medium.

Launch tier: P1.

### Workstream 13: Provider Readiness, Hosted Testing, Model Discovery, Routing

Current state: Provider settings, readiness gate, automatic route-evidence gate, and deterministic Builder provider UX states exist; real hosted proof requires BYOK/network.

Repository areas: `provider_settings.py`, `inference/**`, `model_selector.ts`, `prompt_input.ts`, provider smokes.

Missing work:

1. Run real hosted tests for supported providers with user keys.
2. Make model discovery primary where provider supports it.
3. Treat unresolved model selection as a visible block.
4. Handle stale/unavailable provider models explicitly.
5. Complete locally: add timeout/retry/rate-limit/backoff/failure-category telemetry, Task 53 token/cost accounting for prompt benchmarks, Task 54 exact provider health/stale-policy gating, Task 55 opt-in hosted-provider proof gate, Task 56 automatic route-evidence gate, and Task 57 no-key/invalid-key/stale-proof/quota/rate-limit/outage UX states. Still archive live BYOK reports.
6. Complete locally: add privacy boundary and BYOK/no-key/invalid-key/quota/rate-limit/outage UX.
7. Define automatic routing only after benchmark evidence.

Tests: no key, invalid key, stale model, provider outage, timeout, rate limit, real minimal prompt.

Failure injection: HTTP 401/404/429/500, malformed provider response.

Benchmarks: latency/cost per tier.

Proof artifacts: provider health/stale-policy reports, redacted hosted-provider health reports when opted in, provider route-evidence reports, provider retry reports, provider accounting reports, Builder UI contract results, and provider UX state server-test results.

Exit criteria: prompt cannot run without exact provider/model/key readiness proof.

Dependencies: OS credential storage.

Risk: High.

Complexity: Medium.

Launch tier: P1.

### Workstream 14: Security And Credential Handling

Current state: Locally implemented OS credential storage and local redaction/scanning exist. Provider API keys are written through `credential_store.py`; `provider_settings.json` keeps provider/model metadata, credential references, backend names, unsafe flags, and key fingerprints only. Linux refuses missing `secret-tool` unless `XACE_DEV_UNSAFE_CREDENTIAL_FALLBACK=1` explicitly enables dev-only unsafe file storage. `secret_redaction.py` redacts provider errors/settings, telemetry, and crash-report output, while `tools/security_secret_scan.py` scans source, fixtures, projects, CGS, snapshots, exports, logs, crash reports, and telemetry for key-shaped leaks.

Repository areas: `credential_store.py`, `provider_settings.py`, logs, export, snapshots, telemetry.

Missing work:

1. Complete locally: implement Windows Credential Manager, macOS Keychain, Linux Secret Service.
2. Complete locally: keep only provider/model/fingerprint/credential reference in JSON settings.
3. Complete locally: add redaction utility used by provider errors/settings, telemetry, credential backend errors, and crash reports.
4. Complete locally: add secret scanning for source, project files, snapshots, exports, fixtures, crash reports, and telemetry.
5. Complete locally: add tests with fake keys and mocked OS credential commands.

Tests: secret not present in provider settings, project files, CGS, logs, exports, snapshots, crash reports, telemetry.

Failure injection: credential store unavailable, locked keychain, corrupted credential record.

Proof artifacts: secret-scan reports. Current local evidence: `packages/builder-workspace/server/tests/test_credential_store.py`, `packages/builder-workspace/server/tests/test_secret_redaction_and_scan.py`, `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`, `tools/security_secret_scan.py --source --fixtures --json`, `tools/provider_readiness_smoke.py`, `tools/prompt_pipeline_smoke.py --skip-runtime`, `cargo test -p xace-observability`.

Exit criteria: no production prompt provider key is stored in reversible project/local JSON or leaked to artifacts.

Dependencies: platform APIs.

Risk: Critical.

Complexity: Medium-High.

Launch tier: P0/P1.

### Workstream 15: Performance Budgets And Scale

Current state: No explicit production budgets were proven in this audit.

Repository areas: runtime, snapshot, network, adapter bridge, Builder, SGC, prompt.

Budgets to define:

- 10,000 entities, 100 systems, 1,000 events per tick.
- Snapshot/delta/serialization/save/load/replay/rollback.
- Adapter bridge throughput and apply time.
- Prompt apply and compilation latency.
- Startup, memory, CPU, frame/tick impact.

Tests: scale benchmark suite with stable output JSON.

Failure injection: large malformed CGS, high event volume, network spikes.

Proof artifacts: `benchmarks/<date>/<machine>.json`.

Exit criteria: baseline, target, regression threshold, hardware environment, and CI trend exist.

Dependencies: canonical runtime path.

Risk: High.

Complexity: Medium-High.

Launch tier: P1/P2.

### Workstream 16: Templates, Packages, Compatibility, Extension Boundary

Current state: Useful starter templates; not an ecosystem.

Repository areas: `project_templates.py`, Cargo/npm packages, adapters.

Minimum launch foundation:

1. Version templates.
2. Version packages/adapters.
3. Add dependency declarations.
4. Add compatibility contracts and migrations.
5. Add install/uninstall/update/rollback flow for adapters/templates.
6. Define third-party extension boundary and stable API policy.

Tests: create/open/migrate project across template versions.

Failure injection: incompatible template/package.

Proof artifacts: compatibility matrix.

Exit criteria: users can tell whether a project/template/adapter is compatible.

Dependencies: project manifest/versioning.

Risk: Medium.

Complexity: Medium.

Launch tier: P1/P2.

### Workstream 17: Team, Source Control, CI, Studio Discipline

Current state: Source-control-friendly JSON exists in places; CI/studio workflow not proven.

Repository areas: all schema files, docs, test tooling, future CI workflows.

Missing work:

1. Deterministic formatting and diffs.
2. Merge conflict visibility.
3. Schema migrations.
4. Headless certification in CI.
5. Regression/performance checks.
6. Version pinning.
7. Debug report export.
8. Reproducible builds.

Tests: merge conflict fixtures, migration fixtures, CI dry run.

Proof artifacts: CI runs, build provenance.

Exit criteria: team can review/merge CGS changes without hidden nondeterminism or data loss.

Dependencies: claims correction, schema/versioning.

Risk: Medium-High.

Complexity: Medium.

Launch tier: P2 for early studio; P3 for enterprise.

### Workstream 18: Documentation And Claims Audit

Current state: Some docs are candid; comments/tests still overclaim.

Repository areas: `docs/**`, `MASTER_PLAN.md`, `README.md`, source comments, UI labels, smoke names.

Missing work:

1. Build product claims matrix.
2. Mark every major claim as proven, locally demonstrated, partial, experimental, roadmap, or unsupported.
3. Correct determinism, atomicity, SGC, prompt, import, export, multiplayer, portability wording.
4. Rename tests/smokes that prove wiring only.
5. Require proof links for launch claims.

Tests: doc linter/claim grep for forbidden phrases.

Failure injection: none.

Proof artifacts: claims matrix and docs diff.

Exit criteria: no public claim exceeds evidence.

Dependencies: all P0 audit decisions.

Risk: Critical.

Complexity: Medium.

Launch tier: P0.

## Required Validation Experiments

### 1. Determinism Torture Test

Command target:

```powershell
cargo test -p xace-runtime-core determinism_torture_10000_ticks --target-dir target-production-determinism
```

Environment: Windows first, then Linux and macOS runners. Use same CGS, same runtime binary version, same execution plan.

Steps:

1. Load certified CGS.
2. Run 10,000 ticks in strict determinism mode.
3. Record world hash every tick.
4. Replay from initial snapshot and input log.
5. Compare hashes every tick.
6. Inject illegal RNG, system-clock access, unordered iteration, float edge case, malformed serialization, replay restore, mutation failure, parallel scheduling risk.

Pass: all legal runs match hashes; illegal behavior fails loudly with actionable diagnostics.

Fail: any silent divergence, nondeterministic pass, missing hash, or unhelpful error.

Evidence path: `.xace/proof/determinism/<run-id>/`.

### 2. Mutation Atomicity Test

Command target:

```powershell
python tools/mutation_atomicity_proof.py --target-dir target-production-atomicity
```

Steps: create five-operation batch, force operation 3 to fail, assert components/entities/events/queues/snapshots/replay-visible state equal pre-transaction.

Pass: byte-for-byte or semantic exact equality plus same world hash.

Evidence path: `.xace/proof/mutation-atomicity/<run-id>/`; latest run: `.xace/proof/mutation-atomicity/20260613T023553Z/`.

### 3. Real SGC Test

Command target after repair:

```powershell
cargo build -p xace-system-graph-compiler --target-dir target-production-sgc
python tools/sgc_cli_smoke.py --sgc-bin target-production-sgc/debug/xace-system-graph-compiler.exe --json
python tools/sgc_cli_integration.py --sgc-bin target-production-sgc/debug/xace-system-graph-compiler.exe --benchmark-threshold-ms 1000 --json
cargo bench -p xace-system-graph-compiler --bench sgc_compile_100 -- --sample-size 10
```

Steps: remove fake confidence path from production certification; generate at least 20 systems through prompt-to-SGC-to-runtime path; keep the 100-system compile average under the 1000 ms CLI regression threshold.

Pass: compile, Builder-validate for load readiness, preserve the documented runtime scheduling limitation until persisted `ExecutionPlan` loading exists, snapshot/hash proof, mutation safety, rollback compatibility, adapter compatibility.

Evidence path: `.xace/proof/sgc/<cgs-hash>/`.

### 4. Prompt Corpus Benchmark

Command target:

```powershell
python tools/prompt_corpus_benchmark.py --corpus docs/prompt_corpus_100.jsonl --output target-production-prompt-corpus
```

Steps: run 100 prompts across easy, medium, advanced, ambiguous, unsupported, adversarial.

Track: accepted, blocked, clarification requested, compiled, runtime-passed, rollback-passed, cost, latency, provider, model, and reproducibility columns.

Pass now: JSONL, JSON, and Markdown reports are generated from the reviewed corpus and the local classifier threshold profile passes. Launch pass later: supported categories meet threshold; unsupported/ambiguous do not silently mutate under provider, compile, runtime, and rollback execution.

Evidence path: `target-production-prompt-corpus/summary.json`, `target-production-prompt-corpus/results.jsonl`, `target-production-prompt-corpus/report.md`, and `docs/prompt_launch_thresholds.json`.

### 4a. Deterministic Simple-Edit Benchmark

Command target:

```powershell
python tools/deterministic_simple_edit_benchmark.py --output target-deterministic-simple-edit-benchmark
```

Pass now: certified player-speed value edits produce approval-gated GDE
transactions with zero provider, provider-readiness, PIL, or LLM calls.

Evidence path: `target-deterministic-simple-edit-benchmark/summary.json`,
`target-deterministic-simple-edit-benchmark/results.jsonl`, and
`target-deterministic-simple-edit-benchmark/provider_accounting_summary.json`.

### 4b. Prompt Security Attack Gate

Command target:

```powershell
python tools/prompt_security_check.py --artifact-dir target-prompt-security
```

Steps: run the checked-in Task 50 attack corpus across prompt injection,
adversarial instruction, malformed model response, unsafe mutation,
hallucinated capability, schema corruption, and secret exfiltration cases.

Pass now: every checked attack is blocked before provider or mutation execution,
or quarantined with an exact reason and per-case artifact row. Launch pass
later: broaden this into provider-backed security testing, fuzzing, long-session
abuse coverage, and external security review.

Evidence path: `target-prompt-security/prompt_security_report.json`,
`target-prompt-security/prompt_security_cases.jsonl`,
`target-prompt-security/prompt_security_report.md`, and
`docs/prompt_security_cases.jsonl`.

### 5. Network Chaos Test

Command target:

```powershell
cargo test -p xace-network-core network_chaos_4_16_clients_60m --target-dir target-production-network
```

Steps: run 4-16 clients for 60 minutes with packet loss, jitter, reordering, disconnects, reconnects, late join, rollback, resync, mismatch, malformed input, host loss only if supported.

Pass: zero permanent desync for supported scenarios.

Evidence path: `.xace/proof/network-chaos/<run-id>/`.

### 6. Cross-Engine Vertical Slice

Command target:

```powershell
python tools/certify_launch.py --installed-engines --xace-project <project> --require-installed-engines godot,unity,unreal --installed-engine-output-dir target-production-cross-engine
```

Steps: run same CGS-owned slice in Godot, Unity, Unreal with required gameplay features and semantic triggers.

Pass: engine reports, visual proof, hash compare for portable core.

Evidence path: `target-production-cross-engine/`.

### 7. Scale Benchmark

Command target:

```powershell
cargo bench -p xace-runtime-core --target-dir target-production-bench
```

Steps: 10,000 entities, 100 systems, 1,000 events/tick, snapshots, deltas, bridge, serialization, save/load, replay, rollback.

Pass: within defined budgets; no regression beyond threshold.

Evidence path: `benchmarks/<date>/`.

### 8. Long-Run Soak Test

Command target:

```powershell
python tools/soak_test.py --hours 8 --project <project> --output target-production-soak
```

Steps: repeated save/load, import/export, adapter reconnects, prompt applies, replay/rollback, provider failures, UI stability, log growth, crash recovery.

Pass: no leaks, corruption, unbounded logs, or unrecoverable stale state.

### 9. Fuzzing And Malformed Input

Targets: CGS, mutation transactions, network packets, provider responses, schema versions, import data, adapter messages, serialization, package manifests.

Pass: no panic/corruption/secret leak; all failures actionable.

### 10. Security Review

Command target:

```powershell
python tools/security_secret_scan.py --project <project> --exports --logs --snapshots --output target-production-security
```

Pass: OS credential storage used; no keys in source, project, CGS, logs, exports, crash reports, snapshots, telemetry, fixtures.

## Required Execution Phases

| Phase | Objectives | Exact subtasks | Affected areas | Tests/evidence | Exit gate | Dependencies | Parallelism |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1. Truth audit and claim correction | Stop overclaiming | Correct determinism/atomicity/SGC/prompt/import/export docs and comments | `docs/**`, comments, UI labels | Claims matrix | No unsupported P0 claim remains | None | Can run with phase 2 audit |
| 2. Consolidation | Remove split paths | Canonical builder, asset registry rename, fake path labels | `workspace/builder`, `packages/builder-workspace`, asset registry | Builds/tests | One canonical path per subsystem | Phase 1 decisions | Parallel docs/code cleanup |
| 3. State authority | Prevent split brain | Version IDs, locks, stale rejection, audit | Builder server, GDE, runtime | Conflict tests | No stale mutation applies | Phase 1 | Sequential core design |
| 4. Mutation atomicity | Guarantee rollback | Snapshot-backed transaction restore | MutationGate, SnapshotEngine | Five-op failure proof | Exact pre-state restore | Phase 3 state model | Sequential |
| 5. Live determinism | Enforce in tick | Guard hooks, RNG, hash, replay | Runtime core | 10,000 tick test | Strict mode enforced | Phase 4 | Mostly sequential |
| 6. Real SGC | Compile production plans | Keep CLI smoke green, replace fake smoke, prove runtime loading | SGC, Builder | SGC proof | No fake production SGC | Phase 5 for runtime load | Parallel-eligible schedule work |
| 7. Prompt UX | Honest guarded authoring | Complete capability matrix, classifier gate, bounded clarification loop, prompt diff approval gate, covered prompt rollback recovery, structured apply feedback, reviewed corpus fixture, local benchmark reports with provider accounting artifacts, local threshold gate, covered prompt-security attack gate, inference-adapter boundary gate, provider retry gate, provider accounting gate, provider stale-policy gate, opt-in hosted-provider proof gate, automatic route-evidence gate, provider UX-state coverage, and deterministic no-LLM simple-edit benchmark proof | PIL, Builder UI | Live hosted provider/runtime thresholds and broader security review | Unsupported prompts block, ambiguous prompts resolve before mutation, no prompt mutation persists without explicit preview approval, covered failures leave no partial CGS/artifacts or UI success state, corpus coverage is versioned, benchmark reports are generated with redacted provider accounting artifacts, local thresholds fail below profile, covered attacks block or quarantine with artifacts, direct provider execution outside inference fails CI, provider retry/accounting proofs pass locally, hosted calls require opt-in, automatic routes require fresh benchmark evidence, provider setup blocks have explicit no-key/invalid-key/stale-proof/quota/rate-limit/outage states, and certified player-speed value edits have zero provider/provider-readiness/PIL/LLM calls | Phase 6 | Parallel corpus/UI |
| 8. Provider/security | Safe BYOK | OS credentials, discovery, hosted proof gate, route-evidence gate, provider UX states | Provider/inference | Secret scan, live hosted health reports | No secret leak, exact readiness, stale automatic-route rejection, clear no-key/invalid-key/quota/rate-limit/outage UX | Phase 7 for E2E | Platform work parallel |
| 9. Multiplayer | Product flow | Lobby/topology/chaos | network-core/runtime/UI | Chaos logs | Supported topology stable | Phase 5 | Parallel after determinism |
| 10. Debugger | Explain failures | Timeline, diff, hash/event reports | Builder/runtime | Debug reports | Creator can diagnose failures | Phase 5 | Parallel UI |
| 11. Import/edit loop | Honest migration/editing | Assisted import, live edit conflicts | Project system, adapters | Journey tests | No false import/edit claim | Phase 3 | Parallel |
| 12. Cross-engine proof | Prove core portability | Vertical slice in 3 engines | Adapters/runtime/templates | Installed engine reports | All required engines pass | Phases 5-6 | Engine tasks parallel |
| 13. Assets/bindings | Polish semantic assets | Registry path, binding UI/proof | Assets/adapters/UI | Playback proof | Missing refs handled | Phase 12 partly | Parallel |
| 14. Export boundary | Honest handoff | Adapter/package export and preflight | Builder/adapters | Export manifests | No finished-game overclaim | Phase 8 | Parallel |
| 15. Scale/fuzz/soak/CI | Production pressure | Benchmarks, fuzz, soak, CI artifacts | All | CI/artifacts | Regression gates exist | Core phases | Parallel after core |
| 16. Docs/onboarding/gates | Launch readiness | Final docs, onboarding, gate checklist | Docs/UI/tools | Gate review | Alpha/beta/launch gates signed | All prior | Sequential finish |

## Product Promise Classification

| Product Promise | Current Status | Evidence | Missing Work | Safe to Claim in Alpha? | Safe to Claim at Launch? |
| --- | --- | --- | --- | --- | --- |
| Build gameplay systems rapidly. | Partially supported | Templates, GDE/PIL supported scenarios, classifier, approval, feedback, corpus gates, local benchmark reports with provider accounting artifacts, local threshold pass, covered prompt-security attack artifacts, inference-adapter boundary proof, provider retry proof, provider accounting proof, provider stale-policy proof, opt-in hosted-provider proof gate, automatic route-evidence gate, provider UX-state coverage, and deterministic no-LLM simple-edit benchmark proof | Live hosted provider/runtime thresholds and broader UX proof | Yes, narrowly | Yes, if benchmarked |
| Create complex gameplay systems from natural-language prompts. | Experimental | PIL modules plus narrow classifier/clarification/approval/recovery/feedback proof, reviewed corpus fixture, local classifier-only benchmark reports with provider accounting artifacts, local threshold pass, covered prompt-security attack artifacts, inference-adapter boundary proof, provider retry proof, provider accounting proof, provider stale-policy proof, opt-in hosted-provider proof gate, automatic route-evidence gate, provider UX-state coverage, and deterministic no-LLM simple-edit benchmark proof for certified player-speed edits | Live hosted provider proof plus hosted provider/runtime launch thresholds and broader security review | No | Only constrained |
| Generate arbitrary gameplay systems. | Unsupported | Blocked broad prompt smoke | Years of proof | No | No |
| Catch broken logic before engine integration. | Partially supported | GDE, SGC library, validation modules | Real SGC/runtime integration | Narrowly | Yes, after P0/P1 |
| Deterministic gameplay runtime. | Interface/partial, not live guarantee | Guard modules, tests; live path lacks hooks | Live enforcement and torture test | No, unless narrowed | Yes only after proof |
| Rollback multiplayer. | Primitive partial | network-core rollback modules | Integrated rollback/resync chaos | No | Only if chaos passes |
| Production-grade multiplayer. | Unsupported | Primitives only | Full product flow/chaos/security | No | No unless fully proven |
| Portable gameplay core across Godot, Unity, and Unreal. | Partially demonstrated, not complete | Adapters and certification hooks | Cross-engine vertical slice | Narrowly for adapter protocol | Yes after slice proof |
| Import an existing engine project into XACE. | Wrapper only | `import_engine_project()` creates starter CGS | Assisted migration | Only as "wrap/link" | Yes, honestly scoped |
| Bidirectional XACE-engine editing. | Narrow partial | engine edit/commit routes | Authority/conflict journeys | No or very narrow | Yes after P1 |
| Migrate a project cleanly between engines. | Not proven | Project/adapter setup | Vertical slice and rebinding | No | Narrow gameplay-core only |
| Export a finished game. | Unsupported | Adapter export only | Engine packaging integration | No | No unless engine-owned handoff wording |
| Integrate real animation, audio, VFX, and assets. | Semantic partial | bindings/assets/playback smoke | Creator binding workflows | Narrow semantic refs | Yes after binding proof |
| Ready for non-technical public creators. | Not yet | Builder onboarding partial | UX validation, guardrails | No | Not until human UX proof |
| Ready for professional studios. | Not yet | Architecture foundations | CI/security/compat/perf/team workflows | No | No; P2/P3 roadmap |

## What Can Be Completed Now In This Repository

Can be completed now in-repo:

- Correct docs/comments/UI claims.
- Keep the open CGS export format contract current and implement the actual exporter that writes `format: "xace.cgs.export"`, `format_version: "1.0.0"`, and a matching 64-character SHA-256 `metadata.cgs_hash`.
- Keep the repaired SGC CLI and real-SGC prompt proof under certification.
- Wire `DeterminismGuard` into runtime tick path.
- Keep MutationGate rollback proof artifacts and stress tests retained in CI/artifact storage.
- Add stale CGS hash rejection and transaction IDs.
- Consolidate builder roots and asset-registry path.
- Complete locally: shared prompt capability matrix, prompt classifier gate, bounded clarification loop, prompt diff approval gate, covered prompt rollback recovery, structured prompt apply feedback, reviewed prompt corpus fixture, local benchmark reports with provider accounting artifacts, local benchmark thresholds, covered prompt-security attack artifacts, inference-adapter boundary enforcement, provider timeout/retry telemetry proof, provider token/cost accounting proof, provider health/stale-policy proof, opt-in hosted-provider proof gate, automatic route-evidence gate, provider UX-state coverage, and deterministic no-LLM simple-edit benchmark proof; still execute live BYOK hosted provider/runtime threshold profile and broader security review.
- Add secret scanning/redaction tests.
- Add benchmark/fuzz/soak harnesses that run locally.
- Harden import/export wording and reports.

Requires external infrastructure or environment:

- Live hosted provider reports with valid BYOK keys, explicit opt-in, and network access.
- Real OS credential storage validation on Windows, macOS, and Linux beyond mocked local tests.
- Installed Godot/Unity/Unreal validation across versions and OSes.
- Cross-platform deterministic replay on Windows/Linux/macOS.
- Network chaos with realistic multi-process/multi-machine conditions.
- Human UX validation with target creators.
- Public launch CI infrastructure and artifact retention.
- Security review by humans and platform-specific credential experts.

## Readiness Assessment

Private alpha realistically requires:

- Honest claims, no fake confidence, no known data-loss path, working local Builder, one or more supported prompt/edit flows, SGC CLI repaired with full integration claims narrowed until proven, secrets not leaked in projects/logs, and reproducible local certification.

Public beta realistically requires:

- P0 complete, P1 core flows working, real provider test path, installed-engine proof for advertised engines, prompt capability matrix, benchmarks, CI, import/export honesty, minimum debugger, and robust onboarding.

Credible launch realistically requires:

- Public docs aligned with evidence, cross-engine gameplay-core proof if claimed, strong error recovery, security handling, provider reliability, regression suite, benchmark gates, and no unsupported product promises.

Serious studio-grade readiness realistically requires:

- Cross-platform deterministic proof, long-run chaos/soak/fuzz, source-control/team workflows, compatibility policy, stable APIs, robust package/version management, external security review, performance budgets, and years of disciplined maintenance.

## Launch-Blocker Checklist

- [ ] P0 claims corrected across docs/comments/UI/tests.
- [x] Open readable/shareable CGS export format spec and standalone validator documented.
- [x] MutationGate local apply-time atomicity fixed and proof artifact produced; broader transaction/audit integration still pending.
- [ ] Live determinism integrated or deterministic runtime claim removed.
- [x] Production prompt smoke uses the repaired real SGC binary and stores proof artifacts for accepted structural prompt scenarios.
- [x] Prompt apply requires structured diff preview approval locally, with audited test-mode override support.
- [x] Fake SGC paths are isolated to wiring-only tests.
- [x] Provider secrets moved to OS credential storage locally; secret scan/redaction and real cross-OS validation still required.
- [x] State-authority guards reject stale CGS writes, lock CGS/snapshot writes, refuse mismatched runtime reloads, constrain stale engine edit commits, recover from temp/index/main-CGS corruption, and remove the direct Builder CGS fallback; broader runtime/editor divergence proof remains.
- [ ] Import/export claims narrowed.
- [ ] Certification includes P0 gates and stores artifacts.
- [ ] No known data-loss/corruption path remains unhandled.

## Proof-Artifact Checklist

- [ ] Determinism tick hash logs.
- [ ] Replay validation reports.
- [x] Mutation atomicity pre/post diff reports.
- [x] SGC input/output/compiler logs. Builder and prompt certification store SGC input/plan/metadata locally; external CI retention is still pending.
- [x] Prompt diff preview approval audit records for local covered scenarios.
- [x] Prompt corpus benchmark JSON/Markdown/provider-accounting reports, local threshold evaluation, covered prompt-security attack artifacts, inference-adapter boundary reports, provider retry reports, provider token/cost accounting reports, provider health/stale-policy reports, no-network hosted-provider proof-gate reports, and provider route-evidence reports. Hosted-provider/runtime threshold execution and broader security review remain pending.
- [ ] Live hosted provider readiness/prompt reports with redaction.
- [ ] Network chaos logs.
- [ ] Cross-engine validation JSON and screenshots/video.
- [ ] Scale benchmark JSON.
- [ ] Soak/fuzz reports.
- [ ] Secret scan reports.
- [ ] CI run links/artifacts.

## Private-Alpha Gate

Private alpha can start only when:

- P0 truth/security/correctness blockers are resolved or explicitly removed from claims.
- One local happy path is reproducible by command.
- CGS save/apply/rollback cannot silently corrupt project data.
- Provider configuration cannot silently fake success.
- A user can recover from failed prompt/apply/runtime operations.

## Public-Beta Gate

Public beta can start only when:

- P0 complete and P1 user-facing launch blockers materially complete.
- Supported prompt categories are documented and benchmarked.
- At least one engine path is installed-editor validated.
- CI runs editor-free certification.
- Import/export/bidirectional edit limitations are visible in UI/docs.
- Secrets are handled with production-grade storage or hosted prompting is disabled.

## Credible-Launch Gate

Credible launch requires:

- Cross-engine claims backed by engine proof.
- Deterministic claims backed by 10,000 tick and replay proof.
- Multiplayer claims backed by chaos proof for the supported topology.
- Benchmarks and regression thresholds.
- Clean documentation and onboarding.
- No fake or mock path presented as product capability.

## Studio-Readiness Roadmap

- Cross-platform determinism matrix.
- Long-run multi-user/networked soak.
- Source-control and merge workflows.
- Versioned package/template ecosystem.
- Stable extension APIs.
- Performance profiling at studio scale.
- External security review.
- Compatibility/deprecation policy.
- Advanced debugger/time travel/desync diagnosis.
- Enterprise collaboration only after core correctness is stable.

## Claims XACE Must Not Publicly Make Yet

- "Generate arbitrary gameplay systems."
- "Create any game from a prompt."
- "Full finished-game portability between engines."
- "Import existing Unity/Godot/Unreal gameplay automatically."
- "Export a finished game."
- "Production-grade multiplayer."
- "Deterministic runtime is fully enforced live."
- "MutationGate transactions are studio-proven atomic" until broader transaction/audit integration, CI retention, and external/studio-scale proof exist.
- "Real SGC production integration" for arbitrary generated, plugin, or external systems until those executor contracts, release-wide signing, and release CI artifact review pass.
- "Secrets are securely stored" beyond local OS-vault implementation until secret scans, redaction, and real platform validation pass.
- "Ready for non-technical public creators."
- "Ready for professional studios."

## Decisions Requiring Ankit's Judgment

1. Which engine is the primary private-alpha path: Godot, Unity, Unreal, or headless-first?
2. Is deterministic runtime a launch promise or a roadmap promise until live enforcement lands?
3. Should MutationGate guarantee full atomicity now, or should the contract be narrowed temporarily?
4. Which provider(s) are officially supported at launch?
5. Which hosted BYOK providers should be enabled first now that local OS credential storage exists?
6. What exact prompt categories are worth certifying first?
7. Should import be marketed as "wrap/link existing engine project" or "assisted migration"?
8. What multiplayer topology, if any, is launch scope?
9. What engines/versions/OSes are required for beta and launch?
10. What level of non-technical creator support is actually intended for first public release?

## Suggested Implementation Order For The First 20 Engineering Tasks

1. Correct determinism and MutationGate comments/docs to stop overclaiming.
2. Add product claims matrix and forbidden-claim grep.
3. Keep SGC Cargo/API repair covered by CLI smoke.
4. Complete locally: production prompt certification uses the real SGC CLI and fake SGC remains only as wiring-test coverage.
5. Canonical hash format decided: 64-character lowercase SHA-256. Keep tests/docs aligned and treat short prefixes as non-authoritative labels only.
6. Add live tick world-hash recording.
7. Add `DeterminismGuard` to runtime tick path.
8. Integrate RNG window into system execution.
9. Add 10,000 tick deterministic local test.
10. Implement MutationGate pre-batch snapshot/restore or narrow contract.
11. Add five-operation mutation atomicity proof.
12. Complete locally: add stale `cgs_hash` rejection to prompt apply, asset link, rollback, and live edit commit.
13. Complete locally: add transaction IDs and persisted audit log/dataset to CGS mutations.
14. Complete locally: replace provider local obfuscation with OS credential abstraction.
15. Add secret redaction and secret scan tests.
16. Canonicalize `packages/asset-registry`.
17. Deprecate or remove `workspace/builder`.
18. Complete locally: build prompt capability matrix, classifier gate, bounded clarification loop, diff approval gate, covered rollback recovery, structured apply feedback, reviewed 100-prompt corpus fixture, local benchmark reports with provider accounting artifacts, local benchmark thresholds, covered prompt-security attack artifacts, inference-adapter boundary enforcement, provider timeout/retry telemetry proof, provider token/cost accounting proof, provider health/stale-policy proof, opt-in hosted-provider proof gate, automatic route-evidence gate, provider UX-state coverage, and deterministic no-LLM simple-edit benchmark proof. Still execute live BYOK hosted provider/runtime threshold profile and broader security review.
19. Add provider real-test harness with redacted artifact output.
20. Add import/export honesty reports and UI wording corrections.

## STOP CONDITIONS

Pause implementation and require explicit human judgment if any of these occur:

- A mutation failure can leave partially applied gameplay state while any docs/UI claim atomicity.
- Live deterministic enforcement cannot be integrated without major runtime redesign.
- Snapshot restore cannot reproduce state hash after rollback.
- Any credential appears in CGS, project files, logs, snapshots, exports, crash reports, telemetry, screenshots, or test fixtures.
- The repaired SGC CLI cannot produce runtime-loaded execution plans through the Builder/runtime proof path.
- Import logic risks overwriting or deleting engine project data.
- Runtime, Builder, GDE, or engine adapter authority rules conflict.
- A product claim depends on external proof that has not been run.
- Cross-engine validation produces inconsistent hashes for the portable core.
- Automatic provider/model routing still needs benchmarked evidence and user-visible rejection for unbenchmarked choices.

When a stop condition is hit, record the exact file, command, failure output, prerequisite, and decision required before proceeding.
