# XP-001 completion - 2026-09-23

1. **Implemented.** Shared opt-in typed/versioned CGS, persisted SGC, world,
   gameplay package, input, runtime/protocol and session/epoch identities; bounded
   semantic IDs and SHA-256 values; deterministic fail-closed compatibility;
   identity-only provenance with tick and mutation/activation correlation; frozen
   supported-profile ADR; 50 complete golden offers (5 accepted, 45 rejected);
   byte-exact canonical serialization fixture; source-bound evidence index.
   Fixed official DCL SuiteSpec import roots. No live authority path was added.

2. **Exact task files.** The following 17 paths were created or updated:

   - `Cargo.lock`
   - `MASTER_PLAN.md`
   - `docs/source_inventory.json`
   - `docs/XACE_PLAYER_LIVE_SESSION_WORLD_ROADMAP.md`
   - `packages/core/Cargo.toml`
   - `packages/core/src/wire/mod.rs`
   - `packages/core/src/wire/session_contract.rs`
   - `packages/core/tests/test_session_contract.rs`
   - `packages/core/tests/fixtures/session_contract_v1/authority.canonical.json`
   - `packages/core/tests/fixtures/session_contract_v1/game.cgs.json`
   - `packages/core/tests/fixtures/session_contract_v1/golden_vectors.json`
   - `packages/core/tests/fixtures/session_contract_v1/persisted_plan.json`
   - `packages/runtime-core/tests/test_session_contract_versions.rs`
   - `tools/python_test_gate.py`
   - `docs/adr/XP-001-supported-session-contract.md`
   - `docs/XP001_COMPLETION.md`
   - `docs/evidence/xp001-baseline.json`

   The retained game.cgs.json and persisted_plan.json are exact byte copies from
   the existing SGC runtime proof, not regenerated schema or plan identities.
   Cargo only enables serde on the already-present UUID dependency; no new crate
   or version change. MASTER_PLAN/source inventory had pre-existing edits;
   this task adds its own checkpoint/classification without replacing those edits.
   The roadmap was already untracked from the preceding design session.

3. **Design decisions.** Reuse `CgsVersion`, `ExecutionPlan::validate`, existing
   CGS/plan hashes, wire v1, engine protocol v1 and input packet v1. A ruleset is
   the gameplay tuple fenced by session/incarnation/epoch; no redundant aggregate
   hash. Exact gameplay equality is separate from native presentation identity.
   Different certified engine/adapter/client variants are allowed. Unknown
   required capabilities, missing identities, link mismatch and stale/future
   epochs reject. Certification is an authority-supplied allowlist, never a peer
   assertion. Stable world semantics cannot use native paths as artifact IDs.
   Legacy compatibility and wire messages remain unchanged. Future readers must
   opt in explicitly; compatibility success alone cannot authorize or verify a
   package. Source-bound comparison confirms all 15 previously audited compiler,
   runtime, adapter and Builder authority sources are byte-for-byte unchanged.

4. **Roadmap divergence/clarification.** No later task was implemented. The shared
   pure predicate belongs in core/wire so every host can reuse it without a
   network-core dependency. The legacy network predicate is preserved because
   silently changing its equality rules would alter existing workflows. The
   roadmap's suggested minimal arena is represented only by future artifact
   identity fixtures here: world/package/input/runtime hashes are explicitly
   synthetic, not claims of a compiled arena. Real world compilation/package
   output belongs to XP-003/007. Native reader implementations remain XP-016;
   the documented corpus is ready for all three readers to consume.

5. **Exact tests/results.** Commands run from repository root unless stated:

   - `cargo test -p xace-core -p xace-runtime-core -p xace-network-core -p xace-engine-adapter -p xace-system-graph-compiler --offline --quiet`
     passed **1,895 tests**, zero failures/ignored, across 32 test-result groups.
     Includes six new contract tests and one cross-module version/topology guard.
   - `cargo test -p xace-core --test test_session_contract --offline --quiet`
     final rerun passed **6/6** after strengthening the golden host variants to
     have distinct certified adapter/client versions. All **50 vectors** have the
     expected deterministic result; ordering, canonical bytes, identity reuse,
     capability vocabulary and provenance validation pass. No test is a native
     engine execution or a live network proof.
   - `python tools/python_test_gate.py --suite schema-factory --suite gde --suite project-system --suite asset-registry --suite dcl --suite inference --suite builder-server --output tmp/xp001-python-report.json`
     passed **1,107 tests**, zero failures/errors/not-run: schema-factory 127,
     GDE 200, project-system 11, asset-registry 207, DCL 14, inference 233,
     Builder server 315. Agent Mode and API/BYOK regression suites pass.
     The runner's unrelated tool/syntax stages are disabled for suite-specific
     invocation; no selected test suite was omitted or skipped.
   - `python -I tools/python_test_gate.py --suite dcl --output tmp/xp001-dcl-isolated.json`
     passed **14/14** through the official runner without shell import settings.
   - From `packages/builder-workspace`: `npm run lint`, `npm run typecheck`,
     `npm run test:ui`, `npm run build`: all exit 0. UI contract check passes;
     production build transforms 47 modules. Server coverage is the official
     isolated Python gate above; no new provider login or hosted call was needed.
   - `rustfmt --check --edition 2021 packages/core/src/wire/session_contract.rs packages/core/tests/test_session_contract.rs packages/runtime-core/tests/test_session_contract_versions.rs`: exit 0.
   - Scoped `git diff --check`: exit 0; only existing LF/CRLF notices.
   - `python tools/source_inventory_check.py`: exit 1 for **31 pre-existing**
     unclassified paths. All XP-001 artifacts and the preceding XP roadmap/audit
     are classified. The failure is retained in `tmp/xp001-source-inventory.log`.

   Machine-readable results and log hashes are in `docs/evidence/xp001-baseline.json`.
   Full regressions ran before the final presentation-only fixture strengthening;
   the final focused contract rerun verifies those final fixture bytes. Subsequent
   edits were documentation and module declaration ordering only.

6. **Pre-existing failures.** The DCL missing-`packages` discovery failure is fixed.
   Repository-wide source inventory still reports 31 unrelated omissions spanning
   Agent/Codex docs/tools, AGENTS.md and a strategic-roadmap PDF. This is a separate
   documentation backlog, not a failing gameplay/Agent/BYOK regression. The current
   changes classify their own files and do not ignore the inventory checker.
   Initial new-code compilation exposed a missing serde feature on existing UUID;
   it was enabled and every subsequent relevant Rust test passed.

7. **Concerns for later tasks.** XP-002 must still route Builder compilation through
   Schema Factory and close the audited live input/control mutation bypasses.
   XP-003/007 must replace identity-only fixtures with validated, content-verified
   artifacts. XP-011/016 must wire strict admission/certification; XP-018/019 must
   persist activation/fencing. Geometry bounds, input timeout policy and capability
   vocabulary are frozen targets, not implemented gameplay. No change to the
   approved task order is needed. Historical native-engine proof directories are
   absent; retained Windows replay and simulated chaos cannot establish live
   cross-engine conformance. The evidence index labels these scopes explicitly.

8. **Git diff summary.** XP-001 updates six tracked files and one pre-existing
   untracked roadmap, and adds ten task files (17 total paths above). Product-code
   changes are one new shared contract module, one module export, UUID serde
   support/lockfile dependency, and the two-line DCL runner configuration fix.
   Other additions are fixtures, tests, ADR, classification and completion evidence.
   No Builder, native adapter, networking execution, runtime authority, CGS or SGC
   implementation was edited. Existing uncommitted work is preserved. The evidence
   manifest includes raw scoped tracked diff statistics; those include earlier
   MASTER_PLAN/source-inventory changes and must not be attributed wholly to XP-001.
   No commit was created.

9. **Acceptance.** Fully satisfied for XP-001: deterministic typed identities and
   serialization, exact golden outcomes, rejection of missing/unknown requirements,
   reusable three-host vectors, supported-profile/proof/topology documentation,
   official DCL discovery repaired, scoped source-bound baseline, relevant regression
   suites green, and no new authority bypass. This is contract acceptance, not
   public Player/session/World Contract runtime certification or whole-repo release.

10. **Recommendation: READY FOR XP-002.** Its required contract baseline is now
    executable, documented and verified. XP-002 has not started. Work stops here.
