# XP-006 complete: Generic capability/dependency-aware gameplay authoring

Completed 2026-09-28 for the registered-host authoring profile. XP-007 has not
started. [Architecture and reproduction](adr/XP-006-gameplay-authoring.md).

## Delivered

- A data-only gameplay authoring catalog with pinned content identity, arbitrary
  namespaced capabilities, declared component/system requirements, deterministic
  templates and typed configuration presets. Host-supported system contracts are
  registered separately; package or provider data cannot enroll executable code.
- PIL requirement discovery and Builder choices for marking compatible objects or
  creating the selected catalog template. Existing objects are preserved on the
  marking path; templates refuse to overwrite a populated mode.
- `install_gameplay_package` in the closed typed operation grammar. GDE resolves it
  on the atomic batch copy. Later operation failures, unsupported dependencies,
  stale identities and invalid selections cannot leak partial package changes.
- Real Factory/SGC validation before a materialized CGS preview; normal explicit
  approval, GDE commit, compile, persistence and rollback paths on apply.
- Existing Builder clarification cards and review state support multi-step catalog
  selection. No mechanic-specific UI state, compiler or runtime branch was added.

## Reference evidence

`examples/reference-mechanic/authoring.json` owns the "Add wall running" alias,
capability, arena and presets. `tools/xp006_authoring_proof.py` uses the actual
Builder router for prompt, clarification, missing/wrong approval rejection and
successful approved persistence. It compiles both disabled-third-attempt and
reversal/shockwave configurations into real CGS, SGC plan and World Contract files.

The removable Rust host reads those newly authored artifacts via its test-only
fixture-root override. Nine tests pass, including full event/hash replay for ten
ticks in each configuration, actual impulse behavior, contact rules and rollback.
No additional mechanic was introduced. Renaming the semantic capability to an
arbitrary valid project namespace also compiles through the identical authoring
path. The original XP-005 fixture contents were preserved.

## Verification

| Check | Result |
| --- | --- |
| Schema Factory Python suite | 127 passed |
| GDE Python suite | 200 passed |
| PIL Python suite | 448 passed |
| Builder server Python suite | 353 passed, including 10 XP-006 tests |
| Total affected Python gate | 1,128 passed; zero failures/errors/not-run |
| Reference Rust host on XP-006 artifacts | 9 passed; zero failed/ignored |
| Builder TypeScript typecheck | Passed |
| Existing Builder UI contract test | Passed |
| Catalog clarification-to-preview/apply behavior test | Passed |
| Source inventory comparison | Same 31 pre-existing omissions; zero added |

The first regression run found the closed operation-list expectation needed the
new operation; the final run passes. Counts from focused reruns overlap the gate
and are not additional tests. This was a scoped verification, not a new whole
workspace/native/network/performance certification.

Machine-readable source and artifact evidence: [xp006-baseline.json](evidence/xp006-baseline.json).
Logs remain in `tmp/xp006-python-final.json`, `tmp/xp006-runtime.log`,
`tmp/xp006-targeted-final.log` and `tmp/xp006-proof.json`.

## Limits retained

The authoring host must explicitly register a supported catalog. The general
runtime CLI does not automatically gain the reference fixture or its recorded
input system. Native playable-package admission/distribution remains XP-007.
No paid/provider demonstration, live tick activation or native engine run was
performed. Existing UI provider-readiness policy is unchanged; offline proof uses
the Builder server and typed host flow. Configuration v1 selects declared presets.
Existing `add_asset` typed operations provide placeholders; native paths do not
control capability satisfaction. Unrelated dirty-tree changes were preserved.
