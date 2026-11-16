> CURRENT 2026-11-16: The signed-artifact code prerequisite is now implemented and locally verified; first-party continuity scope is explicitly approved. Actual publisher-backed XACE signing and external certification remain open. See [current implementation and remaining gates](NEC018_LOCAL_IMPLEMENTATION_STATUS.md). Earlier status/planning text below is retained as historical context; existing archive/evidence copies remain unchanged.

# NEC-018 local handoff status ? 2026-11-16

NEC-018 is INCOMPLETE. Local handoff preparation is verified; it is not clean-machine, private-alpha, public-release or Steam certification. Owner confirmed no clean Windows machine, three independent developer testers or signing certificate are currently available. All eight gate-ledger entries remain OPEN. No acceptance criteria were weakened or new roadmap tasks created.

## Prepared material

Persistent checkout: `C:/Users/ankit/XACE-Recovery/worktrees/xace`, branch `recovery/xp022`. The native candidate is pinned to source checkpoint `903bd018794e6c8d22641fbe2f95d1f4b653c2a6` and preserves exact previously verified native outputs; no native game was rebuilt for this kit.

- Archive: `evidence/nec018/20261116/handoff-b/NEC018-private-engineering.zip` (387,103,206 bytes).
- Archive SHA256: `ddc9ffac0cfb45c7b85015d4efea85f012f2fa6a4373f4c9835be452458e9876`.
- Extracted candidate: `evidence/nec018/20261116/handoff-b/handoff`.
- Candidate SHA256: `42a50cff1bf9c0a3e19cf8437ecbfb5a598025a36bd45cbb7a89a8fd1f7a0cc0`.
- Native payloads total 784,495,409 bytes: Godot 4.6.3 / 50 objects, Unity 6000.4.9f1 Mono / 51 entities, Unreal 5.7.4 D3D11 Development / 50 objects.

The archive includes all three native payloads, a self-contained Windows PowerShell environment collector/runner and byte-pinned support, test and signing-prerequisite documents. It needs no Python, Cargo, engine SDK or Builder on the player machine. It is unsigned private engineering material; external distribution has not been approved. Separate preserved creator projects/continuity archives and a properly configured authoring host are required for developer walkthroughs. This player kit does not itself provide a turnkey creator installer.

## Verified local work

385 project-system tests and 127 schema-factory tests pass. All NEC-018 Python entry points compile and both PowerShell scripts parse without changing security policy. The exact candidate passes one smoke launch per engine, structured native gameplay/projection assertions, normal owned-runtime/launcher cleanup and unchanged installation inventory. Those launches took approximately 8.37 / 11.17 / 11.07 seconds respectively, including observation and file verification; these are not authoring performance measurements. The runner defaults to three launches per engine for a future actual clean-machine trial.

A foreign candidate digest and a changed collector both fail before output-directory creation or any native launch. The archive is CRC/member-hash checked; every original source artifact is rehashed unchanged. All 55 recovered XP-022 protected files and 1,575 archived source entries remain unchanged. That baseline is explicitly `original_seal=false`; the original historical seal was not recovered.

The first local rehearsal is retained at `evidence/nec018/20261116/rehearsal-a`: Godot native assertions passed, but Windows PowerShell lost the process exit code. The revised runner owns the .NET process handle, drains redirected streams asynchronously and validates a real exit code. A preparation-script encoding failure was also repaired and Python entry-point compilation added. Neither failure was relabeled a pass. The passing candidate/rehearsal/audit are `handoff-b`, `rehearsal-b` and `audit-a`; earlier attempts remain untouched.

## Remaining mandatory work

1. Implement the versioned unsigned-build ? signed-artifact derivation, matching Python/Rust trust/admission and creator-packaging integration; then test it with an authorized certificate and new exact artifact identities. Current v1 admission requires reproduced unsigned output hashes to equal final executable bytes, so simply signing the existing executor would invalidate admission. See [signing prerequisite](NEC018_SIGNING_PREREQUISITE.md); estimated 1?2 focused engineering days plus 1?2 days for real signed three-engine verification after resources become available. This local code prerequisite remains unimplemented.
2. Run actual fresh Windows x64 installation/offline/canonical-behavior/security/process/network checks for all three final candidates. Same-laptop PATH isolation and TCP sampling do not establish a fresh OS or packet-level isolation.
3. Execute the distinct-version update, failed-update retention, explicit rollback, per-game save namespace, migration-or-unchanged-refusal and portable-removal independence matrix on those clean machines. The runner does not perform this matrix. Save admission is not gameplay-state restoration or automatic migration; there is no certified general installer/updater.
4. Observe three actual independent first-time developers complete the supported workflow without terminal/source repair, retaining failures and assistance.
5. Complete actual two-machine LAN, deployed valid-TLS/two-network Internet, exact-publisher signing and redistribution/continuing-use approval. Steam installation/update/client-lifecycle evidence remains required for any Steam claim.

The detailed [external protocol](NEC018_EXTERNAL_TEST_PROTOCOL.md), [support/loss/exit disclosure](NEC018_SUPPORT_AND_EXIT.md) and [acceptance](NEC018_ACCEPTANCE.md) govern those trials. No runtime-free export or unrestricted gameplay claim is made. Previous limitations and release gates remain in force.

## Preservation

Source and compact evidence are committed and pushed to the existing GitHub recovery branch; see the adjacent backup-verification receipt for the exact backed-up checkpoint. Large native artifacts, archives, raw logs and the recovered XP-022 baseline remain local-only and still need an approved off-device backup. No original repository, historical evidence or sealed baseline was changed. Compact local evidence: `docs/evidence/nec018-handoff-20261116/summary.json`; full local records remain under `evidence/nec018/20261116`.
