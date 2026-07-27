# 06 Determinism Guarantees

Current production-readiness status: local live enforcement exists; full
cross-platform certification remains pending.

XACE has deterministic runtime primitives in `packages/runtime-core/src`:
`DeterminismGuard`, `WorldHasher`, `ReplayValidator`, `RngInterceptor`,
deterministic entity/component ordering, fixed-point authoritative state,
snapshot hashing, runtime schedule identity checks, and focused unit/proof
tests. `RuntimeOrchestrator` owns the live guard/interceptor for ticking
sessions, and `PhaseOrchestrator` calls the tick, phase, system, RNG, and hash
hooks during live execution.

Canonical hash decision:

- Authoritative CGS, world, snapshot, replay, and proof hashes are lowercase
  64-character SHA-256 hex digests.
- Short hash prefixes may be used only as non-authoritative display labels,
  log labels, or cache-key prefixes.
- A 16-character hash must never be treated as a production equality, replay,
  rollback, or certification proof.
- Side-channel hash authority is defined by
  `docs/SIDE_CHANNEL_HASH_POLICY.md` and
  `packages/runtime-core/src/determinism_guard/side_channel_hash_policy.rs`.

Safe claim today:

- XACE has locally enforced live determinism hooks for the Rust runtime tick
  path.
- XACE computes canonical 64-character SHA-256 world hashes every tick in the
  guarded runtime path.
- XACE hashes `cgs_hash`, RNG snapshot state, pending event/mutation queue
  state, clean-boundary status, entity store, and component tables.
- XACE has focused injected divergence tests for the X10-011 side-channel
  policy.

Do not claim yet:

- "Replay determinism is production-proven across Windows, Linux, and macOS."
- "RNG interception prevents all native/OS randomness in arbitrary handwritten
  runtime code without static or sandbox enforcement."
- "Snapshot restore covers every authoritative side channel with full canonical
  serialization/deserialization."

Production gate:

1. Keep `WorldHasher` and `side_channel_hash_policy` green in launch
   certification.
2. Complete X10-012 snapshot-completeness hardening.
3. Complete X10-013 full canonical snapshot deserialization.
4. Complete X10-014 cross-platform replay proof.
5. Pass and retain the 10,000 tick determinism torture proof from
   `docs/XACE_PRODUCTION_READINESS_MASTER_PLAN.md`.
