# XACE Side-Channel Hash Policy

Status: Task X10-011 authoritative runtime policy.

This document defines the hash treatment for side channels that can affect
deterministic execution but may not always live directly in component tables.
The executable source of truth is
`packages/runtime-core/src/determinism_guard/side_channel_hash_policy.rs`.

## Canonical World Hash Inputs

`WorldHasher::compute()` now feeds these fields in fixed order:

1. `tick`
2. `schema_version`
3. `execution_plan_version`
4. `cgs_hash`
5. `rng_state`
6. `event_queue_state`
7. `mutation_queue_state`
8. `is_clean`
9. `entity_store_snapshot`
10. `component_tables_snapshot`

`world_hash` itself is never hashed into its own digest. Engine feedback
buffers, network input buffers before materialization, save-slot metadata, and
adapter playback side effects are not live world-state fields; they are covered
by the policy table below.

## Policy Table

| Channel | Hash Treatment | Proof / Enforcement |
| --- | --- | --- |
| RNG | Direct world-hash input. | `WorldHasher` feeds `WorldSnapshot.rng_state` including `world_seed` and sorted stream positions. `RngInterceptor` gates legal RNG access. |
| Event queue | Direct world-hash input. | `WorldHasher` feeds pending events and `next_event_id`. Clean tick snapshots are normally empty because `PhaseOrchestrator` dispatches events before tick-end hashing. |
| Mutation queue | Direct world-hash input. | `WorldHasher` feeds all pending mutation queues. `MutationGate` applies clean-tick mutations before hashing and hash-proves rollback after failed batches. |
| Feedback queue | Excluded from live world hash; replay-integrity logged. | `FeedbackBuffer` is transient. `RuntimeOrchestrator` drains it at tick start and records messages in `FeedbackLog` with entry hashes and `session_hash`. |
| Network input buffers | Excluded before materialization; materialized into world hash. | Network packets have deterministic digests/log chains. Runtime engine input packets are applied to the `INPUT` component before simulation ticks, then component state is hashed. |
| Save state | Excluded from live tick hash; persisted hash carrier. | Save files carry canonical `WorldSnapshot.world_hash`; metadata carries `cgs_hash` and `asset_hash`. Restore validates the snapshot hash before mutating live state. |
| Adapter side effects | Explicitly excluded derived output. | `EnginePlaybackCommand` batches, rendered objects, audio handles, and transport side effects are derived from semantic events/bindings after simulation. They do not own authoritative world state. |
| Asset binding state | Direct world-hash input through CGS/component state. | CGS semantic binding changes alter `cgs_hash`; committed asset refs inside component JSON alter component-table hash input. Engine-loaded asset objects remain adapter side effects. |

## Injected Divergence Tests

`cargo test -p xace-runtime-core side_channel_hash_policy --lib` proves the
policy with injected divergence tests for all required channels:

- RNG stream position divergence changes `WorldHasher` output.
- Event queue divergence changes `WorldHasher` output.
- Mutation queue divergence changes `WorldHasher` output.
- Feedback payload divergence changes `FeedbackLog.session_hash`.
- Network input divergence changes `InputLog` hash and hashed `INPUT` component state.
- Save-state corruption changes the recomputed snapshot hash.
- Adapter playback command divergence is explicitly excluded as derived output.
- Asset binding divergence changes `cgs_hash` or asset-ref component hash.

## Remaining Boundaries

X10-011 completes the side-channel hash policy. X10-012 and X10-013 still own
full snapshot-completeness hardening and full canonical snapshot
serialization/deserialization for every authoritative field.
