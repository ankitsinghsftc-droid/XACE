# XACE Fake And Skip Register

Inventory date: 2026-06-14

This register satisfies Task 3 of `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md`.
It names known mocks, fakes, stubs, skipped checks, placeholders, fallbacks,
stale-doc risks, and smoke-only proofs. The machine-readable source is
`docs/fake_skip_register.json`; `tools/fake_skip_register_check.py` validates
that suspicious keyword-bearing files are covered by a register entry.

Equivalent repeated occurrences are grouped by path pattern. A grouped entry is
not a fix. It is a signed assignment: remove it, replace it, isolate it, or keep
it documented as test-only.

## Dispositions

- `remove`: delete the item or archived path.
- `replace`: replace with real production behavior, a hard failure, or proof-backed implementation.
- `isolate`: keep only behind test/archive boundaries and prove production cannot import it.
- `document-test-only`: keep as a smoke, fixture, placeholder, or demo-only proof with public wording that cannot be mistaken for production behavior.

## Register

| ID | Item | Evidence | Disposition | Owner task(s) |
| --- | --- | --- | --- | --- |
| FSR-001 | Fake SGC wiring in Builder server tests | `packages/builder-workspace/server/tests/test_prompt_pipeline_e2e.py::_fake_sgc_wiring_test_only_script` | replace | 18, 19, 33, 34 |
| FSR-002 | Removed Builder prompt fallback and `_MockAdapter` path | `SessionManager.run_pil()` now blocks with `PIL_UNAVAILABLE`; production path rules have no `_MockAdapter`/`SimplePipeline` allowlist | replace | 17, 19, 35, 36, 51, 54 |
| FSR-003 | Optional/skipped SGC execution paths | `SessionManager._compile_sgc`, structural Builder SGC rejection, `builder_server.py --sgc-bin` blocking | replace | 17, 18, 21-25, 30, 33 |
| FSR-004 | Certification quick/skipped installed-engine gates | `launch_certification_report.json` records quick skipped checks, pass/fail checks, and unsupported installed-engine entries | replace | 5, 97-99, 122 |
| FSR-005 | Smoke-only and proof-only tools | `tools/*_smoke.py`, `tools/*_proof.py`, integration helpers | document-test-only | 5, 12, 15, 16, 141-143 |
| FSR-006 | Test-only mocks, fakes, fixtures, deliberate failures | `packages/**/tests/**`, `packages/**/src/tests/**`, `tests/**` | isolate | 4, 19 |
| FSR-007 | Archived stub design docs | `docs/00_*` through `docs/10_*` stub files except completed docs | replace | 13, 14 |
| FSR-008 | Historical/stale planning material | `CLAUDE.md`, `MASTER_PLAN.md`, `XACE_FILE_MANIFEST(LATEST).md`, launch map history | isolate | 13, 14, 144 |
| FSR-009 | Uncovered production stubs and not-implemented CLI/BYOK/DCL paths | `packages/inference/src/byok_manager.py`, `packages/cli/src/**`, `packages/dcl/**` | replace | 8, 13, 17, 51, 54, 130, 133 |
| FSR-010 | Partial validation and silent-skip logic | `invariant_enforcer.py`, `validation_loop.py`, prompt output/code-generation validators | replace | 4, 17, 20, 35, 36, 39, 44 |
| FSR-011 | Asset placeholders and grey-box sample assets | asset registry/core placeholder states, `tools/asset_playback_smoke.py`, quickstart placeholder visuals | document-test-only | 82-86, 101 |
| FSR-012 | Engine adapter fallback visuals and tolerant parsing | Unity `fallbackPrefab`, Unreal `FallbackActorClass`, adapter fallback reads | replace | 63, 82, 84, 85, 93, 97-99 |
| FSR-013 | Build script skips generated C header | `packages/engine-adapter/build.rs` cbindgen warning/skip | replace | 4, 12, 95, 123, 125 |
| FSR-014 | Inference model/provider fallback chains | `packages/inference/src/fallback_policy.py`, `model_router.py`, provider settings | replace | 51-57 |
| FSR-015 | Fake provider keys and unsafe credential fallback in tests/smokes | `tools/provider_readiness_smoke.py`, `tools/prompt_pipeline_smoke.py`, server credential tests | isolate | 4, 19, 54, 55, 126 |
| FSR-016 | Archived legacy workspace server path | `packages/workspace/**`, `workspace/**` | isolate | 8, 13, 14 |
| FSR-017 | Builder demo endpoints and editor-free demo smokes | Builder `/demo/*/smoke` endpoints and UI smoke buttons | document-test-only | 69, 71, 88, 91, 141-143 |
| FSR-018 | Operational fallback/skip terminology that is real behavior | runtime/core/network/save/feedback paths where skip/fallback is intentional behavior | document-test-only | 13, 60, 68, 71, 144 |
| FSR-019 | Production-path rule enforcement artifacts | Task 4 rules, config, checker, and CI workflow intentionally contain fake/skip terminology | document-test-only | 4, 17-20, 144 |
| FSR-020 | Task 5 baseline failure and skipped-gate report | `docs/XACE_BASELINE_FAILURE_LIST.md` records failing commands, skipped installed-engine validation, and missing artifacts | document-test-only | 5-7, 9-12, 97-99, 122 |
| FSR-021 | Python test gate accounting terms | `tools/python_test_gate.py` records unittest not-run/skipped accounting and runs the fake/skip register checker as part of the gate | document-test-only | 10, 12, 121 |
| FSR-022 | No-silent-success and real-SGC guard accounting terms | `tools/silent_success_check.py` records blocked/unsupported/skipped response accounting and fails on silent success, prompt-proof, or fallback-removal regressions | document-test-only | 17, 18, 19, 12, 144 |
| FSR-023 | X10 completion backlog risk terminology | `XACE_10_OUT_OF_10_COMPLETION_TASKLIST.md` names fake/mock/skip/smoke/placeholder/fallback terms as risks, removal targets, or proof requirements | document-test-only | X10 |

## Non-Negotiable Follow-Up

- Fake SGC must not be presented as compiler proof.
- `_MockAdapter` and fake provider keys must not satisfy production provider readiness.
- Quick/editor-free certification must not imply installed-engine validation.
- Smoke tools prove only their named scenario.
- Archived docs and stub docs are not product truth.
- Placeholder assets are unresolved or grey-box stand-ins, not finished assets.
