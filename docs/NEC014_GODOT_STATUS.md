# NEC-014 Godot native Play/export status

Completed 2026-10-26 for the declared local Godot 4.6.3 stable, standard GDScript Windows x64 profile. This is not general shipping certification. NEC013 remains incomplete pending its mandatory clean-machine test. NEC015 has not started. Existing clean-machine, signing, first-time tester, external networking and Steam gates are unchanged.

## Implemented and verified

The developer main scene remains in use. Explicit World-ID-to-NodePath bindings project authoritative state onto existing Node3D objects through the existing transport/applicator. The shared NEC012 Rust host owns the runtime; input is ticked, gameplay stays in the runtime, and required presentation is native AudioStream/AnimationPlayer playback. The native host fails closed on authority loss and never switches to local gameplay.

Source approval pins saved project files, engine version, native profile and package inputs. The editor plugin checks approval on Play and embeds a checked/refused stamp during export. The creator export wrapper additionally verifies the copied release and starts the exported executable in a dedicated packed-scene/resource preflight mode. That mode must return xace.godot.native_preflight.v1, packed=true and authority_started=false. The wrapper emits a complete file-hash receipt only after both checks pass. Receipt status is built-not-certified. Fresh output outside the project is required; failure retains staging and never replaces an earlier export.

Evidence: docs/evidence/nec014-completion-20261026/summary.json; earlier focused checks: docs/evidence/nec014-native-increment-20261025/summary.json. Earlier incomplete status remains historical; the new bundle supplies closeout.

| Acceptance | Concrete proof |
| --- | --- |
| New native main scene, input/world/event parity, cooked resources | export-final-g: NativeGame.tscn runs authoritative movement plus packed audio and animation; executable relocated, restricted PATH, unchanged installation |
| Existing project retains its scene | existing-fault-export-d: copied NEC011 authoring project retains Fixture/World.tscn byte-for-byte, including native identity metadata and parent hierarchy; same scene runs and exports |
| Actual editor lifecycle | editor-play-a uses EditorInterface.play_main_scene; existing-fault-export-d uses actual Editor Play and stop_playing_scene |
| Failure ownership | existing-fault-export-d kills only its recorded runtime, checks projection frozen for20 frames; abrupt recorded Godot exit and Editor Stop clean both owned processes while an unrelated sentinel survives |
| Refusal and export preservation | refusal-a: stale source rejected, prior output sentinel unchanged, required audio excluded from PCK refused without authority startup, failed staging retained |
| Read-only/save/update/rollback | update-final-d: ACL denies writes; actual final export checks compatible envelope without restoration, preserves incompatible envelope, refuses bad release without changing activation, explicitly returns to prior release and retains save sentinel |
| Shared behavior regression |9 actual Godot client lifecycle checks;22 Godot playback/resource/input mapping checks; existing exported Player lifecycle regression. Shared runtime/Player code was not modified in NEC014 |
| Baseline integrity |55 protected recovered XP022 files and1575 archived source entries checked unchanged |

The existing-project proof adds fixture observer/host integration and explicitly changes settings in a copy; it does not demonstrate automatic migration of arbitrary game code. Its original source is unchanged. Test input is programmatically submitted to the native collector; physical controller/device certification is not claimed. Restricted PATH and local loopback execution do not establish firewall-isolated or clean-machine operation.

## Creator integration and supported boundary

1. Use the admitted NEC012 release layout, including pinned launcher, executor receipt, package and resources. Copy Godot adapter scripts and install native_export as addons/xace_native_shipping. Enable that editor plugin. Preserve the project's own main scene.
2. Add xace_native_host.gd to an opt-in Node, and supply xace-native-profile.json (schema xace.godot.native_profile.v1). It declares game_id, relative release_directory, release_sha256, launcher_sha256, controller_id, explicit World object IDs mapped to NodePaths relative to the host, and input_bindings. The final fixture source approval records an exact example.
3. Save and review the source before explicitly recording approval using the editor tool menu. Approval is create-only. Preserve any previous approval outside the source project before intentionally approving a changed revision; there is no automatic reapproval. No source/review approval is inferred from Play.
4. Configure the existing Windows Desktop export preset with the installed standard x64 template; include the native profile JSON and exclude release/* from the PCK. The wrapper copies the admitted sidecar release. Run tools/nec014_export.py with project, a fresh persistent output path outside that project, and the installed Godot console executable. The fixture scripts create synthetic approvals solely for controlled tests.
5. Distribute the entire shipping directory only after reviewing receipt.json and its file hashes. Required resources must resolve from the PCK. Writable per-game saves live under LOCALAPPDATA/XACE/NativeGames/<validated-game-id>/saves, not the installation. Preserve the release-state history and save namespace across updates.

Godot's EditorExportPlugin callback has no cancellation result: a refusal stamp/error alone cannot guarantee Godot reports a failed export. The wrapper and its successful receipt are mandatory for this supported export route. Packed preflight invokes the trusted main scene and its scripts; it is not a sandbox for untrusted scripts. The experimental xace_native_preflight.gd creator utility is not used or certified by the exported preflight route; exported --script was observed to be ignored.

Only static, translation-only approved hierarchy and existing mapped objects are certified here. Nonidentity basis/unsupported physics poses are refused. Dynamic spawning, destruction of a bound parent with surviving children, arbitrary reparenting, seamless scene transitions and additional physics/simulation backends are not certified. This two-object native integration proof does not satisfy or lower NEC017's1000-object target. Required AudioStream/AnimationPlayer bindings and the existing semantic catalog are the declared presentation profile, not all Godot animation graphs or effects. Save checking does not restore gameplay or migrate a snapshot. Update/rollback uses explicit release selection and NEC012 activation safeguards, not an automatic installer.

## Retained failures and evidence provenance

All raw attempts remain preserved. export-preflight-e is excluded: the exported template ignored --script and ran regular fixture gameplay. That attempt created synthetic compatible/incompatible save envelopes in the laptop's ordinary LOCALAPPDATA/XACE/NativeGames/game-nec012-proof/saves namespace; those files were retained, not removed or presented as user saves. The corrected f/g preflight uses a dedicated host flag, isolated LOCALAPPDATA, distinct result schema and asserts no authority starts.

existing-fault-a failed on fixture indentation; b failed on an incorrect console-wrapper PID assertion. The corrected d proof uses the freshly reported owned Godot PID. Earlier playback-b reported an exit resource warning; final exports did not reproduce it, but no general fix is claimed. These failures are not counted as passing evidence. Original historical XP022 evidence lost during cleanup has not been recreated or relabeled: the protected baseline here is explicitly the recovered XP022 seal.

Source and compact evidence are checkpointed in recovery/xp022; remote identity is checked after push. Raw native fixtures, binaries and the recovered sealed archive remain local-only and still need off-device backup.
