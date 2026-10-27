# NEC-015 Unreal native Play and Windows packaging

Status: INCOMPLETE. Final local verification is in progress. Mandatory clean-Windows-machine verification remains unavailable; no prior acceptance criterion is waived. NEC-016 has not started.

## Declared profile

UE 5.7.4 Windows x64, D3D11, native C++ Editor target and Development packaged game. Existing explicitly bound actors and their saved map are retained. Rust remains gameplay authority; native input, World projection, audio and animation use the existing protocol. The Unreal process serializes only host startup through handshake/Stop to prevent simultaneous PIE worlds racing over release activation. Running worlds retain separate owner/runtime processes.

Supported bindings are static, translation-only hierarchies with identity rotation/scale and no native physics authority. Required audio uses USoundBase; animation uses a compatible skeletal mesh/animation asset. The existing registered semantic playback catalog remains the presentation boundary. Dynamic creation/destruction/reparenting, arbitrary Blueprint gameplay authority, extra simulation backends, all animation graphs, embedded-browser gameplay and unrestricted mechanics are not certified here. This small native fixture does not replace NEC-017's 1,000-object requirement.

## Creator route

1. Compile the project's native Editor target with the XACE adapter module. Configure UXaceNativeHostComponent with reviewed native actor mappings, timed input bindings, relative release path, game identity and pinned release/launcher hashes.
2. Save and review source. Explicitly call XaceNativeApproval::RecordSavedSource in the Editor integration. Approval is create-only; preserve an earlier approval outside the source tree before approving another revision. Unsaved maps/assets and stale inventories refuse Play. The integration currently exposes the C++ approval API, not a new general authoring UI.
3. Use tools/nec015_build.py with the .uproject path, a fresh persistent output directory outside the project, the installed Engine directory and the native /Game map path. The wrapper requires the precompiled Editor module, checks source admission without starting gameplay, runs the normal Game build/cook/stage/archive, then checks cooked admission and source stability before issuing its success receipt. Failed staging is retained.
4. A successful Unreal process exit alone is insufficient: graceful native refusals can return zero. Require receipt.json with status built-not-certified and review its pinned artifact files. Do not distribute a failed staging directory. The final supported wrapper verification is still pending at this draft.

Approval excludes generated Binaries, Intermediate, Saved, DerivedDataCache and the two exact generated Windows FileOpenOrder logs, plus receipt/evidence metadata. Authored build settings remain checked. No approval is inferred from Play or compilation. Tests that synthesize approval are explicitly labeled fixtures.

## Runtime, updates and limitations

Distribute the full checked native package, including its pinned Rust launcher/executor and native release metadata. Shipping does not require the XACE Builder or development tools; this does not mean the game has no bundled XACE runtime. Clean-machine prerequisite coverage is not yet evidenced.

Per-game writable data lives under LOCALAPPDATA/XACE/NativeGames. Save checking admits compatible envelopes without restoring gameplay and refuses incompatible schemas without modifying the save. No automatic migration/restoration is claimed. Updates/rollback use explicit checked release selection and NEC-012 activation safeguards, not a general automatic installer or Steam integration. A native-binary update is distinct from a new gameplay-schema version.

Map reload ends the previous authority and starts a fresh session; it is not seamless state continuity. Fault tests verify only test-owned processes. Multiple PIE worlds in one Editor are supported by the startup queue; unrestricted concurrent independent installations sharing one save namespace are not certified. Editor proof runs disable unused CEF; earlier Chromium shutdown failures remain preserved.

## Evidence and preservation

Passing and failed attempts remain under persistent evidence/nec015. Earlier checkpoints are in docs/evidence/nec015-*. Final source-bound receipts and acceptance disposition will be added after the remaining tests. The protected XP-022 baseline is the recovered seal, not recreated original historical evidence. Current integrity verification preserves all 55 protected files and 1,575 archived source entries.

Clean-machine, signing, first-time tester, external networking and Steam gates remain open. Source and compact evidence are checkpointed to recovery/xp022; raw native binaries, fixtures and the recovered sealed archive remain local-only and need off-device backup.
