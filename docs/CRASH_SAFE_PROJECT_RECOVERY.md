# Crash-Safe Project Recovery

Task X10-016 makes recovery part of the product runtime path, not a manual repair step.

## Recovery Scope

- `game.cgs.json`: `CGSPersistence.load()` calls `recover()` before reading. Recovery deletes stale `.xace_tmp_*.json` files, rebuilds `.xace/snapshot_index.json` from valid snapshots, and restores the latest valid snapshot when the active CGS is missing or invalid.
- SGC ExecutionPlan files: `.xace/execution_plans/<cgs_hash>.plan.json` is validated with the persisted execution-plan contract. If the plan was interrupted, recovery repairs it from the matching `.xace/proof/sgc/<cgs_hash>/plan.json` bundle when that bundle is valid.
- SGC proof bundles: incomplete or invalid `.xace/proof/sgc/<cgs_hash>` bundles are removed during recovery, so later Builder/runtime paths cannot treat partial compiler output as authoritative.
- Structural CGS consistency: if the active CGS declares executable systems but has no valid persisted ExecutionPlan, recovery restores the newest snapshot that also has a valid persisted plan.
- Project manifest and project-template files: project creation and manifest writes use temp-file, fsync, and replace writes with a `.xace_bak_<file>` copy of the last valid state. `load_manifest()` runs recovery before parsing.
- Save slots: `FileSaveEngine` maintains `.xace_bak_<file>` copies for session, metadata, progress, and world files, removes stale save temp files, repairs invalid or missing files from the last valid copy, and repairs session/metadata mismatch to the last complete slot state.
- Builder restarts: `create_app()` runs `CGSPersistence.recover()` during server startup and includes the structured recovery report in the WebSocket `session_init` payload.

## Recovery Reports

`CGSRecoveryReport` includes:

- `temp_files_removed`
- `snapshot_index_rebuilt`
- `execution_plans_repaired`
- `execution_plans_removed`
- `proof_bundles_removed`
- `restored_cgs_hash`
- `errors`

`SaveRecoveryReport` includes:

- `temp_files_removed`
- `files_restored`
- `slots_checked`
- `errors`

## Corruption-Injection Evidence

- `packages/project-system/tests/test_project_system.py::test_x10_016_manifest_recovery_restores_last_valid_backup`
- `packages/builder-workspace/server/tests/test_cgs_persistence_authority.py::test_crash_recovery_rebuilds_index_and_restores_latest_valid_snapshot`
- `packages/builder-workspace/server/tests/test_cgs_persistence_authority.py::test_x10_016_recover_repairs_interrupted_plan_write_from_proof_bundle`
- `packages/builder-workspace/server/tests/test_cgs_persistence_authority.py::test_x10_016_recover_restores_latest_snapshot_with_valid_plan`
- `packages/builder-workspace/server/tests/test_cgs_persistence_authority.py::test_x10_016_corrupt_main_ignores_planless_structural_snapshot`
- `packages/save-engine/tests/test_save_roundtrip.rs::x10_016_save_recovery_restores_corrupt_session_and_metadata_pair`
- `packages/save-engine/tests/test_save_roundtrip.rs::x10_016_save_recovery_restores_last_complete_slot_after_metadata_gap`

## Certification Commands

- `python -m unittest packages/project-system/tests/test_project_system.py packages/builder-workspace/server/tests/test_cgs_persistence_authority.py`
- `cargo test -p xace-save-engine x10_016 --target-dir target-codex-crash-recovery`
- `python tools/certify_launch.py --quick --target-dir <target-dir>`
