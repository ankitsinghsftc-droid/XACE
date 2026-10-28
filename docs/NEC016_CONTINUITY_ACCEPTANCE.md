> Current: NEC016 local engineering complete 2026-10-28; exact private-profile notice inventory/archive gap closed. User explicitly deferred clean-machine certification. Public redistribution/continuing-use approval remains an NEC018 release gate, not a prerequisite to internal NEC017 certification. Earlier unavailable-notices assertions were overbroad and are superseded by docs/evidence/nec016-notices-closeout-20261028/summary.json. No historical evidence rewritten or public shipping certification claimed. NEC017 now authorized and starting; NEC018 not started.

# NEC-016 offline distribution, continuity archive and detach

Started 2026-10-28 at8bb9e3c on recovery/xp022, explicitly authorized. NEC013/015 local profiles are verified but their mandatory clean-machine gates remain open. No earlier acceptance is waived; NEC017 is not authorized.

## Reconciliation against actual code

- playable_package.py verifies bounded runtime packages and content-addressed activation; its512MiB/4096-file in-memory profile is not a whole-project/source/history archive.
- adapter_installation.py retains before-images and surfaces modified-file conflicts; reuse it for detach rather than inventing a second destructive uninstaller.
- authoring_identity_store.py and NEC009 authoring_transaction*.py preserve identity maps, journals and recovery references. Restored history must retain these identities and bind explicit relocation; journals are data, never executable recovery instructions.
- NEC012 native_storage.rs and native host admission enforce save identity and readiness-gated activation. Native update/save proofs from NEC013-015 remain reusable, but do not prove source closure, automatic migration or independent rebuild.
- NEC015 checked native packaging needs approved native source and pinned bundled executors; its receipts alone do not preserve creator-side executor source/build inputs or dependency licensing notices.

## Required scope and acceptance

1. Versioned streaming continuity archive: explicit source roots/roles, declared dependency closure, executor source/build inputs, native project/assets, identity/history journals, protected checkpoint references, runtime identities and redistributable notices. Every omission/unavailable item is reported. Missing essential material blocks a completeness claim. No automatic source deletion or history cleanup.
2. Archive integrity, hostile path/link/case-collision/duplicate/size refusal, deliberate secret omission/redaction reporting, create-only restore into an independent persistent workspace, retained failed staging. No archive import executes code or assumes its claims are trusted.
3. Actual restored project/history validation and rebuild with documented installed prerequisites. Toolchains/unlicensed third-party materials remain explicit external requirements, never silently bundled. Original projects/evidence/seals remain untouched.
4. Explicit safe detach modes reuse existing adapter ownership/backups and approvals. Modified adapters/native files must be preserved with both versions and a reviewable conflict. Failure must retain the archive and prior native state. Runtime-free native gameplay export is a non-goal.
5. Define clone/fork/branch/merge/rebase/recovery behavior using existing identities, reconciliation and journals. Preserve conflicting versions and require review; full two-developer certification remains assigned to NEC017 without weakening this contract.
6. Actual packaged launch without Builder and with network denied; failed/interrupted update retention, prior-release rollback and save migration/refusal preserving original saves. Existing external clean-machine/signing/tester/network/Steam release gates remain open until evidenced.

## Verification and preservation

Focused adversarial archive/restore and detach tests, real independent workspace restore/rebuild, native package isolation/network-denial proof and existing regression suites. Pin source, archive and restored-file identities. Use persistent paths outside disposable build directories. Failures and partial checkpoints are retained and labeled. Stop before NEC017.

Status: typed closure inventory and streaming archive/verification/create-only restore core implemented;19 distinct focused tests pass. Actual native closure/rebuild, detach/collaboration integration and offline/update/save proofs remain pending. No NEC016 acceptance claim yet. Evidence: docs/evidence/nec016-archive-20261028.

Current checkpoint: archive/restore/detach CLI and preservation verified;318 full project-system and27 focused tests pass. Independent restored executor exact rebuild and real Godot rebuild/gameplay pass; failed/interrupted update, explicit rollback and save refusal pass. See evidence/nec016-continuity-20261028/summary.json and NEC016_CONTINUITY_WORKFLOW.md. Task NOT complete: firewall elevation canceled (retry pending), complete public redistribution notices unavailable; archive truthfully incomplete. External clean-machine gates remain open.

NEC016 firewall update 2026-10-28: UAC granted for first run; actual native TCP connection denial observed, but process-exit harness check stopped before gameplay. Rules removed and zero remaining rules independently verified. Corrected harness records direct process exit codes and supports fresh attempt names; syntax passes. Retry UAC canceled, so correction/elevated gameplay are not yet verified. Evidence: docs/evidence/nec016-firewall-attempt-20261028/summary.json. No completion claim; another prompt awaits user readiness.

NEC016 network gate verified 2026-10-28: fresh Godot native fixture passed actual executable-scoped Windows Firewall denial, external positive/unblocked controls, local authoritative gameplay, audio/animation, compatible save admission and unchanged incompatible-save refusal. Installation hashes unchanged, owned processes gone, zero temporary firewall rules independently verified. Synthetic save probe explicitly flushes/closes before hash capture and records detailed diagnostics; prior failed runs retained. Evidence: docs/evidence/nec016-firewall-verified-20261028/summary.json. Network-denial gate is now closed for this local profile. NEC016 overall remains incomplete for complete redistribution notices/licensing closure and inherited clean-machine gates. No claim of Builder uninstall from this laptop, automatic migration, clean-machine certification or NEC017 completion.
