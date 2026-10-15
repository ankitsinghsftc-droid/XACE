# NEC-001 recovery reconciliation

The current implementation is the independent recovery checkout, based on the XP015 source and faithfully replayed XP016-022 changes, plus explicitly recorded journal and proof-harness repairs. The protected engineering baseline is `C:/Users/ankit/XACE-Recovery/baselines/xp022-recovered-20261015/baseline.json`, SHA-256 `44b38aea2503731b455377221385821228916b5ea843b094e9cd01d4847a90fc`, source checkpoint `13a3d9b6ddb68d155b51045d6ad7dcc297ed1df9`. It is fresh evidence, not the missing historical seal payloads.

## Present source boundary

The recovered historical audit and ownership ADR remain applicable to this code. `project_creator.py::import_engine_project` links/inventories native projects; `engine_migration_wizard.py` produces starter preview mappings; Builder's migration route returns `preview_only`. `project_manifest.py` still declares `bidirectional_editing: False`. These do not implement faithful native scene adoption or automatic native edit capture.

`runtime_orchestrator/ruleset_candidate.rs` explicitly rejects unregistered configuration mappings, world/capability migration and entity migration without proven hooks. `ruleset_activation.rs` durably decides before publication, while `runtime_cli.rs` refuses the parent after a recovered durable decision. This does not provide cross-editor save recovery. `epoch_replay.rs` and the exact-host archive verifier provide bounded deterministic history, not authoring undo or native gameplay source generation.

The verified Windows Player distribution bundles the XACE runtime. NEC's Builder/cloud-independent continuation promise does not mean runtime-free Unity/Unreal/Godot gameplay export. That requires a separate compiler/parity program.

## Roadmap disposition

Retain the recovered 18 task IDs and their order. Preserve the original NEC001 amendments:

1. Pin actual engine profiles; runtime reader proofs do not certify native editor capture or shipping integration.
2. NEC007/009-012 distinguish explicit stopped-session rebuild from eligible XP018/019 live configuration activation.
3. NEC008/009 add three-way review, authoring conflict/recovery UI and a separate durable authoring journal.
4. NEC016/018 preserve replay completion/quota metadata and prove dependency-closed restore/rebuild, save policy, licensing and continuing-use boundaries.
5. REL01-05 remain open with original claim-specific conditions.

Recovery amendments: every future worktree, source checkpoint, unique evidence artifact and seal uses persistent paths. Historical `target/...` paths are provenance only and must not be reused as output defaults. Commit each restored milestone, identify incomplete work, preserve all prior receipts, and keep off-device backup status explicit. Original task-specific pauses are historical; the owner's current sequential restoration authorization covers NEC001-009. NEC010 remains prohibited until recovered implementation/NEC009 and final recovery acceptance are verified.

## Verification accounting

Nine Python suites were freshly rerun (85 tests). All 23 Rust reference/candidate/activation tests also pass. Before/after protection checks pass for all54 sealed files and1575 archived source entries. NEC001 recovery acceptance is complete; exact results are in evidence/nec001-20261015/summary.json. The exact pinned host's recently completed socket, process-fault, mixed-host, replay, native-reader, browser, packaging and full-soak proofs are retained and hash-bound; they are not described as newly executed NEC001 tests. No runtime source is modified by NEC001.

Before/after seal verification hashes every sealed file, checks source ZIP entries and release inventory, and permits live changes only to MASTER_PLAN.md and AGENT_PROGRESS.md among pre-existing baseline files. New NEC documents/tools have independent identities. No original repository, preserved Codex log or seal is modified. No external release certification is claimed. All checkpoints remain **NOT backed up off-device**.
