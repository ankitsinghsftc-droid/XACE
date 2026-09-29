# XP-007 completion ? 2026-09-29

XP-007 is complete for the Windows native headless package profile. The preceding
world extensibility correction is complete; see [its report](WORLD_EXTENSIBILITY_COMPLETION.md).
Project-defined nouns remain versioned semantic data rather than core enum entries.

## Changed APIs and files

- `packages/project-system/playable_package.py`: deterministic construction,
  authoritative verification, runtime support admission, presentation indexing,
  bounded archive import, staged activation and verified native launch arguments.
- `packages/project-system/sgc_identity.py`: persisted Rust SGC identity verification.
- `packages/runtime-core/src/world_loader.rs` and `src/lib.rs`: compiled world loader/export.
- `packages/runtime-core/src/runtime_orchestrator.rs`: startup binding, retained
  semantic metadata on restore, and rejection of unstaged compiled-world reload.
- `packages/runtime-core/src/bin/xace_runtime.rs`: paired world/manifest CLI paths.
- `packages/project-system/tests/test_playable_package.py`: 11 package regressions.
- `packages/runtime-core/tests/fixtures/playable_package_v1/`: four Factory/SGC artifacts
  used by two additional runtime integration tests.
- `tools/xp007_package_proof.py`: actual native build/package/relocation execution proof.

## Verification

- Project-system gate: **22 passed**, zero failures/errors.
- Runtime library: **703 passed**, zero failures/ignored.
- World/session/geometry/reference targeted Rust suites: **48 passed**, zero failures/ignored.
- Native runtime build passed offline. Identical package construction, followed by
  original and relocated execution, produced the same four authoritative tick hashes.
  All four hashes differ across time, proving actual state progression.
- Package regressions cover missing/tampered artifacts, forged SGC proofs, unsupported
  host contracts/profiles, unsafe archive paths/links/limits, asset location rejection,
  presentation identity separation and interrupted installation/activation.
- Source inventory retains the same **31 pre-existing findings**, with no additions.

The relocation fixture retains the requested space/strategy/horror semantic nouns
and compound bindings, using existing MovementSystem for state progression. It does
not add corresponding game implementations. Legacy reference-mechanic package data
passes the same generic verifier with explicitly registered host support.

See [the contract](adr/XP-007-playable-package.md) and
[source-bound evidence](evidence/xp007-baseline.json). Logs are under
`tmp/xp007-verification/`, `tmp/xp007-project-system-final.json` and `tmp/xp007-proof/`.

## Remaining boundary

No graphical Player, clean-machine install, additional geometry backend or multiplayer
certification is claimed. The stock host does not automatically register the reference
mechanic. XP-008 must compose a supported host through normal system registration.
Direct compiled-world hot reload remains blocked pending XP-018 staged activation.
The roadmap keeps later mechanisms generic and reference mechanics replaceable.

**READY FOR XP-008.**
