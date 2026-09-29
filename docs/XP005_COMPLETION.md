# XP-005 completion - 2026-09-25

XP-005 is complete as a **Reference Mechanic Proof**, not a privileged core mechanic.

The prerequisite capability correction uses World Contract v2 package declarations
and data-driven role constraints in Python/Rust. Platform admission requirements
remain separate from semantic names. Artifact-bound admission checks actual world
content. Historical v1 fixtures are preserved and require explicit recompilation;
there is no silent world migration.

The removable [reference package](../examples/reference-mechanic/README.md) uses
normal GCL config/state, ISystem registration, declared reads/writes, a real persisted
SGC plan, generic geometry/capability queries and MutationGate. It implements two
chained wall-jumps, canonical landing reset and the optional third-attempt reversal
+ shockwave. The wave changes another actor's velocity; it is not just a visual event.
No mechanic-specific branch was added to runtime orchestration, world validation,
networking or engine adapters.

Verification:

- Broad selected Rust regression run: **1,934 passed**, zero failed/ignored,
  37 result groups, including the initial seven reference tests.
- Final reference run: **9/9 passed**, including stable corners, arbitrary capability
  renaming and full event/hash replay for both policies across ten recorded ticks.
- Final contract run: **14/14 passed** (8 session, 6 world), including artifact-bound
  rejection of undeclared semantic requirements. These counts overlap the broad run.
- Official Python gate: **1,135 passed**: Schema Factory 127, GDE 200, project system 11,
  asset registry 207, DCL 14, inference 233, Builder 343. No failures/errors/not-run.
- Both real Factory/SGC reference compilation of both policy variants and the migrated six-object world
  compilation proof reproduce committed golden bytes. Invalid source/geometry,
  malformed declarations and failed tick transactions reject without partial changes.
- Source inventory retains its 31 pre-existing omissions; no new task source is
  unclassified. All 41 task files/hashes and replay results are in the evidence manifest.

Commands: `cargo test -p xace-core -p xace-runtime-core -p xace-network-core
-p xace-engine-adapter -p xace-system-graph-compiler -p xace-reference-mechanic
--offline --quiet`; final `cargo test -p xace-reference-mechanic --offline --quiet
-- --nocapture`; final `cargo test -p xace-core --test test_session_contract
--test test_world_contract --offline --quiet`; `python tools/xp005_reference_proof.py`;
`python tools/xp003_world_proof.py --output tmp/xp005-world-proof`.
The Python gate used schema-factory, gde, project-system, asset-registry, dcl,
inference and builder-server suites with `--output tmp/xp005-python.json`.

Limits: Windows x64/offline proof only. The harness explicitly registers this
package; the default runtime CLI does not auto-discover it. No additional mechanic,
provider, native-engine, multiplayer, live activation or 60-Hz performance claim.
The two policies are proved as separately initialized rulesets; activation at tick N
remains XP-018/019. Earlier Agent/BYOK and XP work is preserved; source-bound older
reports are historical rather than being relabeled with the new contract results.

[Design and compatibility details](adr/XP-005-reference-mechanic.md).
[Source-bound evidence](evidence/xp005-baseline.json).

**READY FOR XP-006. XP-006 has not started.**
