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
| XP-017 | Reconstructed; original evidence missing | All three local scenarios pass; initial four-client timeout unresolved |
| XP-018 | Reconstructed from successful records; source c5a81ba | 857 Rust + 10 Builder tests; candidate and live isolation proof pass |
| XP-019 | Reconstructed; source a6a70b2, harness f9802c0 | 842 runtime +21 reference; all local matrix gates pass, recurring timeout unresolved |
| XP-020 | Reconstructed; source 9775bce, harness 0c9a4a4 | 864 Rust tests and actual four-client replay proof pass |
| XP-021 | Reconstructed; source 4ea57e2, harness 626c8f6 | 883 tests, Builder build/UI and actual browser walkthrough pass |
| XP-022 | Historical source reconstructed through final seal-tool corrections | Fresh certification pending; original seal missing |
| NEC-001 through NEC-008 | Pending | Not run |
| NEC-009 | Pending; historical final edits unverified | Not run |
| NEC-010 | Not started; blocked until recovered implementation and NEC-009 verified | Not run |

## Evidence boundaries

Original XP-022 sealed artifacts remain missing. Reconstructed historical docs are not fresh verification and must never be presented as an original seal.
Historical NEC-009 passed 337 tests before later edits; 338 passing tests and final closeout are unverified.
XP-016 initially had a Unity license blocker; original continuation at transcript lines7926?7939 fixed the proof setup and passed Unity. This continuation is now recovered. Missing-cosmetic startup regression remained open.

## Next work

XP-016 reconstruction and fresh historical-scope verification are checkpointed at `8625fd5`. Next reconstruct XP-017, then proceed in order through XP-022 and NEC-009. Preserve fresh reports under `docs/recovery/evidence/` or the persistent recovery evidence directory.

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

- `8625fd5`: XP-016 fresh verification checkpoint. Small unit-test logs are committed in the following checkpoint; raw build and native logs remain in persistent recovery evidence.

## XP-017 recovery in progress

Original transcript range7950-8252; source patches replayed with original execution records. Original retained evidence generator stays preserved as patch text, not executed against missing historical results. Original baseline JSON/video evidence remains missing.

**OFF-DEVICE BACKUP: NONE. All recovery checkpoints, including this milestone, exist only on the internal SSD.**

- XP-017 source checkpoint `12f4733` (unverified, no off-device backup). Recovery-only harness adjustment: configurable persistent build/Unreal project paths and refusal to restage an existing build. Original production changes remain faithful; original generated evidence is missing. Fresh acceptance is in progress.

## XP-017 fresh acceptance - 2026-10-12

Source `12f4733`; persistent harness safety `9ed100c`. Fresh retained summary: `docs/recovery/evidence/xp017-20261012/summary.json`. Player/Godot, three-native and four-client combinations pass all 40 ticks, ownership, world rejection, applied digests/events, cross-owner effect at tick7, accepted recorded input, departure at19 and survivors through39. Unity 15-case regression and fresh Unreal native build/contract proof pass. Actual Player recordings retained (40 and20 frames).

Initial four-client run timed out after tick12 (Unreal input13 absent, Player liveness failure). Unchanged retry passed. Cause remains unresolved; no reliability or remote-network claim. Both attempts retained. Original XP017 retained JSON and recordings remain missing; these are fresh evidence. Next: XP018 reconstruction. All checkpoints remain **NOT BACKED UP OFF-DEVICE**.

## XP-018 reconstruction

XP017 verification checkpoint: `3e36d66` (NOT backed up off-device). XP018 historical range8253-8574 replayed in order, including original rustfmt after8402. Failed call8489 excluded. Retained-evidence generators8560/8568 preserved as raw patch input, not run against absent original results. Fresh candidate proofs and regressions pending.

## XP-018 fresh acceptance - 2026-10-12

Source `c5a81ba`; 857 runtime/reference tests (including 6 candidate cases), 10 Builder authoring tests and final approved-authoring/live-controller isolation proof pass. Fresh retained evidence: `docs/recovery/evidence/xp018-20261012/summary.json`. Original evidence remains missing. No activation claim: XP019 is next. This checkpoint and all previous checkpoints are NOT backed up off-device.

XP018 verification checkpoint: `17c89ad`. A UTF-8 read error prevented the first master-plan update; corrected in the following documentation checkpoint. No test failure resulted.

## XP-019 source reconstruction

Successful historical patches replayed through9288. Original failed8936 excluded;8726 first two patches and intervening shell edit succeeded, third patch was rejected and excluded. The later8745 digest-only bounded control implementation was recovered. Original successful shell extraction8646 recovered. Proof launch paths preserve the XP017 recovery safety adjustment; further persistent-path harness adaptation is pending. No fresh activation claim yet. NOT backed up off-device.

XP019 source checkpoint `a6a70b2` (unverified; not backed up off-device). Recovery-only proof adaptation adds explicit persistent artifact/Unreal paths and refuses restaging existing artifact roots. Production activation semantics are unchanged.

## XP-019 partial fresh verification

Source/harness `f9802c0`: 842 runtime tests and 21 reference/fault tests pass; production host without fault-injection builds. Player/Godot 40-tick activation proof passes, including join fences and old-parent restart refusal. Fresh Unreal build is in progress; three-native and four-client activation acceptance are still pending. Partial evidence under `docs/recovery/evidence/xp019-20261012`. All 36 original owning-Git files remain hash-identical. NOT backed up off-device.

## XP-019 fresh acceptance

Fresh historical local gates pass: 842 runtime +21 reference/fault tests, production host build, Unreal Development/Shipping build and 15 native cases, all three 40-tick activation combinations, admission probes, epoch8 transition, changed behavior at9 and old-parent restart refusal. Evidence: `docs/recovery/evidence/xp019-20261012/summary.json`. Four-client first attempt timed out after Unreal baseline acknowledgement without input0; unchanged retry passed. This recurring missing-input issue (also XP017) is NOT repaired and remains a final recovery acceptance audit blocker. Original evidence remains missing. Next XP020 reconstruction; NOT backed up off-device.

## XP-020 reconstruction

XP019 gate checkpoint `1f825e8`; recurring native timeout remains open. XP020 source replayed through9478, including historical rustfmt after9421. Original retained evidence generator was not executed. Fresh replay and regression gates pending. All checkpoints NOT backed up off-device.

XP020 source checkpoint `9775bce` (unverified). Recovery-only replay harness adds explicit persistent artifacts and native project paths. No runtime semantics changed. NOT backed up off-device.

## XP-020 fresh acceptance

842 runtime +22 reference tests pass. New four-client recording contains140 accepted input packets; prefixes before/at activation, full40 ticks, repeated replay and backward seek all verify without divergence or emitted presentation effects. Corruption/identity rejection and live-state isolation are included in the reference tests. Fresh evidence: `docs/recovery/evidence/xp020-20261012/summary.json`. This native run passed first attempt; earlier missing-input failures remain unresolved and do not count as fixed. Original evidence remains missing. XP021 is next. NOT backed up off-device.

## XP-021 reconstruction

XP020 gate checkpoint `46d22f7`. XP021 successful historical source patches replayed through9691. Historical evidence generation was not executed. Fresh runtime, reference, debugger, authoring, Builder build and browser walkthrough gates pending. NOT backed up off-device.

XP021 source checkpoint `4ea57e2` (unverified). Recovery walkthrough explicitly selects the fresh XP020 archived host/recording and independent current host; no original repository binary is executed. Output remains persistent. NOT backed up off-device.

## XP-021 fresh acceptance

842 runtime +22 reference +9 debugger +10 authoring tests pass, plus Builder build/UI and actual browser walkthrough. Live authority advanced175 to1022 while inspecting; historical replay/live fork verification, guest refusal and explicit creator control pass. Fresh evidence: `docs/recovery/evidence/xp021-20261012/summary.json`. Offline dependency install failed ENOTCACHED;338 existing dependency files were copied/hash-checked read-only from original checkout after version comparison with lockfile. Source and lockfile unchanged. Fresh current host pinned at `recovery-evidence/20261012/xp021/verified-XP021-reference-host.exe`. Earlier native timeout remains unresolved. XP022 is next. NOT backed up off-device.

## XP-022 reconstruction

XP021 verified checkpoint `7e43b1f`. Successful XP022 patches replayed through11147, excluding unexecuted9793 and historical target evidence generator10706. Reviewed shell edits9993,10051,10196 recovered. XP021 proof path overlap reconciled to explicit recovered inputs and one pinned final host. Historical certification documents carry missing-original-evidence banners. Fresh release tests, installed-host A-H, process faults, packaging/lifecycle, replay/debugger and two-hour soak are pending. No original seal is recreated or claimed. NOT backed up off-device.

XP022 source checkpoint `fcc087e` is unverified and NOT backed up off-device. Fresh final-host harness now accepts the persistent Unreal project explicitly, preserving recovered scenario argument order. Fresh verification is next; original seal remains missing.

## XP-022 fresh verification in progress - 2026-10-13

Production release build and persistent artifact staging pass. Pinned runtime/launcher/relay hashes are in `recovery-evidence/20261012/xp022/pinned-binaries/identity.json`. Fresh 23 reference/fault tests, 8 world-extensibility tests and XP011/012/013 production socket/admission/recovery proofs pass. Native, runtime regression and remaining local certification gates are in progress; two-hour soak is pending. No original seal has been recovered. NOT backed up off-device.

XP022 short local gates now pass: 842 runtime +23 reference/fault +8 world tests; all native readers; final mixed-host activation and replay; production faults; browser debugger; Player input/presentation; launcher/invite/local TLS relay; unsigned release inventory and ZIP. Fresh compact evidence: `docs/recovery/evidence/xp022-20261013/summary.json`. Sixty-second preflight is running; two-hour soak, archive verification and fresh recovery sealing remain pending. No original seal recovered; native intermittent-input issue remains a final recovery audit blocker. NOT backed up off-device.

## XP-022 endurance interruption - 2026-10-14

The fresh two-hour soak FAILED after 4378 seconds wall-clock: all four Players reported liveness failure after matching tick20555. Windows Kernel-Power42 records Button/Lid sleep at 2026-10-13 10:39:41 IST; Kernel-General1 records a 3629.739-second clock adjustment on resume. The sampler gap was about3636 seconds. This is interrupted endurance evidence, not a pass or proof of a gameplay defect. Failed logs remain intact; compact assessment and power events are under `docs/recovery/evidence/xp022-20261013/failed-soak`. Short gates remain passing. Retry awaits owner confirmation of an uninterrupted awake laptop window; no system power settings changed. XP022 sealing/NEC reconstruction remain pending. NOT backed up off-device.

## Newly found original XP022 receipt - 2026-10-14

Preserved six user-located files (50,360 bytes) read-only from Downloads/blender into `C:/Users/ankit/XACE-Recovery/preserved/20261014/newly-found-xp022`. The original engineering-candidate receipt is RECOVERED: SHA256 `2d66ac3f4b0b6f4abf76e59b6a349cf73a1571e1b78cc18f2fb5347a6630ee79` matches the historical baseline-manifest identity. Its 27 report references and nine sealed-file references survive; referenced source archive, binaries and detailed original soak evidence remain missing. Both recovered Python scripts match reconstructed text after newline normalization, including the original corrected bounded soak route. Status doc differs only by the added recovery warning. Bytecode preserved, not executed. Earlier blanket missing-seal statements now mean missing sealed payloads, NOT missing receipt. User confirmed an awake/plugged-in retry window and requested background execution without a two-hour active agent wait. Fresh retry will use a separate persistent output and the unchanged pinned binaries. NOT backed up off-device.

## XP022 second soak diagnosis

Retry failed after1556.593 seconds, last matching tick36720. All four input packets for36721 reached the journal; only peers3/2 have accepted-validation records before termination. No matching sleep event or large sampled gap found. Input-stage timings reached seconds; synchronous SessionLog write/sync_data is the leading suspect, not a proven root cause. XP011/012 explicitly require durable input admission, so flush removal is not acceptable. Added opt-in `XACE_SESSION_LOG_DIAGNOSTICS` watchdog reports journal lock/write/sync_data stalls without changing durability or liveness thresholds. This is DIAGNOSTIC INSTRUMENTATION, NOT A VERIFIED FIX. Fresh isolated candidate/regressions in progress. Prior evidence/binaries unchanged. NEC remains on hold; NOT backed up off-device.

Diagnostic candidate `24d4c7e97bc956f22911a1665d682cd65bb7617af467ac3c736fa64f368b14d3` passes842 runtime tests, production socket/admission/fault checks, and60-second four-Player preflight (1735 ticks,9.6469ms p95, mutations/reconnect). Next background diagnostic soak is under `recovery-evidence/20261014/xp022-stall-diagnostic/background-run`; journal watchdog enabled. No root cause or fix claimed yet; full run and diagnosis pending. Previous production artifacts and failed runs preserved. NOT backed up off-device.

## XP022 durable validation group commit - 2026-10-15

Diagnostic soak completed7200.735 seconds/182002 ticks without a freeze or journal-stall warning, but FAILED performance:18.8007ms p95 versus16.7ms. Peak authority memory63,651,840 bytes. Automatic archive verification was skipped; a separate exact-host verification is running. The earlier intermittent freeze remains unconfirmed. Stage timings identify inbound and input-scheduling as the main cost, including per-record durable journal flushes. New recovery repair batches validation records from each ingress pass into one write+sync before lockstep release. Raw input, admission, activation and replay durability are unchanged; validation order/content retained; write/sync failures propagate before release. This is a new repair beyond historical reconstruction.845 runtime tests pass, including three batch durability regressions. Production build/process checks pending; no new soak pass claimed. NOT backed up off-device.

## XP022 ingress batching candidate - 2026-10-15

First validation-only repair failed short performance preflight (95.5974ms p95); failed evidence preserved. Full prior diagnostic archive independently verifies711 segments/182002 ticks. Second repair groups raw receipt records within the inbound staging pump and flushes before that pump returns to authoritative input collection. Validation durability barrier remains. Added scope/error/order/size tests; runtime suite passes847 tests. Production build and process/performance checks pending. Gate wrapper now rejects functional smoke results whose timing budget fails. Earlier intermittent freeze remains unconfirmed. This is a new recovery repair, not historical source equivalence. NOT backed up off-device.
