# XP-004: Authoritative geometry queries v1

Accepted implementation, 2026-09-24. Scope: the minimal Rust geometry query layer.

## Contract and ownership

`xace_core::geometry` contains versioned typed requests/results. Systems call
`ISystemContext::geometry_query_v1` from their persisted ExecutionPlan. Contexts
without this extension return an unsupported error. There is no engine-contact
input, system scheduling, mutation, or CGS edit in the query implementation.
Movement consumers still submit component writes through MutationGate.

Sweeps, overlaps and probes require declared reads of UCL transform (1) and collider
(4); a declared write also grants read access under the existing context contract.
Targeting reads only transform (1), from an explicit bounded candidate set. Access
is checked even for empty queries. SGC continues using ordinary component access
sets: no hidden access declarations or new UCL components are introduced.

Every call derives an immutable, validated spatial view from the current canonical
component tables. No spatial cache is serialized, and no geometry survives a
component update or snapshot restore independently of those tables. A linear scan
of at most 4,096 bodies is intentional for this first profile.

`QueryEngine::bind_world_geometry` installs validated World Contract object-to-entity
identities from the loader's actor binding map. Installation is atomic: missing,
zero or aliased bindings leave the previous binding intact. This map contains no
positions. A package activation must install its own binding; restoring a snapshot
of the same world preserves entity IDs and reuses the binding. The future package
loader must verify artifact provenance and supply the actual spawn map; this API
is not package admission or a proof that caller-supplied IDs exist in a live store.

Bound objects sort lexically by stable World Contract ID. Unbound runtime objects
sort after bound objects by EntityID (D3). Equal-time contacts and equal-distance
targets use this identity ordering. Contacts/targets expose both IDs when bound.
Overlap results use the same order. This makes bound-world ties independent of
actor creation and component insertion order. Legacy unbound ECS callers retain
entity-ID ordering; they are not silently treated as activated portable packages.

## Numeric and contact policy

- Existing Fixed64 raw micro-units; right-handed Y-up, forward -Z.
- Centers and box endpoints remain within +/-8,192 metres. Half-extents are
  positive and at most 4,096 metres, matching XP-003's contract validator.
- Sweep displacement has Euclidean length at most 16 metres. The entire requested
  endpoint must remain inside the profile even if a collision would stop it sooner.
- Only axis-aligned BOX colliders, identity rotation/scale and no parent transform.
  In the XP-003/004 portable profile, source collider `size` is full width and must
  contain positive even micro-unit values; queries use explicit half-extents.
  This follows the XP-003 compiler contract, not older ambiguous UCL size comments.
- Collider offset is included; missing layer mask uses existing UCL DEFAULT (1).
  Noninteger, string, missing required, out-of-range and unsupported shape data
  reject. Excluded/filter-mismatched colliders are still structurally validated.
- All slab times are exact rational values compared with bounded i128 products.
  Returned time is a reduced nonnegative fraction. Travel rounds toward the start
  per axis. There is no floating-point arithmetic, epsilon or saturation fallback.
- Positive-volume initial overlap reports time zero and the least-penetration
  normal. Equal normal choices order X, Y, Z, negative before positive.
- Overlap excludes mere touching. A touching face blocks motion into the face at
  time zero; stationary, tangential or separating motion does not block. A contact
  only grazing a corner for zero duration is excluded. Endpoint impact is included.
- Zero displacement reports initial overlap only. Ground probes sweep along -Y;
  side probes use +/-X or +/-Z. Probe distance is nonnegative and bounded.
- Solids/triggers/all, layer intersection and self exclusion are explicit filters.
  The result reports all hits in exact time/identity order; it is not a slide,
  depenetration, rigid-body or moving-platform response solver.
- Target distance uses raw micro-units squared in u128. Radius is at most 16,384
  metres; candidates must be unique, nonzero and at most 4,096. Missing transforms
  reject. Radius inclusion is inclusive; no square roots or float conversion.

Kinematic geometry is sampled from canonical state at the scheduled query boundary.
Relative two-body continuous motion, carrying riders and wall-run response belong
to later scheduled movement systems. Swept movement through the sampled geometry
cannot tunnel within the declared bounds; endpoint teleport writes are not secretly
converted into a physics solver by this read-only API.

## Failure transaction

An invalid geometry query poisons that SystemContext, even if the system catches
its error. Both sequential and parallel-eligible executors reject its outputs.
PhaseOrchestrator now checkpoints entities, component tables, event queues/counters
and RNG audit state before scheduled execution. Any failed tick restores those
checkpoints, discards queued mutations, invalidates query caches and halts without
advancing the tick or returning a delta. This includes movement applied by earlier
phase groups. Subsequent tick attempts fail until the snapshot-restore lifecycle
resets the orchestrator; live restore also resets the DeterminismGuard. Guard
failure diagnostics remain available rather than being erased on error.

This transaction starts at scheduled phase execution. Existing inbound buffering
and legacy engine feedback processing occur before it; XP-002 live-session policy
already excludes gameplay-authoritative physics/visibility feedback. This task does
not redesign input/network ingestion or add real network rollback certification.

Checkpointing copies state each tick and queries rebuild their views. Correctness
is verified; 60 Hz throughput at the maximum scene size has not been benchmarked.

## Evidence and follow-on

See `../XP004_COMPLETION.md` and `../evidence/xp004-baseline.json`. Tests cover the
XP-003 golden arena, 5,766 independent gap-oracle sweep cases, permutations,
semantic-ID ties across entity assignment, boundary/overflow rejection, thin walls,
trigger/layer filters, probes, wide squared distances, declared-access rejection,
snapshot reconstruction, scheduled replay hashes and poisoned-query rollback,
including event/RNG restoration. Verification is local Windows x64; no additional
OS, native-engine, provider, multiplayer, Player or performance certification.

XP-005 owns the wall-run/wall-jump mechanic. XP-007 owns playable package admission
and installation of verified world bindings. No later task is started here.
