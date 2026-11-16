# NEC-018 local implementation status ? 16 November 2026

Local implementation and local verification are complete for the declared Windows profiles. NEC-018 and the full NEC release claim remain INCOMPLETE: actual publisher-backed signing/final signed game builds, real external-network certification, clean-machine tests, independent developer walkthroughs and exact-final-candidate third-party/notice approval are still unverified. The owner deferred clean-machine/human tests only; the other external requirements have not been waived.

## What changed

- Added xace.native_executor_build.v2 and xace.native_release.v2 with independent publisher-policy pins. v1 unsigned receipts remain compatible and unchanged. Both original unsigned compiler outputs remain in the derivation; signing cannot alter source/build/system/capability/compatibility claims.
- Added matching Python and Rust Windows Authenticode verification: actual OS chain/integrity, verified signer DER SHA256, timestamp countersigner, allowed publisher and before/after executable identities. It is read-only, uses no shell or target execution, changes no trust store, and makes no fresh network retrieval. Current revocation/publisher approval remains a separate release check.
- Added strict PE derivation: reconstruct the reproduced unsigned executable hash from the signed file, allowing only the original checksum/security-directory changes, zero alignment padding and one appended PKCS certificate table. Another correctly signed executable cannot inherit the original build claims.
- Added create-only common-release, native-copy and signed-handoff finalization tools. They preserve original CGS/plan/presentation/sidecars/notices, reissue exact final identities, retain old build receipts, regenerate Unreal cooked hashes and require a newly pinned native verifier. Output alias normalization prevents writes into original source or disposable trees. Existing approvals remain explicit; no silent native source/profile overwrite was introduced.
- Added a v2 handoff validator and PowerShell publisher boundary. Prior unsigned native proofs stay labeled as context; a declaration or self-authored PASS cannot certify signed gameplay. All candidate gates start OPEN.
- Recorded the owner's explicit first-party shipping/continuing-use approval and issued [XACE game continuity terms](XACE_GAME_CONTINUITY_TERMS.md). Third-party rights and exact-final-candidate approval remain separate.
- Collected 1,343 notice-review files, including exact Unity 6000.4.9f1 Windows Mono Player/build-support notices, preserved Godot/Rust notices and an Unreal 5.7.4 installed-license superset. This is technical review material, not an automatic legal-rights or per-binary dependency determination. A separate 14,086,043-byte companion ZIP includes the approved first-party terms without altering any original game or notice packet.

## Verification and its boundaries

Final source-pinned regressions: 401 project-system tests, 127 schema-factory tests, 11 native-launcher tests and 2 relay tests, plus Python entry-point compilation and PowerShell parsing. Native integration proves actual current-host authority start/stop for the existing Godot/Unity/Unreal releases. All three common-host portable workflows prove distinct cosmetic updates, per-game namespaces, compatible save admission, unchanged incompatible refusal, failed/interrupted update retention, rollback, reversible portable removal and independent-game preservation. This is not MSI/general-installer, gameplay-state restoration or automatic migration certification.

Both language verifiers agree on an existing timestamped vendor signature. Common finalization, native delivery copying, Unreal cooked inventory reissuance and signed handoff creation pass a complete contract path using explicitly INERT vendor bytes and synthetic creator/engine metadata. Those fixture binaries are NEVER executed as games, launchers or runtimes. This proves verifier/packager behavior, not that XACE game executables have been signed by an approved XACE publisher. Wrong publishers, altered capabilities/original receipts, downgrade attempts, unrelated source edits and unsafe output aliases are refused. The PowerShell v2 wrong-publisher test stops before any native launch. Its successful signed-game launch path still requires actual signed XACE artifacts.

Protected native artifacts, the original unsigned handoff ZIP and all 55 recovered XP-022 protected files / 1,575 archived source entries remain unchanged. The recovered baseline remains original_seal=false; no original historical seal was fabricated. Failed attempts and all prior evidence remain intact. No source reconstruction, cleanup, original-repository modification or destructive removal occurred; only fresh test installation copies were reversibly quarantined and restored.

## Exact remaining requirements

| Requirement | Current state / required next input |
| --- | --- |
| Publisher-backed signed release | Integration implemented and locally tested. Need an authorized code-signing certificate/HSM/service; then sign NEW XACE executor/launcher/native game copies, run the checked native builds and final signature/gameplay/resource/offline/tamper/save tests against those exact bytes. No certificate is currently available. |
| Clean Windows install/update/save/removal | Owner deferred; actual fresh supported PC/VM, toolchain/Builder absence, security observations, packet evidence and final-candidate matrix still mandatory. |
| Independent developer certification | Owner deferred; three actual independent first-time people, real supported workflows and no terminal/source repair. |
| Real LAN | Need two reachable Windows computers and ordinary invite/join/rejoin/cleanup evidence. Local tests are not two-machine certification. |
| Real Internet relay | Need an authorized deployed relay with a valid public TLS chain and two real ordinary networks, plus outage/reconnect/expiry/cleanup evidence. No deployment or public exposure was performed. |
| Rights / notice closure | First-party continuing-use policy APPROVED. Need review/approval of actual final signed candidate, applicable engine/asset/dependency rights, delivered credits/notices and exact distribution scope. No final signed candidate exists yet. |
| Steam | No actual Steam certification claimed; corresponding client installation/update/lifecycle proof is required for any future claim. |

The [signing workflow](NEC018_SIGNING_WORKFLOW.md) and [external protocol](NEC018_EXTERNAL_TEST_PROTOCOL.md) provide the concrete sequence. All 18 NEC tasks retain their order and prior acceptance criteria. No architectural prerequisite was silently deferred or turned into a new task program. Remaining work is externally gated execution/approval, including final signed native build verification; it is not limited to the two tests the owner deferred.

## Paths and preservation

Checkout: C:/Users/ankit/XACE-Recovery/worktrees/xace; branch recovery/xp022. Compact current evidence: docs/evidence/nec018-integration-20261116. Full local records: evidence/nec018/20261116, specifically verification-h, signed-proof-c, portable-independence-c, signed-handoff-contract-b, signed-runner-refusal-a, native-signing-copy-a and integration-audit-b.

The existing real native handoff is still the unsigned handoff-b/NEC018-private-engineering.zip; its identities remain in the earlier evidence. Signed-handoff-contract directories contain INERT TEST FIXTURES and must never be distributed or executed as games. Notice/terms companion: evidence/nec018/20261116/notice-delivery-a/NEC018-notices-and-continuity-terms.zip, SHA256 2e982b7bbc36874c2961ad9d19df4d3f65d904517de46fc08006ef3c0a24df67.

Source, approved terms and compact receipts are checkpointed on GitHub recovery/xp022; consult backup-verification.json for the exact backed-up identity. Large binaries, archives, full notice packet, raw logs and the recovered XP-022 baseline remain local-only. No off-device backup of those raw materials is claimed.
