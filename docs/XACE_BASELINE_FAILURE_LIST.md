# XACE Baseline Failure List

Task: 5 from `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md`
Date: 2026-06-18
Workspace: `C:\Users\ankit\Downloads\xace`

## Clean Checkout Caveat

This baseline was not captured from a clean checkout. `git status --short` reported many modified, deleted, and untracked files before the Task 5 runs, including prior governance artifacts, adapter/runtime changes, generated `target-codex-*` outputs, and older local workspace noise. I used isolated Task 5 output directories where possible, but this is a current-worktree baseline, not a release-quality clean-checkout baseline.

Missing artifact: a clean-checkout baseline proof from a tagged or freshly cloned source tree.

## Command Baseline

| Area | Command | Result | Baseline finding |
| --- | --- | --- | --- |
| Rust workspace | `cargo test --workspace --target-dir target-codex-baseline-rust` | FAIL | Workspace stops at `xace-engine-adapter`; rerun below captures exact adapter failures. |
| Rust adapter | `cargo test -p xace-engine-adapter --lib --target-dir target-codex-baseline-adapter` | FAIL | 217 passed, 2 failed. Delta compression does not eliminate unchanged data as expected. |
| Rust runtime | `cargo test -p xace-runtime-core --target-dir target-codex-baseline-runtime` | FAIL | Unit/integration tests ran, then doctests failed in runtime component-table/state-printer docs. |
| Rust network | `cargo test -p xace-network-core --target-dir target-codex-baseline-network` | FAIL | 31 tests passed across earlier binaries, then `resync_engine_retries_and_acknowledges_sessions` failed. |
| Rust SGC | `cargo test -p xace-system-graph-compiler --target-dir target-codex-baseline-sgc` | PASS | 249 library tests and 2 binary tests passed; 1 doctest was ignored. |
| Python project system | `python -m unittest discover packages/project-system/tests` | PASS | 6 tests passed. |
| Python asset registry | `python -m unittest discover packages/asset-registry/tests` | PASS | 200 tests passed; one warning for an intentionally unknown asset link attempt. |
| Python Builder server | `python -m unittest discover packages/builder-workspace/server/tests` | PASS | 30 tests passed. |
| Python save engine | `python -m unittest discover packages/save-engine/tests` | PASS | 12 tests passed. |
| Python schema factory | `python -m unittest discover packages/schema-factory/src/tests` | FAIL | 3 test modules failed import because `pytest` is not installed. |
| Python GDE | `python -m unittest discover packages/gde/src/tests` | FAIL | 5 test modules failed import because `pytest` is not installed. |
| Python inference | `python -m unittest discover packages/inference/tests` | FAIL | 8 test modules failed import because `pytest` is not installed. |
| Python prompt intelligence | `python -m unittest discover packages/prompt-intelligence/src/tests` | FAIL | 6 test modules failed import because the test discovery path does not expose modules like `context_assembler`, `intent_intake_layer`, and `pil_pipeline`. |
| Python pytest runner | `python -m pytest packages/schema-factory/src/tests packages/gde/src/tests packages/inference/tests` | FAIL | Python environment has no `pytest` module. |
| TypeScript/Builder | `npm run build` | PASS | Root script typechecked Builder and produced a Vite production build. |
| Full editor-free certification | `python tools/certify_launch.py --target-dir target-codex-baseline-cert` | PASS WITH SKIP | 24 editor-free checks passed; installed Godot/Unity/Unreal validation was skipped because `--installed-engines` was not passed. |
| Commercial scope docs | `python tools/commercial_scope_check.py` | PASS | Commercial scope check passed. |
| Source inventory docs | `python tools/source_inventory_check.py` | PASS | Source inventory check passed before this report was added. |
| Fake/skip register docs | `python tools/fake_skip_register_check.py` | PASS | First parallel run timed out at 123.5s; rerun alone passed in 29.2s. |
| Production path docs | `python tools/production_path_check.py` | PASS | Production path rules check passed. |
| Forbidden claims docs | `python tools/forbidden_claims_check.py` | PASS | Forbidden claims check passed. |

## Failing Commands

### Rust Adapter Delta Compression

Command:

```powershell
cargo test -p xace-engine-adapter --lib --target-dir target-codex-baseline-adapter
```

Failures:

- `delta_sync::delta_compressor::tests::compression_ratio_high_when_mostly_unchanged`
  - File: `packages/engine-adapter/src/delta_sync/delta_compressor.rs:560`
  - Assertion: `c.metrics().compression_ratio() > 0.5`
- `tests::test_delta_sync_integration::performance::compressor_eliminates_unchanged_fields_at_100_entities`
  - File: `packages/engine-adapter/src/tests/test_delta_sync_integration.rs:589`
  - Assertion: expected only 1 changed entity after compression, got 100.

Task mapping: Task 6.

### Rust Network Resync

Command:

```powershell
cargo test -p xace-network-core --target-dir target-codex-baseline-network
```

Failure:

- `resync_engine_retries_and_acknowledges_sessions`
  - File: `packages/network-core/tests/test_desync_detection.rs:108`
  - Error: `resync ack hash good did not match expected aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`

Task mapping: Task 7.

### Rust Runtime Doctests

Command:

```powershell
cargo test -p xace-runtime-core --target-dir target-codex-baseline-runtime
```

Doctest failures:

- `packages/runtime-core/src/component_tables/archetype.rs:7`
- `packages/runtime-core/src/component_tables/archetype_storage.rs:7`
- `packages/runtime-core/src/component_tables/storage_router.rs:10`
- `packages/runtime-core/src/state_printer.rs:8`

Observed causes include prose/diagram snippets being treated as Rust code, box-drawing characters inside doctests, and doctest examples missing imports or fixture variables.

Task mapping: Task 9.

### Python Test Environment And Import Harness

Commands:

```powershell
python -m unittest discover packages/schema-factory/src/tests
python -m unittest discover packages/gde/src/tests
python -m unittest discover packages/inference/tests
python -m unittest discover packages/prompt-intelligence/src/tests
python -m pytest packages/schema-factory/src/tests packages/gde/src/tests packages/inference/tests
```

Failures:

- `packages/schema-factory/src/tests`: `pytest` missing.
- `packages/gde/src/tests`: `pytest` missing.
- `packages/inference/tests`: `pytest` missing.
- `packages/prompt-intelligence/src/tests`: import path/harness missing for modules including `context_assembler`, `intent_intake_layer`, `llm_orchestrator`, `memory_store`, `pil_pipeline`, and `scope_boundary_guard`.
- Direct pytest command: `No module named pytest`.

Task mapping: Task 10.

## Skipped Gates

| Gate | Status | Evidence | Consequence |
| --- | --- | --- | --- |
| Installed Godot validation | SKIPPED | `tools/certify_launch.py` printed `installed-engine validation skipped; pass --installed-engines to run real Godot/Unity/Unreal checks.` | No current Task 5 proof that Godot adapter works in an installed editor. |
| Installed Unity validation | SKIPPED | Same certification output. | No current Task 5 proof that Unity adapter works in an installed editor. |
| Installed Unreal validation | SKIPPED | Same certification output. | No current Task 5 proof that Unreal adapter works in an installed editor. |
| Clean-checkout verification | SKIPPED / NOT SATISFIED | `git status --short` was dirty before running gates. | Baseline cannot be treated as clean release evidence. |
| SGC doctest body | IGNORED | `cargo test -p xace-system-graph-compiler` reported 1 ignored doctest. | SGC crate passes its active tests, but one documentation example is not executable proof. |
| Builder UI test suite | NOT FOUND | `packages/builder-workspace/package.json` exposes `build` and `typecheck`, but no `test` script. | Builder has build/typecheck proof, not a declared UI test gate. |

## Missing Artifacts

- Clean-checkout proof from a fresh clone or clean working tree.
- Machine-readable Task 5 command report with exit codes, timings, tool versions, and captured logs.
- JUnit or JSON artifacts for Python tests.
- A single canonical command that runs all production Python package tests.
- Declared Builder UI test command and UI test artifact.
- Installed-engine summary JSON for Godot, Unity, and Unreal from a Task 5 run.
- Installed-engine proof artifacts showing real adapter validation in Godot, Unity, and Unreal.
- CI artifact retention for the full baseline command matrix.
- Cross-platform baseline evidence; all Task 5 commands here were run on this Windows workspace only.
- A passing `cargo test --workspace` artifact from a clean target directory.

## Task 12 Resolution Note

Task 12 does not change the historical Task 5 baseline above. It does close the certification artifact gap for current runs: `tools/certify_launch.py` now writes `launch_certification_report.json` for pass and fail outcomes, records quick-mode skipped checks under `editor_free.skipped_checks`, and writes `installed-engine-validation/installed_engine_summary.json` with Godot, Unity, and Unreal marked as unsupported when installed-engine validation is not requested.

## Current Truth

The editor-free certification path is strong enough to run and pass 24 checks, including runtime binary build, protocol tests, SGC smoke, Builder build, governance checks, prompt/provider/onboarding smokes, runtime bridge, feedback replay, networked runtime smoke, and save replay/migration. That does not mean the whole repository is clean: full workspace Rust tests fail, important adapter and network assertions fail, runtime doctests fail, several Python suites are not runnable in the current environment, and installed engine validation remains unproven in this baseline.

Next task should be Task 6 only: fix `xace-engine-adapter` delta compression until `cargo test -p xace-engine-adapter --lib` passes cleanly.
