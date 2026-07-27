# XACE Snapshot Completeness Policy

Status: production contract for X10-012.

`WorldSnapshot` restore is production-supported at clean tick boundaries. A clean
boundary means all phase mutations have been applied, all phase events have been
dispatched, no per-system RNG stream is live across the boundary, and the
snapshot hash was computed by `WorldHasher`.

## Included In WorldSnapshot

| Channel | Snapshot Field | Restore Contract |
| --- | --- | --- |
| Entity records | `entity_store_snapshot.entities` | Rebuilds entity metadata and `next_entity_id`. |
| Component tables | `component_tables_snapshot.tables` | Clears rows absent from the snapshot and restores every recorded row. Empty table registrations are retained. |
| Archived entities | `entity_store_snapshot.entities[state=Archived]` | Reconstructs `EntityArchive` from archived records and `destroyed_tick`. |
| RNG stream positions | `rng_state.stream_positions` | Must be empty for production clean-boundary restore; non-empty live stream positions are rejected. |
| Events | `event_queue_state` | Must be empty for production clean-boundary restore; pending events are rejected. |
| Mutations | `mutation_queue_state` | Must be empty for production clean-boundary restore; pending mutations are rejected. |

## Explicit Exclusions

| Channel | Reason | Restore Action |
| --- | --- | --- |
| Feedback | Engine observation input, not authoritative simulation state. | Runtime drains/resets `FeedbackBuffer`, validator state, and `FeedbackLog`. |
| Network sync buffers | Raw inbound buffers are transient; accepted inputs are materialized before ticking. | Runtime clears pending engine inputs and disconnects bridges. |
| Save state | Save-slot metadata is a persisted envelope around the snapshot. | Save engine verifies the snapshot hash/metadata before restore. |
| Adapter side effects | Rendered objects, sockets, audio handles, and playback commands are derived outputs. | Runtime clears playback commands; adapters rebuild from future snapshots/deltas. |

## Enforcement

- Executable policy: `packages/runtime-core/src/snapshot_engine/snapshot_completeness_policy.rs`.
- Restore gate: `SnapshotEngine::restore_snapshot` calls `validate_restorable_snapshot`.
- Runtime precheck: `RuntimeOrchestrator::restore_world_snapshot` validates before disconnecting engines or clearing buffers.
- Archive repair: `EntityStore::restore_from_snapshot` infers permanent archive entries from archived entity records.
- Table repair: `ComponentTableStore::restore_from_tables_snapshot` clears rows absent from the snapshot while preserving registered empty tables.

## Verification

Run:

```powershell
cargo test -p xace-runtime-core x10_012 --lib
cargo test -p xace-runtime-core snapshot_engine --lib
cargo test -p xace-runtime-core runtime_orchestrator --lib
```

The X10-012 runtime test proves that a clean snapshot restored after rollback
replays to the same subsequent world hashes as the original timeline.
