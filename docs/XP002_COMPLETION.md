# XP-002 completion - 2026-09-24

1. **Implemented.** Builder now compiles through the real Schema Factory and its
   compiled-schema projection into SGC. Registry identity, fields, values, world
   coordinates and system phases reject before SGC. Value-only edits use the same
   candidate validation, with GDE restore on rejection and disablement if restore
   fails. Runtime input is staged and committed by a scheduled Input system through
   MutationGate. Preview uses isolated stores; live-session mode rejects legacy
   preview writes and native physics/visibility authority.

2. **Exact task files.** Changes below are relative to the saved pre-XP-002 dirty
   working tree, not a claim that all current Git changes belong to this task.

   - `MASTER_PLAN.md`
   - `docs/source_inventory.json`
   - `docs/XACE_PLAYER_LIVE_SESSION_WORLD_ROADMAP.md`
   - `packages/schema-factory/src/schema_factory.py`
   - `packages/schema-factory/src/portable_compilation.py`
   - `packages/builder-workspace/server/session_manager.py`
   - `packages/builder-workspace/server/tests/test_factory_authority.py`
   - `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py`
   - `packages/builder-workspace/server/tests/fixtures/prompt_pipeline_contract.py`
   - `packages/runtime-core/src/input_ingress.rs`
   - `packages/runtime-core/src/lib.rs`
   - `packages/runtime-core/src/cgs_loader.rs`
   - `packages/runtime-core/src/runtime_orchestrator.rs`
   - `packages/runtime-core/src/bin/xace_runtime.rs`
   - `tools/xp002_authority_proof.py`
   - `docs/adr/XP-002-authority-boundaries.md`
   - `docs/XP002_COMPLETION.md`
   - `docs/evidence/xp002-baseline.json`

3. **Decisions.** Reuse SchemaFactory, CompiledSchemaPackage.to_sgc_input,
   ISystemContext, MutationGate, rollback snapshots and the existing feedback
   buffer/validator/router. No new compiler, scheduler, simulator, hash identity,
   provider or engine authority. Core registry identity remains frozen; generated
   project components remain GCL. The unused, nonexistent SystemVersion import
   was removed so the real Factory entry point can load. See the authority ADR.

4. **Scope and intentional compatibility changes.** XP-003 is not started.
   The portable adapter is an input representation bridge, not World Contract v1.
   EngineInputSystem must be explicitly declared, have reads=[] / writes=[6], and
   occupy the first singleton sequential Input group. Recompile plans; do not edit
   them by hand. --live-session enables strict restrictions, not multiplayer.
   Authoring preview retains one isolated candidate, with no native rendering.

   Legacy exports and current old default project templates that contain undeclared
   DCL or noncanonical fields now fail closed at Builder apply. They need an
   explicit schema migration before authoring through this boundary. The root CGS
   and canonical_cross_engine_vertical_slice were not rewritten. This is a visible
   compatibility limitation across both Agent and API/BYOK paths, not a provider
   failure. The prompt integration fixture was migrated to declared structured UCL
   so approval, persistence failure, SGC failure and runtime/adapter rollback tests
   still reach their intended stages. Its actor-addition scenario tests an actor
   with canonical transform/identity; it does not claim executing pickup mechanics.
   Supported shipped gameplay primitives compile through the new projection.

5. **Verification.** Final official Python gate: **1,121 passed**, zero failures/errors/not-run:
   Schema Factory 127, GDE 200, project-system 11, asset registry 207, DCL 14,
   inference 233, Builder server 329. Command: `python tools/python_test_gate.py
   --suite schema-factory --suite gde --suite project-system --suite asset-registry
   --suite dcl --suite inference --suite builder-server
   --output tmp/xp002-python-final.json`. Suite-specific syntax/tool stages are
   intentionally disabled by the existing runner; no selected suite was skipped.

   - Offline Rust regression: **1,901 passed**, zero failures/ignored, 32 result
     groups, using cargo test on core, runtime-core, network-core, engine-adapter
     and system-graph-compiler. Final focused runtime run: **7 passed** (one extra
     malformed-plan/live-derived-plan test added after the broad gate), 694 filtered.
   - Factory authority tests: **14 passed**. Covers missing Factory/no fallback,
     invalid world/registry/phase, injected field/type, nonfinite values, empty GCL
     schemas, generated GCL types and failed candidate-restore disablement.
   - Migrated prompt-pipeline tests: **21 passed**, including real GDE and existing
     approval/rollback assertions. Their SGC fixture remains a wiring fixture; the
     separate authority proof below uses the actual Rust SGC binary.
   - Real offline Builder -> GDE -> Factory -> SGC -> runtime proof passed via
     python tools/xp002_authority_proof.py. Three ticks, two identical full schedule
     and world-hash reports; invalid world and invalid value edit preserve project
     artifact hashes; rejected edit restores exact previous GDE state. No provider,
     native editor or networking is invoked. Evidence contains hashes and scope.
   - Runtime preview before/after hash:
     c170b4a7e027ce5d0f2f0223cadb0c7a560372fb3d6e17d7dd031089260785af
     in both cases. Packet staging, absent ingress, invalid/timed input, reordered
     packets and native feedback rejection also preserve the asserted boundaries.
   - Builder npm run lint, typecheck, test:ui and build all passed.
   - git diff --check passed; Git emitted line-ending normalization warnings.
     Source inventory still reports the same 31 pre-existing unclassified paths;
     all XP-002 additions are classified.

6. **Failures found and resolved.** The first Rust run found eight old input test
   fixtures without an ingress declaration; two shared fixture builders now declare
   it explicitly. A subsequent build hit a Windows executable lock while the proof
   runtime was running; rerun passed. Initial Python runs exposed canonical numeric
   type/GDE generated-schema adaptation gaps, fixed in the adapter, then 14 prompt
   tests using the invalid legacy template, addressed with the explicit fixture
   migration above. No tests were skipped or assertions disabled. The old template
   incompatibility remains intentional and documented, not labeled a passing flow.

7. **Remaining architecture work.** Migrate/certify legacy project templates before
   exposing them through the new Player/package path. XP-003 must implement actual
   world semantics, identities and geometry validation; this task only validates
   existing world coordinates. Later session work must bind peer ownership and
   admission to sockets and require strict runtime configuration. Native animation,
   contact and visibility behavior needs its own future certification. Existing
   source-bound AG-030/XP-001 evidence is historical and is not silently refreshed.

8. **Git summary.** Eighteen task paths, with pre-existing Agent/BYOK changes and
   XP-001 artifacts preserved. No commit, push, native-engine change or deployment.
   Per-file additions/deletions relative to the saved baseline are in the evidence
   manifest; unrelated working-tree changes are excluded from those counts.

9. **Acceptance.** Satisfied for the declared supported profile. The focused
   authority criteria pass: invalid schemas stop before SGC, external input writes
   use scheduled MutationGate, previews preserve live hashes, and providers/engines
   receive no direct commit capability. This is not whole-XACE product readiness.

10. **Recommendation. READY FOR XP-003**, with the documented legacy-template
    migration requirement before those projects can use the new authoring/package
    path. XP-003 has not started.
