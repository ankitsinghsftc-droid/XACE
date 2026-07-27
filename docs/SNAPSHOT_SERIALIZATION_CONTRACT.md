# XACE Snapshot Serialization Contract

Status: production contract for X10-013.

`SnapshotSerializer` serializes and deserializes the complete
`WorldSnapshot` serde schema. Deserialization must never fall back to
`WorldSnapshot::minimal`, because that drops authoritative rollback and save
state.

## Required Fields

Serialized snapshots must include:

| Field | Purpose |
| --- | --- |
| `tick` | Authoritative simulation tick. |
| `time_seconds` | Fixed64 informational time, encoded as integer micro-units. |
| `schema_version` | CGS schema compatibility marker. |
| `execution_plan_version` | SGC/runtime execution plan compatibility marker. |
| `cgs_hash` | Active CGS identity for restore/hash validation. |
| `entity_store_snapshot` | All entity records and next ID state. |
| `component_tables_snapshot` | All non-empty component tables and rows. |
| `rng_state` | World seed plus recorded stream positions. |
| `event_queue_state` | Pending event queue image. |
| `mutation_queue_state` | Pending mutation queue image. |
| `world_hash` | Stored canonical world hash. |
| `is_clean` | Whether the snapshot was taken at a clean tick boundary. |

## Enforcement

- `SnapshotSerializer::serialize` validates `WorldSnapshot` before writing.
- `SnapshotSerializer::deserialize` uses `serde_json::from_str::<WorldSnapshot>`
  and validates the decoded snapshot.
- Missing legacy-minimal fields are rejected with rule `X10-013`.
- `SnapshotSerializer::compute_hash` clears `world_hash` before hashing the
  canonical JSON image so snapshots do not hash their own stored digest.

## Verification

Run:

```powershell
cargo test -p xace-runtime-core snapshot_serializer --lib
```

The X10-013 tests round-trip a rich snapshot containing entities, components,
archived records, RNG state, pending events, pending mutations, `cgs_hash`,
fixed-point time, world hash, and clean-boundary status. A deterministic
32-case fuzz loop repeats this over varied values and verifies canonical output
stability after deserialize/serialize.
