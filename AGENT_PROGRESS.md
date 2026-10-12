# XACE recovery progress

Recovery started 2026-10-12. This file overrides historical completion claims in reconstructed documents.

- Baseline: XP-015 commit `39ed07b8cd390619a479a3364dc903ee077a6d38`; tree `f39aef3faf59ccc3d43f3ded7af8418d1bb7e350`.
- Workspace: `C:/Users/ankit/XACE-Recovery/worktrees/xace`.
- Independent Git database: `C:/Users/ankit/XACE-Recovery/repositories/xace.git`; no borrowed objects or hard links from originals.
- Preserved inputs: `C:/Users/ankit/XACE-Recovery/preserved/20261012/manifest.json` (SHA-256 checked local copies; NOT an off-device backup).
- Original repositories, objects, and transcripts are read-only recovery inputs. Never clean, reset, prune, restore, or build there.
- Unique source, checkpoints and evidence must stay outside disposable directories. No automatic deletion. Never execute transcript shell commands wholesale.

## Current state

| Milestone | Recovery | Fresh verification |
|---|---|---|
| Protected workspace / XP-015 baseline | Created; independent objects | Baseline commit/tree checked |
| XP-016 | Reconstructed through original continuation line7936; original evidence JSON missing | Fresh native, live, unit and selected Player gates pass; scope limits below |
| XP-017 through XP-022 | Pending | Not run |
| NEC-001 through NEC-008 | Pending | Not run |
| NEC-009 | Pending; historical final edits unverified | Not run |
| NEC-010 | Not started; blocked until recovered implementation and NEC-009 verified | Not run |

## Evidence boundaries

Original XP-022 sealed artifacts remain missing. Reconstructed historical docs are not fresh verification and must never be presented as an original seal.
Historical NEC-009 passed 337 tests before later edits; 338 passing tests and final closeout are unverified.
XP-016 initially had a Unity license blocker; original continuation at transcript lines7926?7939 fixed the proof setup and passed Unity. This continuation is now recovered. Missing-cosmetic startup regression remained open.

## Next work

Reconstruct XP-016 successful patches plus reviewed shell edits; record omissions, recover its generated fixture safely, checkpoint before tests. Then proceed in order through XP-022 and NEC-009. Preserve fresh reports under `docs/recovery/evidence/` or the persistent recovery evidence directory.

## Checkpoints

- `9147783`: protected independent XP-015 workspace.
- Next checkpoint: XP-016 source reconstruction, explicitly unverified. Exact patch ledger: `docs/recovery/xp016-reconstruction-ledger.json`.
- Excluded failed calls 7096 and 7473. Replayed reviewed shell edit 7102. Historical evidence-generation commands were not run.

- `c2f7e81`: first XP-016 source checkpoint (earlier closeout). Later continuation recovered through line7936, before XP-017 starts at7950. Fresh Unity rerun pending; Unreal build in progress.

## XP-016 recovery verification ? 2026-10-12

Source checkpoint `6dc9f7d` includes the original successful Unity continuation. Fresh retained summary: `docs/recovery/evidence/xp016-20261012/summary.json`.

- Unity/Godot/Unreal: all 15 contract cases each, geometry and input fencing pass. Unreal Development/Shipping builds pass.
- Godot and Unreal live authority/reconnect proofs pass at generation2; session regression passes.
- 13 Rust contracts, 35 project-system, 7 Player launch, 14 engine-routing tests pass; adapter reversibility/handoff pass.
- Exported Player input/lifecycle and the explicitly selected presentation subset pass. Missing-cosmetic case remains outside the historical passing subset.
- Earlier attempts remain retained: absent compiler prerequisite, staging-path refusal, and pre-continuation Unity setup failure. These were resolved without weakening checks.
- Original XP016 JSON and XP022 seal remain missing. Fresh reports are not original evidence.
- Preservation: 2,707 initial files and 813 additional files; manifests under `preserved/20261012`. All 36 preserved owning-Git files still match originals. Local copies only.
- Raw fresh artifacts are persistent under `C:/Users/ankit/XACE-Recovery/evidence/20261012` and this worktree's `recovery-evidence/20261012`. Never clean these folders.

Next: reconstruct XP-017 from original transcript line7950 onward, identify its actual final continuation, and checkpoint before verification. XP-018 through XP-022 and NEC-001 through NEC-009 remain pending. NEC-010 is prohibited until recovered implementation and NEC-009 are verified.
