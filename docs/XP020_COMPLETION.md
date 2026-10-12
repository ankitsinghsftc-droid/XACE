> Reconstructed historical document. Original retained evidence remains missing; fresh recovery acceptance is pending. See AGENT_PROGRESS.md. Do not reuse historical disposable paths for unique evidence.

# XP-020: replay across recorded ruleset epochs

Implemented on 2026-10-04 in the isolated `xp-016` worktree. Protected branches
remain untouched; no commit or push was performed.

## Product capability

`packages/runtime-core/src/runtime_orchestrator/epoch_replay.rs` defines versioned
`ReplayBundle`, `ReplayEpoch`, `ReplayTick`, `SealedReplay` and `ReplayReport`
contracts. A sealed bundle includes:

- The initial clean-boundary snapshot, seed, input-application policy and exact
  initial CGS, persisted plan, compiled world and world-manifest bytes.
- The historical host executable digest. Verification requires that exact host;
  it never substitutes the currently installed implementation for missing code.
- The authority's actually applied input packets, after live admission and
  quantization; permitted feedback after validation; required peers, missing
  peers, release decision and wait count for each executed tick.
- Canonical entity/component state, events, world hash and persisted schedule
  identity for every tick.
- Candidate artifacts and migration mapping for every activation, with the
  flushed XP-019 journal and migrated snapshot hash. Preparation identity,
  candidate digest, checkpoint and publication must agree during replay.

The recorder starts before tick zero and captures the initial simulation boundary
after admission setup. It records successful executed ticks, not render frames.
The final bundle is written with create-new semantics and a digest over its
contents. Truncated, modified, incomplete or out-of-range histories fail visibly.
The supported format is bounded to 100,000 ticks and a 512 MiB serialized bundle;
this is an in-memory recorder sealed on successful shutdown, not a crash-resumable
streaming recorder. Failed/incomplete exports are not certified recordings.

## Offline execution and seeking

Verification materializes only the fixed historical artifact names into a new
scratch directory. It creates a runtime with the matching host registration,
restores the initial snapshot and feeds the recorded accepted input/feedback
sequence. Network waits and admission are not rerun: their recorded decisions
explain which authoritative inputs were released at each simulation boundary.

At each recorded activation it validates the durable journal and parent snapshot,
then reuses XP-018/XP-019's isolated MutationGate migration and historical plan.
The configuration mapping must be a subset of the trusted host registration.
Every tick compares world hash, full canonical state, events and schedule. The
first mismatch reports the tick, epoch, hashes, compared dimensions, inputs and
scheduled systems. Missing historical code, plan, world or activation evidence
never falls back to current rules.

Seeking or rewinding creates another offline fork and reexecutes the historical
sequence through the requested tick, including earlier schedules at epoch
boundaries. This does not weaken XP-019's ordinary live snapshot-restore fence.
No engine bridge or control socket is opened by the offline command. Headless
verification emits no presentation effects, so repeated verification cannot
duplicate audio, particles or other engine effects. Rendered replay navigation
and creator UI integration remain XP-021 work.

## Commands and tests

Authority recording adds `--epoch-replay-out <new-file>` to its existing launch
arguments. Offline verification uses the recorded host executable:

```text
xace_reference_host --epoch-replay-in replay.json --epoch-replay-report report.json
xace_reference_host --epoch-replay-in replay.json --epoch-replay-report before.json --epoch-replay-through-tick 7
```

The commands take trusted local paths; no path-bearing socket command was added.
Artifacts are retained in the new report-adjacent scratch directory for inspection.
Historical sessions lacking a complete bundle cannot be retroactively certified.

`tools/xp020_replay_proof.py` records an actual Player+Unity+Godot+Unreal session
with 140 accepted input packets and a configuration activation at tick 8. It
verifies prefixes before and at activation, all 40 ticks afterward, a repeated
full replay and a backward seek. The reference assertions stay in the removable
package/proof tools; replay has no wall-run or shockwave branch.

Final regression gates cover 842 runtime tests and 22 reference-package tests.
The replay integration test includes two activations, repeated forward/backward
verification, first-divergence diagnosis, unchanged live state/history, missing
epochs/code/plan/world, corrupted bundle/journal and an out-of-range seek.
See `docs/evidence/xp020-baseline.json` for actual-run results and fingerprints.

Reproduction:

```text
cargo test -p xace-runtime-core --lib --tests
cargo test -p xace-reference-mechanic --all-targets --features activation-fault-injection
cargo build -p xace-reference-mechanic --bin xace_reference_host
python -m tools.xp020_replay_proof --stage --out target/xp020/fresh-proof
```

With a shared Cargo target directory, first copy the production host into the
worktree's `target/debug/xace_reference_host.exe`. The native Unreal project must
already be staged/built at `target/xp019/native`, as documented for XP-019.

## Certification boundary

This is Windows-only evidence from one computer using Unity 6000.4.9f1,
Godot 4.6.3 and Unreal 5.7.4. Linux/macOS and three-OS determinism are not claimed.
The live mutation profile remains registered, read-only configuration replacement;
other migration hooks remain unsupported. General World Contract semantics and
package-defined mechanics remain unrestricted by reference-fixture names.

Earlier XP-010 clean-machine, XP-014 two-machine, XP-015 public/two-network gates
and the older missing-cosmetic startup limitation remain pending.
