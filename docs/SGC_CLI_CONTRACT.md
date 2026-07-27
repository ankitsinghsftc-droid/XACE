# SGC CLI Contract

The production SGC binary reads one JSON document from stdin and writes one
JSON document to stdout or stderr.

## Input

Schema: `docs/schemas/xace-sgc-cli-input.schema.json`

The input envelope is:

```json
{
  "schema": "xace.sgc.cli.input.v1",
  "schema_version": "0.1.0",
  "plan_version": 1,
  "cgs_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "systems": [
    {
      "id": "MovementSystem",
      "display_name": "MovementSystem",
      "phase": "Simulation",
      "reads": [5],
      "writes": [1],
      "depends_on": ["InputSystem"],
      "deterministic": true,
      "version": {"major": 1, "minor": 0},
      "description": "Applies velocity to transforms."
    }
  ]
}
```

`systems[]` is the CGS `SystemDefinition` contract: `id`, `display_name`,
`phase`, `reads`, `writes`, `depends_on`, `deterministic`, `version`, and
`description`. The CLI still accepts legacy `version_major` and
`version_minor` when `version` is absent.

## Success Output

On success, stdout contains an `ExecutionPlan` JSON document. The CLI stamps
`compiled_from_cgs_hash` from the input `cgs_hash`. Stderr is not part of the
success contract.

Persisted Builder artifacts are governed by
`docs/SGC_EXECUTION_PLAN_CONTRACT.md` and
`docs/schemas/xace-sgc-execution-plan.schema.json`. Builder canonicalizes and
enriches accepted plans with component access sets, system metadata, and a
proof-bundle reference, plus the current `adapter_protocol_version` and
`migration_status`, before storing them at
`.xace/execution_plans/<cgs_hash>.plan.json`, where the filename stem must
match `compiled_from_cgs_hash`.

## Builder Acceptance Validation

Builder validates every successful `ExecutionPlan` with
`packages/builder-workspace/server/sgc_plan_validator.py` before storing it as
load-ready proof. The validator checks:

- `schema_version`, `plan_version`, `plan_hash`, and `compiled_from_cgs_hash`
- exact match between CGS `SystemDefinition` IDs and `all_system_ids`
- exact match between scheduled systems and `all_system_ids`
- no duplicate scheduled systems
- no non-deterministic systems in parallel groups
- no write/write or read-after-write hazards inside parallel groups
- integer read/write component IDs for rollback compatibility

Validation failure blocks the Builder apply before the updated CGS is persisted
and returns a `server_error` with `code`, `message`, `action`, `sgc_error`, and
`sgc_validation`.

## Error Output

On every failure, stderr contains one JSON object:

```json
{
  "schema": "xace.sgc.cli.error.v1",
  "ok": false,
  "code": "INVALID_PHASE",
  "category": "invalid_input",
  "message": "Invalid phase for system 'MovementSystem': 'BadPhase'.",
  "exit_code": 1,
  "system_id": "MovementSystem"
}
```

Exit codes:

- `1`: invalid input or non-cycle/non-conflict compilation failure
- `2`: cycle detected
- `3`: conflicting system graph
- `4`: stdin or output serialization failure

## Runtime Status

As of Task 30, Builder stores SGC execution plans and proof bundles, and the
standalone runtime can load the persisted plan as its authoritative schedule
when launched with `--require-sgc-plan` or an explicit `--sgc-plan` path. In
that strict mode, missing, stale, malformed, hash/schema/plan-version
mismatched, adapter-protocol mismatched, component/system-mismatched,
migration-pending, non-deterministic, or unregistered-system plans fail before
tick zero. Non-SGC fixture runs may explicitly use the CGS-derived compatibility
path with `--derive-cgs-plan`; that path also fails before tick zero when any
declared system lacks a runtime executor and writes a
`.xace/proof/runtime-compatibility/<cgs_hash>.json` proof artifact instead of
filtering unsupported systems. Generated systems now normalize through the
local generated-system ABI before registry insertion. The supported executor
kinds are `generated.increment_numeric_field` and
`generated.emit_event_on_rng_threshold`; both declare and validate inputs,
reads, writes, events, RNG budget, `halt_and_rollback` errors, and rollback
hooks before executing through `SystemContext`, `MutationGate`, deterministic
RNG windows, and the phase-buffered event bus. Generated Rust source now has a
local safe compile/sign gate that runs SystemSpec/runtime ABI validation,
unsupported generated-system rejection, deterministic static checks, Cargo
sandbox checking, real SGC compilation, signed compile-artifact creation, and
runtime signature verification before generated-code-backed executor metadata
can register. The unsupported rejection policy blocks nondeterministic sources,
filesystem/network/process access, engine-only API calls, unsafe/FFI/threading
escapes, and missing rollback hooks with exact local reason codes before SGC.
Runtime ticks now preserve the loaded SGC schedule ABI, including group IDs,
phase order, execution indexes, parallel flags, system order, dependencies,
serialization constraints, and component access sets; persisted parallel
component hazards are rejected by the runtime loader, and
`--schedule-snapshot-out` writes per-tick schedule snapshots for replay checks.
As of Task 31, SGC `parallel=true` means parallel-eligible schedule metadata.
The standalone runtime reports
`parallel_group_execution_policy=deterministic_sequential` and
`parallel_group_worker_threads=false`; systems in those groups are invoked one
at a time in persisted SGC order, with deterministic event merge order retained
for replay and any future worker-thread policy.
As of Task 32, parsed persisted plans that are stale across schema,
template/plan-version, runtime adapter-protocol, or migration-status changes
are rejected before tick zero with a
`.xace/proof/sgc-migration/<cgs_hash>.json` proof. The proof records
`decision=reject_and_regenerate`, `fallback_to_cgs_derived=false`, and
`silent_downgrade_performed=false`; the runtime does not mutate or downgrade
old plan files.
As of Task 33, `tools/sgc_runtime_proof.py` creates a retained
`.xace/proof/sgc-runtime/<run-id>/` proof by generating a CGS with multiple
supported generated systems, invoking the real SGC binary, persisting the
emitted plan with the strict runtime metadata envelope, running the real
runtime in `--require-sgc-plan` mode twice, and comparing schedule snapshots
plus per-tick world hash logs across replay. Certification can pass
`--proof-root` to store the same proof shape in a scratch artifact directory.
As of Task 34, `tools/cgs_end_to_end_proof.py` extends that retained path with
CGS generation evidence, runtime control-socket `replay_record` /
`replay_validate`, rollback failure restoration artifacts, and live adapter
snapshot output. The hosted `cgs-e2e-proof` CI job builds the real SGC/runtime
binaries, runs that proof, and uploads `.xace/proof/cgs-e2e-ci/` artifacts for
retention. Plugin/external executor support and release-wide artifact signing
remain separate gates.

Local integration evidence:

```powershell
python tools/sgc_cli_smoke.py --sgc-bin target-codex-production-sgc-build/debug/xace-system-graph-compiler.exe --json
python tools/sgc_cli_integration.py --sgc-bin target-codex-production-sgc-build/debug/xace-system-graph-compiler.exe --benchmark-threshold-ms 1000 --json
python tools/sgc_runtime_proof.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe --sgc-bin target-codex-task28-safe-compile/debug/xace-system-graph-compiler.exe --ticks 3
python tools/cgs_end_to_end_proof.py --runtime-bin target-codex-task28-safe-compile/debug/xace_runtime.exe --sgc-bin target-codex-task28-safe-compile/debug/xace-system-graph-compiler.exe --ticks 3 --target-dir target-codex-task28-safe-compile
cargo bench -p xace-system-graph-compiler --bench sgc_compile_100 -- --sample-size 10
```
