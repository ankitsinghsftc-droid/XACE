# SGC ExecutionPlan Contract

Task 21 defines the authoritative persisted execution-plan contract for XACE.
Task 22 implements Builder's canonical persisted plan writer for that contract.
The CLI stdin/stdout contract remains in `docs/SGC_CLI_CONTRACT.md`; this file
defines the on-disk artifact that Builder stores and the runtime loader
consumes.

## Storage

Schema: `docs/schemas/xace-sgc-execution-plan.schema.json`

Persisted plans live at:

```text
<project>/.xace/execution_plans/<cgs_hash>.plan.json
```

The filename stem is authoritative and must equal the plan document
`compiled_from_cgs_hash`. Builder owns this directory through
`CGSPersistence.save_execution_plan()`. The SGC owns the plan content and
`plan_hash`; Builder may validate, canonicalize, and enrich the persisted
document with non-schedule metadata, but must not rewrite phase/group/system
ordering or other schedule semantics.

Proof bundles remain separate:

```text
<project>/.xace/proof/sgc/<cgs_hash>/
```

The proof bundle may include CLI input, the emitted plan, metadata, validation
reports, and hashes. The runtime schedule artifact is the `.plan.json` file in
`.xace/execution_plans/`.

## Required Fields

Every persisted plan must be a JSON object with:

- `schema_version`: CGS schema version used for compilation.
- `plan_version`: integer `>= 1`, monotonic for adapter/runtime compatibility.
- `adapter_protocol_version`: integer matching the runtime adapter protocol
  version required by the current runtime.
- `migration_status`: string status for loadability. Builder-persisted plans use
  `current`; stale or pending migration states must not be loaded.
- `created_tick`: integer `>= 0`. Builder-compiled plans use `0` until runtime
  reload support stamps live tick values.
- `plan_hash`: lowercase 64-character SHA-256 digest owned by SGC.
- `compiled_from_cgs_hash`: lowercase 64-character SHA-256 digest matching the
  CGS and filename stem.
- `all_system_ids`: sorted unique system IDs.
- `phases`: object keyed by phase ordinal strings `0` through `4`, where each
  phase schedule contains `phase`, `groups`, and `total_system_count`.
- `component_access_sets`: Builder-derived canonical read/write component
  access sets for every system, plus aggregate read/write/component ID lists.
- `system_metadata`: Builder-derived canonical metadata for every system,
  including display name, phase, dependencies, deterministic flag, version, and
  description.
- `proof_bundle`: stable reference to `.xace/proof/sgc/<cgs_hash>/` with the
  proof input hash, validation hash, plan hash, and compiled CGS hash.

Execution groups must contain `group_id`, `phase`, `parallel`, `systems`,
`serialization_constraints`, and `execution_index`.

## Identity And Hashes

The runtime identity tuple is:

```text
(schema_version, plan_version, adapter_protocol_version, compiled_from_cgs_hash, plan_hash)
```

Rules:

1. `compiled_from_cgs_hash` must match the current CGS `metadata.cgs_hash`.
2. `compiled_from_cgs_hash` must match the persisted filename stem.
3. `plan_hash` must be a valid SGC-produced 64-character lowercase SHA-256
   digest.
4. Proof metadata may store `plan_json_hash`, but that is an artifact hash, not
   the runtime schedule identity.
5. Canonical persisted plan bytes are the artifact identity for reproducibility
   checks and must be byte-identical for unchanged CGS, SGC output, and
   validation inputs.

At runtime, XACE seals a `RuntimeScheduleIdentity` before tick zero. That
identity extends the tuple above with the schedule source, scheduled system ID
list, phase/group ordering, component access sets, and system dependency map.
Every tick records a `xace.runtime.schedule_snapshot.v1` snapshot containing
those fields plus the tick number. Runtime execution derives its phase plan only
after validating the snapshot against the sealed identity, and replay validation
rejects the first recorded snapshot whose identity fields drift from that
startup schedule.

## Builder Validation

Before Builder accepts or stores a plan it must validate:

- JSON shape against the persisted contract schema.
- `compiled_from_cgs_hash` and storage path ownership.
- `schema_version`, `plan_version`, `created_tick`, and hash fields.
- `adapter_protocol_version` and `migration_status` for strict persisted plans.
- Sorted, duplicate-free `all_system_ids`.
- Exact match between scheduled systems and `all_system_ids`.
- Phase/group structural fields and `total_system_count`.
- Required persisted metadata: `component_access_sets`, `system_metadata`, and
  `proof_bundle`.
- Canonical JSON bytes produced with sorted keys and compact separators.
- Existing runtime-load readiness checks from
  `packages/builder-workspace/server/sgc_plan_validator.py`, including
  CGS system ID match, duplicate schedule detection, parallel hazard checks, and
  rollback-compatible read/write declarations.

`CGSPersistence.save_execution_plan()` refuses invalid persisted-plan contracts.
If a plan file already exists for a CGS hash, the writer accepts it only when the
existing bytes exactly match the newly canonicalized plan bytes.

## Migration Policy

Execution plans are immutable byte artifacts for one CGS hash. XACE does not
silently migrate, downgrade, or patch a `.plan.json` file in place.

Regenerate through SGC when any of these change:

- CGS `metadata.cgs_hash`
- CGS `metadata.schema_version`
- CGS `metadata.execution_plan_version`
- `plan_version`
- runtime `adapter_protocol_version`
- system IDs, phases, dependencies, reads, writes, determinism flags, or system
  versions
- runtime/adapter contract rules that make an older plan incompatible

Future migration tools may write a separate migration report, but the migrated
schedule must still be emitted as a new SGC plan with a new valid identity tuple.

Current runtime migration behavior is explicit invalidation, not in-place
migration. When the standalone runtime can parse a persisted plan but rejects it
as stale or incompatible before tick zero, it writes:

```text
<project>/.xace/proof/sgc-migration/<cgs_hash>.json
```

The report uses schema `xace.sgc.plan_migration.v1`, records
`decision = reject_and_regenerate`, captures the stale plan identity and current
runtime expectation, and proves `migration_performed = false`,
`fallback_to_cgs_derived = false`, `silent_downgrade_performed = false`, and
`runtime_tick_started = false`. This covers schema-version, plan-version,
adapter-protocol, migration-status, CGS-hash, created-tick, and broader runtime
compatibility failures. The runtime error includes the proof path. Regeneration
through SGC is the supported migration action until a real migration tool exists.

## Runtime Load Rules

Current standalone runtime status: `strict_loader_ready`. Builder validates,
canonicalizes, enriches, and persists plans, and the standalone runtime can load
the persisted plan as its authoritative schedule when launched with
`--require-sgc-plan` or an explicit `--sgc-plan` path. Non-SGC fixture runs may
explicitly use the CGS-derived compatibility path with `--derive-cgs-plan`.
That path now rejects any declared unsupported, unknown, duplicate, invalid, or
non-deterministic system before tick zero and writes a
`.xace/proof/runtime-compatibility/<cgs_hash>.json` proof artifact; it never
silently filters systems or injects a replacement default system. SGC-authority
runs must not fall back.

Strict runtime loader rule:

1. Load `<project>/.xace/execution_plans/<metadata.cgs_hash>.plan.json`.
2. Validate this schema and the semantic Builder/runtime checks: CGS hash,
   schema version, CGS execution-plan version, plan version, adapter protocol
   version, system IDs, component access sets, system metadata, deterministic
   flags, migration status, proof bundle hashes, and phase/group consistency.
3. Reject before tick zero if the file is missing, unreadable, malformed, stale,
   hash-mismatched, schema-mismatched, plan-version mismatched,
   adapter-protocol mismatched, component/system-mismatched, migration-pending,
   non-deterministic, or schedules a system the runtime cannot execute.
4. Do not fall back to a CGS-derived schedule when SGC authority is required.
5. Surface an actionable error code and preserve the original CGS without
   starting simulation.
6. Preserve the loaded SGC schedule ABI, including group IDs, phase names,
   execution indexes, `parallel` flags, system order, serialization
   constraints, component read/write access, and declared dependencies. Runtime
   tick snapshots and per-tick world hash logs must match this loaded schedule
   for every tick in replay.
7. When a parsed persisted plan is stale or incompatible, write the
   `xace.sgc.plan_migration.v1` invalidation proof before returning the error.
   Do not downgrade, mutate, or fall back from the persisted SGC authority path.

## Runtime Parallel Execution Policy

`parallel=true` in an SGC execution group means the group is dependency-safe and
parallel-eligible. It is schedule metadata, not a promise that the standalone
runtime currently uses worker threads.

Current standalone runtime policy:

- `parallel_group_execution_policy`: `deterministic_sequential`
- `parallel_group_worker_threads`: `false`
- Systems in a SGC-parallel-eligible group are invoked one at a time in the
  persisted SGC order.
- Events are still merged by `system_id` order so replay behavior stays stable
  and a future worker-thread policy has a fixed merge contract.
- Startup output, runtime status, and `--schedule-snapshot-out` reports expose
  the active policy. Any future true thread-pool policy must update this
  contract, policy tests, benchmark evidence, and launch-copy claims in the
  same change.

Task 24 completes the strict runtime compatibility matrix for persisted SGC
plans. Task 25 removes silent filtering for CGS-derived plans. Task 26 adds the
first generated-system registry path. Task 27 defines the local generated-system
ABI: supported generated systems must normalize to a deterministic
`GeneratedSystemAbiSpec` before registration, including declared inputs, reads,
writes, events, RNG usage, error policy, and rollback hooks. Unsupported
generated, plugin, or external systems are still rejected before tick zero until
their executor contract and safety gates exist. Task 28 adds the local
generated-code safe compile gate: accepted generated Rust must pass
SystemSpec/runtime ABI validation, deterministic static checks, Cargo sandbox
checking, real SGC compilation, signed compile-artifact creation, and runtime
signature verification before it can register as generated-code-backed runtime
executor metadata. Task 29 adds the local unsupported generated-system
rejection policy: generated Rust is scanned for unsupported APIs,
nondeterministic constructs, filesystem/network/process access, engine-only
calls, unsafe/FFI/threading escapes, and missing rollback hooks before SGC or
runtime load. The signed artifact includes the rejection-policy hash
`3306f82262ec3e951b9d8d7de53dac45f3e69fac8b6b00d0959c89877c5e47c5`.

## Runtime Executor Contract

Built-in systems register from the runtime's built-in registry. Non-built-in
generated, plugin, and external systems must declare an explicit runtime
executor contract in their CGS system definition before the standalone runtime
will schedule them from a CGS-derived plan or register them for persisted-plan
execution.

Supported runtime executor kinds:

- `generated.increment_numeric_field`: queries a declared component, reads a
  top-level numeric JSON field, and submits deferred component mutations through
  `SystemContext` and `MutationGate`.
- `generated.emit_event_on_rng_threshold`: queries a declared component, draws
  at most one deterministic RNG value per entity through `SystemContext`, and
  emits a buffered broadcast domain event when the draw is below `chance`.
- `plugin.set_json_field`: queries a declared component, writes one scalar
  top-level JSON field, and submits the update through `MutationGate`.
- `plugin.increment_numeric_field`: plugin-scoped form of deterministic numeric
  field increment using the same ABI and mutation path as generated systems.
- `external.copy_numeric_field`: queries declared source and target components,
  copies a numeric source field into a numeric target field with optional
  deterministic scale/offset, and writes through `MutationGate`.
- `external.increment_numeric_field`: external-scoped form of deterministic
  numeric field increment using the same ABI and mutation path.

Legacy Task 26 executor blocks without an explicit `abi` object are accepted
for the increment executor and normalized to ABI version 1. New generated
systems should include the explicit ABI block. New plugin and external systems
should use `runtime_executor.abi.schema = "xace.runtime_executor_abi.v1"`;
legacy generated systems may still use `xace.generated_system_abi.v1`.

```json
{
  "id": "GeneratedCounterSystem",
  "phase": "Simulation",
  "reads": [300],
  "writes": [300],
  "depends_on": [],
  "deterministic": true,
  "runtime_executor": {
    "kind": "generated.increment_numeric_field",
    "component_type_id": 300,
    "field": "count",
    "amount": 1,
    "abi": {
      "schema": "xace.generated_system_abi.v1",
      "version": 1,
      "inputs": {
        "query_components": [300],
        "component_reads": [300],
        "current_tick": false
      },
      "events": {
        "emits": []
      },
      "rng": {
        "allowed": false,
        "max_calls_per_entity": 0
      },
      "errors": {
        "policy": "halt_and_rollback"
      },
      "rollback": {
        "mutation_hook": "mutation_gate_deferred",
        "event_hook": "event_bus_phase_buffered",
        "rng_hook": "rng_windowed"
      }
    }
  }
}
```

```json
{
  "id": "GeneratedLootRollSystem",
  "phase": "Simulation",
  "reads": [301],
  "writes": [],
  "depends_on": [],
  "deterministic": true,
  "runtime_executor": {
    "kind": "generated.emit_event_on_rng_threshold",
    "component_type_id": 301,
    "chance": 1.0,
    "event_type": "generated.loot_roll",
    "payload": {
      "source": "generated"
    },
    "abi": {
      "schema": "xace.generated_system_abi.v1",
      "version": 1,
      "inputs": {
        "query_components": [301],
        "component_reads": [301],
        "current_tick": true
      },
      "events": {
        "emits": [
          {
            "event_type": "generated.loot_roll",
            "broadcast": true,
            "payload": {
              "source": "generated"
            }
          }
        ]
      },
      "rng": {
        "allowed": true,
        "max_calls_per_entity": 1
      },
      "errors": {
        "policy": "halt_and_rollback"
      },
      "rollback": {
        "mutation_hook": "mutation_gate_deferred",
        "event_hook": "event_bus_phase_buffered",
        "rng_hook": "rng_windowed"
      }
    }
  }
}
```

Rules:

- `runtime_executor.kind` must be a supported executor kind.
- `runtime_executor.abi.schema` must be `xace.runtime_executor_abi.v1` or
  compatible legacy `xace.generated_system_abi.v1`, and
  `runtime_executor.abi.version` must be `1`.
- ABI `inputs.query_components`, `inputs.component_reads`, and
  `inputs.current_tick` must exactly match the executor's query/read/tick use.
- ABI `events.emits` must exactly match the executor event declarations,
  including broadcast mode and scalar payload.
- ABI `rng.allowed` and `rng.max_calls_per_entity` must exactly match executor
  RNG use.
- ABI `errors.policy` must be `halt_and_rollback`.
- ABI rollback hooks must be `mutation_gate_deferred`,
  `event_bus_phase_buffered`, and `rng_windowed`.
- `component_type_id` must be a positive u32 declared in `reads` or `writes`;
  mutation executors must also declare it in `writes`.
- Increment `field` must be a non-empty top-level JSON object field name and
  `amount` must be a finite number.
- RNG event `chance` must be between `0.0` and `1.0`, `event_type` must be
  non-empty, and payload values must be scalar.
- Runtime executors run only through `SystemContext` and do not bypass
  phase-plan order, component access enforcement, deterministic RNG windows,
  `MutationGate`, or phase-buffered event delivery.
- Generated-code-backed executors may include
  `runtime_executor.compile_artifact`. When present, the runtime validates
  `schema = "xace.generated_system_compile_artifact.v1"`, the system ID,
  source hash, runtime-executor hash, ABI hash, SGC plan hash, sandbox hash,
  unsupported generated-system rejection policy hash, required safe-compile
  validation step order, signing key ID, and deterministic local signature
  before registration.

Task 29 completes the local safe compile/sign/register plus unsupported
generated-system rejection boundary for generated code targeting the supported
executor set. Task 30 wires runtime ticks to the loaded SGC schedule ABI:
runtime now preserves group IDs, execution indexes, dependency metadata,
component access sets, serialization constraints, and parallel flags, rejects
persisted parallel groups with component hazards, records per-tick schedule
snapshots, and exposes `--schedule-snapshot-out` for real-binary replay checks.
Task 31 documents and tests the current standalone runtime parallel-group
execution policy: persisted SGC `parallel` flags remain parallel-eligibility
metadata, while execution is explicitly `deterministic_sequential` with no
worker threads and with benchmark coverage for that policy.
Task 32 adds SGC migration behavior for the runtime: stale persisted plans are
invalidated before tick zero with `.xace/proof/sgc-migration/<cgs_hash>.json`
proofs for schema, plan-version, adapter-protocol, and migration-status
mismatches, and no silent downgrade or CGS-derived fallback is allowed.
Task 33 adds the local retained `tools/sgc_runtime_proof.py` command, which writes
`.xace/proof/sgc-runtime/<run-id>/` evidence for real CGS generation, real SGC
compilation, strict runtime persisted-plan load, per-tick world hash logging,
and replay comparison without fake wiring.
Task 34 adds `tools/cgs_end_to_end_proof.py`, which retains one artifact bundle
for generated CGS creation, real SGC compilation, strict runtime persisted-plan
load, deterministic tick replay, runtime control-socket replay validation,
rollback failure restoration, and live adapter snapshot output. The hosted
`cgs-e2e-proof` job runs that command and uploads `.xace/proof/cgs-e2e-ci/`
for retention. Plugin/external executor registration and release-wide artifact
signing remain later gates.
