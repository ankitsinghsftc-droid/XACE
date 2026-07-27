# Replay Divergence Diagnosis

Task: X10-015

Status: implemented on 2026-07-24.

## Contract

When recorded replay validation finds the first divergent tick, the runtime
returns a `RuntimeReplayMismatch` with a structured
`RuntimeReplayDivergenceDiagnosis`.

The diagnosis includes:

- Tick and expected/actual hash prefix summary.
- Suspected SGC group when the recorded schedule can map the tick to a group.
- Candidate systems from the SGC schedule.
- Component mutation evidence from the tick `StateDelta`.
- Emitted event identifiers, event type, source/target entity, and payload keys.
- RNG access records by system, tick, deterministic flag, and issued seed.
- Mutation counts for applied mutations and state change categories.
- Engine input packet trace with peer, tick, sequence, player, actions, digest,
  applied flag, and status.
- Expected and actual per-tick replay traces for tooling and readable debug
  output.

## Runtime Binding

`RuntimeOrchestrator::tick` now records a compact `RuntimeTickReplayTrace` for
each completed tick. `RuntimeOrchestrator::validate_recorded_replay_from_cgs`
collects the same trace during live replay and attaches a diagnosis object to
the first hash mismatch.

`RngInterceptor::accesses_for_tick` exposes deterministic RNG access records in
stable system order so the replay report can identify RNG use at the divergent
tick.

## Evidence

Focused test gate:

```powershell
cargo test -p xace-runtime-core x10_015 --lib
```

The injected-divergence tests cover:

- Generated runtime systems under a persisted SGC group.
- Component update evidence for `COMP_COUNTER_V1.count`.
- Emitted `generated.loot_roll` event evidence.
- RNG seed evidence for `GeneratedLootRollSystem`.
- Mutation count and state change evidence.
- Engine input packet evidence for a queued `Attack` input.

Launch certification includes the focused `runtime replay divergence diagnosis`
check.
