# XP-003 completion - 2026-09-24

1. **Implemented.** Opt-in World Contract v1 compilation through the existing
   Schema Factory; immutable content/manifest bytes on CompiledSchemaPackage;
   stable object/actor/target bindings; bounded box, trigger, spawn and anchor
   vocabulary; explicit capabilities; registered typed asset requirements; canonical
   content hashing and source/package provenance. Rust exposes the matching typed
   reader, strict validation, canonical serialization, hashing and manifest checks.
   No runtime mutation, geometry execution, native-engine or session path was added.

2. **Exact files.** Nineteen task paths, relative to the saved pre-XP-003 working
   tree. Pre-existing Agent/BYOK, XP-001 and XP-002 work is preserved.

   - `MASTER_PLAN.md`
   - `docs/source_inventory.json`
   - `docs/XACE_PLAYER_LIVE_SESSION_WORLD_ROADMAP.md`
   - `packages/core/src/lib.rs`
   - `packages/core/src/world/mod.rs`
   - `packages/core/tests/test_world_contract.rs`
   - `packages/core/tests/fixtures/world_contract_v1/source.cgs.json`
   - `packages/core/tests/fixtures/world_contract_v1/world.canonical.json`
   - `packages/core/tests/fixtures/world_contract_v1/manifest.json`
   - `packages/core/tests/fixtures/world_contract_v1/malformed_vectors.json`
   - `packages/schema-factory/src/schema_factory.py`
   - `packages/schema-factory/src/compiled_schema_package.py`
   - `packages/schema-factory/src/portable_compilation.py`
   - `packages/schema-factory/src/world_contract.py`
   - `packages/builder-workspace/server/tests/test_world_contract.py`
   - `tools/xp003_world_proof.py`
   - `docs/adr/XP-003-world-contract.md`
   - `docs/XP003_COMPLETION.md`
   - `docs/evidence/xp003-baseline.json`

3. **Design decisions.** Geometry derives from compiled actor blueprints and
   existing UCL components. Stable IDs are explicit semantic tokens, not array
   indices or runtime EntityIDs. World content excludes source hash, native asset
   paths/resolution and display names, while a separate WorldIdentity manifest
   binds content to source CGS and the containing compiled schema package. This
   preserves identical geometry bytes when equivalent CGS lists reorder. Reuse
   WorldSize, Gravity, Fixed64, AssetType, the XP-001 identity types/capability
   vocabulary and the existing strict CGS validator. No UCL/DCL/GCL component
   definitions were changed. Details and the input format are in the XP-003 ADR.

4. **Scope clarifications.** The package binding is to CompiledSchemaPackage;
   the playable archive/manifest belongs to XP-007 and must later pin WorldIdentity.
   Native event-playback bindings remain distinct from world object bindings.
   The initial resource bound caps all objects (including points) at 4,096, a
   conservative extension of the XP-001 AABB bound. This task compiles initial
   geometry/roles; it does not execute kinematic motion or enforce per-tick query
   displacement (XP-004). World size retains its WorldDefinition meaning; the
   numeric profile independently bounds geometry endpoints. No legacy project is
   automatically opted in or migrated; XP-002's template restrictions remain.

5. **Tests and exact results.** All selected verification passed.

   - `cargo test -p xace-core -p xace-runtime-core -p xace-network-core
     -p xace-engine-adapter -p xace-system-graph-compiler --offline --quiet`:
     **1,906 passed**, zero failures/ignored, 33 result groups. Includes four new
     World Contract tests and the shared **23-case malformed reader corpus**.
   - `python tools/python_test_gate.py --suite schema-factory --suite gde
     --suite project-system --suite asset-registry --suite dcl --suite inference
     --suite builder-server --output tmp/xp003-python.json`:
     **1,130 passed**, zero failures/errors/not-run: Schema Factory 127, GDE 200,
     project-system 11, asset registry 207, DCL 14, inference 233, Builder 338.
     This broad run included the initial nine world tests. After review added
     four edge tests and tightened only the opt-in world code, the final focused
     `python -m unittest discover -s packages/builder-workspace/server/tests
     -p test_world_contract.py -v` passed **13/13**. Counts overlap and are not summed.
   - The focused Python tests cover an 18-case malformed-source corpus stopping
     before SGC, stale CGS hash, deterministic bytes, ID preservation, immutable
     views, native asset resolution independence, bounds/count limits, unresolved
     renderer references, manifest/source/version mismatch and capability-role
     contradictions. The real GDE invalid-box edit restores exact prior state;
     CGS, world bytes and manifest files remain unchanged on disk.
   - `python tools/xp003_world_proof.py`: real Factory compile of the six-object
     arena, exact retained golden-byte comparison, reordered-source equality and
     distinct source provenance all pass. Rust reproduces Python's exact bytes,
     verifies its digest/manifest and rejects malformed nested/duplicate JSON.
     Golden world SHA-256:
     `d156f869a9d3884e2dd717ba89a59553688a44801e526ce2800087a5941fe66b`.
   - `cargo check -p xace-core --offline --quiet` and scoped `git diff --check`
     pass. New Rust files were formatted. No UI changed, so XP-002 UI/build checks
     remain historical and were not relabeled as fresh XP-003 results.

6. **Failures discovered.** Initial golden setup omitted the existing required
   per-mode schema version, and an insertion missed its Unicode comment anchor;
   both were corrected before the focused proof passed. No pre-existing test
   failure was found. Source inventory retains its 31 pre-existing unclassified
   paths; all XP-003 additions are classified. Approval review temporarily stopped
   the first implementation write because usage was exhausted; that write did not
   execute and work resumed only after the user restored usage.

7. **Remaining architecture concerns.** The authoring distribution must include
   tools/cgs_schema_validate.py, reused in-process by the compiler. Future consumers
   must verify the world against a trusted package identity before activation;
   manifest self-consistency alone is not trust. XP-004 must implement checked
   geometry queries, movement bounds and deterministic tie breaking. XP-006/007
   must wire world-aware authoring and package distribution. Native rendering,
   session admission and live epoch activation remain later tasks. Existing
   XP-001/002 and AG-030 source-bound evidence remains historical and untouched.

8. **Diff summary.** Nineteen scoped paths; exact per-file additions/deletions
   against tmp/xp003-before are retained in docs/evidence/xp003-baseline.json.
   No commit, push, deployment, dependency change or production CGS rewrite.

9. **Acceptance.** Satisfied for World Contract v1's declared profile: equivalent
   reorders produce identical content bytes/hash; stable IDs survive insertion;
   invalid geometry, IDs, transforms, bindings and assets reject before commit;
   source/package provenance is verified; rejected edits preserve prior artifacts.

10. **Recommendation: READY FOR XP-004.** XP-004 has not started. This is compiler
    and contract readiness, not Player, native-engine or multiplayer certification.
