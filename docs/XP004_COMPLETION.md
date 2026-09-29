# XP-004 completion - 2026-09-24

1. **Implemented.** Typed authoritative geometry queries through scheduled
   ISystemContext reads: bounded swept AABB, overlap, ground/side probes, stable
   contact normals and squared-distance targeting. World Contract identity bindings
   make equal hits independent of actor creation order. Geometry derives from
   canonical components; writes remain deferred through MutationGate.

2. **Failure behavior.** Invalid geometry, query bounds or access declarations
   poison the system context even if caught. Failed scheduled ticks restore prior
   phase movement, entities, tables, events and RNG audit state, discard pending
   mutations and halt until snapshot recovery. No partial movement delta is returned.

3. **Exact task files.** Sixteen paths relative to the saved pre-XP-004 tree.
   Earlier Agent/BYOK and XP-001/002/003 work remains preserved.

   - `MASTER_PLAN.md`
   - `docs/XACE_PLAYER_LIVE_SESSION_WORLD_ROADMAP.md`
   - `docs/XP004_COMPLETION.md`
   - `docs/adr/XP-004-authoritative-geometry.md`
   - `docs/evidence/xp004-baseline.json`
   - `docs/source_inventory.json`
   - `packages/core/src/contracts/interfaces.rs`
   - `packages/core/src/geometry.rs`
   - `packages/core/src/lib.rs`
   - `packages/runtime-core/src/geometry.rs`
   - `packages/runtime-core/src/lib.rs`
   - `packages/runtime-core/src/phase_orchestrator/parallel_executor.rs`
   - `packages/runtime-core/src/phase_orchestrator/phase_orchestrator.rs`
   - `packages/runtime-core/src/phase_orchestrator/system_context.rs`
   - `packages/runtime-core/src/query_engine/query_engine.rs`
   - `packages/runtime-core/tests/test_geometry_v1.rs`

4. **Decisions.** Fixed64 inputs, exact rational time-of-impact ordering, bounded
   i128 arithmetic, u128 squared distance and conservative travel rounding. Stable
   world IDs precede runtime-only EntityIDs. Initial overlap, corners, tangency,
   touching, zero motion, trigger selection and layer masks have explicit rules.
   The per-call spatial view avoids stale caches after snapshot restore. Full
   policy and integration API: [XP-004 ADR](adr/XP-004-authoritative-geometry.md).

5. **Verification.** Final selected Rust regression command:
   `cargo test -p xace-core -p xace-runtime-core -p xace-network-core
   -p xace-engine-adapter -p xace-system-graph-compiler --offline --quiet`:
   **1,924 passed, 0 failed, 0 ignored, 34 result groups**. Includes all **18 new
   geometry tests**. The focused test command with `-- --nocapture` also passes
   18/18; these counts overlap and are not summed. Its numerical corpus includes
   **5,766** independently checked axis/gap/speed combinations. Tests cover all six
   directions, permutation/equal-hit ordering, stable IDs under swapped EntityIDs,
   extreme integers, exact endpoint hits, 16-metre thin-wall sweeps, filtering,
   malformed geometry, declared access, XP-003 golden compatibility, kinematic
   updates, snapshot restore, event/RNG rollback and caught-error rejection in
   both sequential and parallel-eligible execution.

   The scheduled query-to-MutationGate replay produced these identical hashes
   before and after snapshot restore (ticks 0, 1, 2):

   - `d3c2db0121a6e3692c1e768e3d2df813dd7e5c110d699517dd1f788bb9b93d47`
   - `692f8b3aa48883532dee45d64fe140f006fb03aeb19035de435c996690c0e2b0`
   - `95de87f15e5f0fab1f5cde8aa2fad32981ee2053075abc088b51ca04d4e4dfe6`

   No Python/UI behavior changed, so those suites were not rerun. Earlier XP-003
   evidence remains historical rather than being relabeled as a new run.

6. **Limits.** Verified locally on Windows x64. No extra OS/native-engine/network
   certification or maximum-scene 60 Hz throughput claim. Geometry is sampled at
   query time; two-body relative motion and movement response are later consumers.
   The query layer does not turn arbitrary transform writes into collision solving.
   Immutable identity installation is available to loaders; playable package
   verification/activation wiring belongs to XP-007. Legacy unbound callers use
   EntityID ties. XP-002 legacy migration restrictions remain. Checkpoint copies
   and linear scans need later performance measurement. The source inventory still
   has its 31 pre-existing omissions; no new XP-004 source is unclassified.

7. **Result.** XP-004 complete for its declared query-layer profile. READY FOR
   XP-005. XP-005 has not started. No Player or live-session launch claim is added.
   Source-bound record: [xp004-baseline.json](evidence/xp004-baseline.json).
