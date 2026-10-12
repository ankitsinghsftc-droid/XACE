> Reconstructed historical document. The ORIGINAL XP022 SEAL AND EVIDENCE ARE MISSING. Historical passing claims below are not fresh recovery certification. See AGENT_PROGRESS.md. Never reuse disposable paths for new unique evidence.

# XP-022 closeout review — 2026-10-08

Superseded for local engineering by `XP022_ENGINEERING_CERTIFICATION.md` and
`evidence/xp022-engineering-candidate.json`: the missing local fault/A-H/packaging
evidence below has now been completed. This earlier audit is preserved as history.
External release acceptance is still open; the proposed scope amendment is in
`XP022_RELEASE_GATES.md`. No public-release completion is implied.

**Verdict: NOT COMPLETE.** The endurance and archived replay gates passed.
The roadmap's mandatory certification criteria are not all satisfied. Previously
approved deferrals record pending acceptance; they do not turn those criteria
into passes. No final release baseline, release approval, commit or tag is created.

## Verified endurance evidence

Run: `target/xp022/independent-fixed-20261008-042759`.
The supervisor reports `passed`, all three return codes zero, and 7,379.078
seconds total. The soak itself ran 7,200.860 seconds with four actual exported
Players, headless over loopback on one Windows computer. It completed 202,271
authority ticks, mutations at ticks 256 and 512, and a Player reconnect.
Authority p95 was 12.0662 ms, below the 16.7 ms compute-time target; normal
authority exit was confirmed. Peak sampled private memory was 63,430,656 bytes
(60.49 MiB) for the authority and 38,068,224 bytes (36.30 MiB) for any Player.
This is not evidence of sustained 60 ticks per
wall-clock second, rendered frame rate, Internet latency or multi-machine play.

Automatic offline verification passed every tick across 791 durable segments.
Closeout checks rehash every segment and executable, validate the index chain,
completion marker and individual saved replay reports, and independently recompute
p95 from the raw metrics. They do not rerun the completed two-hour experiment.
The exact host, Player executable and Player resource pack hashes are retained in
`evidence/xp022-closeout-20261008.json`. This is a verified soak checkpoint,
**not a final XP-022 release baseline**. Its source inventory is a closeout-time
observation, not retrospective build provenance for all historical binaries.

## Acceptance reconciliation

| Mandatory criterion | Evidence and decision |
| --- | --- |
| Two-hour four-client soak with mutations/rejoin | PASS for the declared headless Windows loopback profile. |
| Authority p95 under 16.7 ms | PASS for recorded tick computation: 12.0662 ms. Complete reference-hardware/build-profile and separate latency/render report still required. |
| Bounded memory and queues | Soak enforces 256 MiB authority and 1 GiB per Player memory budgets, bounded comparison history and a 512-tick client-lag fence. PASS for sampled normal-load memory; adversarial slow-consumer queue/backpressure certification remains open. |
| Bounded reconnect and normal cleanup | Soak reconnect waits at most 20 seconds and succeeds; authority shuts down normally. Prior socket tests fence incomplete input/handshake and dropped baselines. Full fault-profile cleanup/reconnect certification remains open. |
| Every Proof H fault has an explicit safe outcome | INCOMPLETE: retained process/socket subsets and unit fault tests do not establish the complete final-binary real-process matrix. |
| Proofs A-H rerun on pinned binaries and fixture | INCOMPLETE: historical passes use different host hashes; they cannot be attributed to the final soak executable. |
| Release packaging, signing and notices | Final packaging/notices reconciliation is not recorded as passed. Signing is owner-deferred because no certificate is available. |
| Clean supported-machine installation | PENDING by owner instruction; no clean machine available. |
| Three first-time testers complete Play/Invite/Join/approve without terminal help | PENDING by owner instruction; no testers available. Automated debugger/Player checks do not substitute. |

## Proof ladder and fault evidence

| Proof | Retained coverage and limits |
| --- | --- |
| A: local Player | XP008/010 implementation evidence and current real exported Player soak. Clean toolchain-free installation remains pending. |
| B: canonical World Contract | XP016 installed-host evidence; no complete final-pinned rerun recorded. |
| C: invite | XP014/015 local evidence. Second-machine and public two-network trials remain owner-deferred. |
| D/E: mixed and three-engine session | `target/xp022/four-host-result.json` covers actual Unity, Godot, Unreal and Player for 40 ticks. This historical host is not silently relabeled as the final soak host. |
| F: activation | XP019 historical activation/fault evidence; current soak activates two configuration epochs. Complete final-process crash-boundary/migration/joins-around-N matrix remains unproven. |
| G: replay/debug | XP020/021 historical replay/browser evidence; current full archive replays 202,271 ticks. Final debugger/seek integration certification against segmented recording is not established by the archive verifier alone. |
| H: faults | `current-faults/report.json`, `release-admission/proof.json`, `release-input-faults/proof.json`, `release-recovery/proof.json` are passing subsets, not full certification. |

Admission evidence includes stale CGS, plan, world, input, runtime, epoch and
incarnation rejection, missing capabilities and invalid grants. Socket evidence
includes ownership/input rejection, duplicate flooding, alternate input arrival
orders, slow handshake, input timeout, late join, spent reconnect credentials,
stale acknowledgement and dropped-baseline fencing. Offline replay evidence
includes corrupted digest, truncated replay, missing recording and invalid seek.
The full presentation regression passes optional missing cosmetics, required
geometry/binding failures and cosmetic identity invariance.

These are distinct from the missing final-process evidence for crash before/after
commit, token **expiry** (not merely spent-token reuse), partial **package** transfer
(not merely truncated replay), slow-consumer/backpressure, all required transport
faults, and the complete activation failure/joins matrix. Unit tests and historical
proofs remain useful but do not satisfy the roadmap's final pinned A-H rerun.

## Baseline disposition

Preserve the successful run, its packages, raw logs, metrics, replay archive and
verification output. The evidence JSON pins the reports and all segment hashes;
generated data remains under ignored `target/`. Do not overwrite this run.
Earlier failed soak and checkpoint evidence remain available as historical records.

XP-022 and the whole XP roadmap cannot be marked unconditionally COMPLETE from
this evidence. Closeout only updated documentation and a hash-bound checkpoint;
it did not start new implementation, rerun long tests, change protected refs or push.
