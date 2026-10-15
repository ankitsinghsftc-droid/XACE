# XP-022 recovered engineering closeout

Local engineering acceptance passed on 2026-10-15. External release gates REL-01 through REL-05 remain open. This is fresh recovery evidence; it does not replace the recovered original receipt or claim that missing original sealed payloads were recovered.

The production host SHA-256 is `ccbd880532321eb86c544e40260da6238b3ee3232bd68026bd9b848d54543ae1`. Runtime implementation checkpoint: `dd2741c`. Subsequent changes affect documentation and native proof tooling; packages, examples and Cargo manifests are unchanged. Journal batching preserves the durability barrier before authoritative input release. It is a new recovery repair beyond historical reconstruction.

## Evidence reconciliation

- 847 runtime and 23 reference/fault tests pass on the repaired source.
- Pinned production socket, process-fault, mixed-engine activation and replay checks pass.
- Final-host browser debugger, Player input and presentation, normal launcher, invite and local TLS relay were rerun and pass.
- All 15 native contract vectors pass per engine. Godot/Unity evidence is carried forward only after verifying all 35 relevant source/fixture files byte-for-byte. Unreal Development/Shipping was rebuilt and its 15 cases rerun after the proof-only correction.
- Two-hour four-Player soak: 7200.844 seconds, 188507 ticks, p95 11.6411ms within 16.7ms. Reconnect and clean authority exit pass. All 737 replay segments verify all 188507 ticks without divergence.
- All 25 unsigned distribution inventory entries match disk and release ZIP. Runtime identity matches the soak. ZIP SHA-256: `86c9adce5c7be056107c3836331a73f841eb901e4231b46d523627b89b8553eb`.

Evidence: `evidence/xp022-closeout-20261015/` and `evidence/xp022-ingress-batch-20261015/completed-soak/`. Full raw runs remain under persistent `recovery-evidence/`; no old report is edited or relabeled.

## Correction of the native-input diagnosis

Earlier progress notes incorrectly described missing Unreal network inputs. The preserved XP017 journal contains Unreal input13, and the XP019 journal contains Unreal input0, despite corresponding rows being absent from Unreal's transcript. Exact journal line numbers and file hashes are in `historical-input-correction.json`. The proof harness waits for those transcript rows before launching Player or stepping its paused authority. Therefore missing rows alone stall the proof and can trigger Player liveness failure without missing network delivery.

The Unreal test writer ignored `SaveStringToFile` failures and omitted `FILEWRITE_AllowRead`, while Python continuously reads the transcript. The installed-engine regression holds a reader open: the original append fails, the corrected append succeeds. The corrected writer also explicitly fails the proof on any write failure. A complete 40-tick four-client activation session passes with that reader held open throughout. Three additional observed/fragmented-frame sessions passed without transport changes. This closes the native missing-input acceptance blocker as a reproduced evidence-writing/harness defect. The old attempts did not capture OS sharing errors, so the exact historical OS error cannot be retroactively proved.

The separate earlier four-Player endurance freeze still has no captured blocked stack; it is not asserted to have the same cause. The new journal repair passes the full endurance gate, but does not establish immunity to every intermittent failure.

## Recovery baseline and boundaries

The next operation seals this checkpoint into `C:/Users/ankit/XACE-Recovery/baselines/xp022-recovered-20261015`: actual source archive and manifest, exact unsigned release ZIP, pinned runtime/launcher/relay and Unreal proof binary, compact evidence, and a SHA-256 baseline manifest with readback verification. The receipt is committed separately after creation to avoid a circular source hash. Unique material never goes under build-output directories.

The owner has authorized the engineering-closeout then NEC001-009 recovery sequence with external gates deferred. Clean Windows, two-machine LAN, public relay across two networks, signed distribution and three first-time testers remain unpassed. The separate commercial endurance requirement is not satisfied by this two-hour local gate. No public release certification is claimed. All checkpoints and evidence remain **NOT backed up off-device**.

After sealing and readback, restore NEC001 against this recovered baseline, reconcile its historical handoff assumptions, then restore NEC002-009 sequentially with fresh verification and commits. NEC010 remains prohibited until recovery acceptance is complete.
