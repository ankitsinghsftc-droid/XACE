> Reconstructed historical NEC005 document. Fresh recovery verification passed:239 Python tests and74 installed-Godot checks; historical output paths below are not current instructions. See AGENT_PROGRESS.md.

# NEC-005 - Godot saved authoring capture and staged serialization

Completed 2026-10-09 in the local, uncommitted `target/xp016-work` tree.
Installed profile: **Godot 4.6.3-stable (official), Windows**, text and binary
PackedScenes, external binary mesh/animation resources and explicit input/bindings.
NEC-006 is not started. REL-01 through REL-05 remain OPEN.

## Implementation

The opt-in [authoring plugin](../adapters/godot/authoring/plugin.cfg) adds editor
APIs alongside the existing adapter. Frozen Godot runtime/Player scripts are
unchanged; authoring never uses feedback packets as schema edits.

- [Reader](../adapters/godot/authoring/authoring_reader.gd): saved discovery and
  capture, resource UIDs, explicit node metadata, packed-instance associations,
  dependency fingerprints, full rescan and retained native behavior dispositions.
- [Plugin](../adapters/godot/authoring/authoring_plugin.gd): explicit trusted-project
  opt-in, grouped editor metadata enrollment/duplicate rekey, Undo/Redo, editable
  instance enrollment and scene/save/filesystem/history invalidation.
- [Writer](../adapters/godot/authoring/authoring_writer.gd): approved field staging
  through PackedScene/ResourceSaver, saved readback, original-byte backups,
  receipt-bound publication and conflict-preserving recovery.
- [Wire](../adapters/godot/authoring/authoring_wire.gd): bounded canonical ASCII JSON,
  string numbers, duplicate/noncanonical request rejection and exact numeric checks.
- [Python bridge](../packages/project-system/godot_authoring.py): NEC-002 identity
  association, NEC-003 normalization/inspection/snapshot policy and concrete writer
  requests. It never launches Godot, commits CGS or advances a baseline.

`capture` is a saved-content proposal, not a claim that arbitrary native behavior
has been converted. This task adds callable APIs, not a default Builder migration
UI or automatic synchronization loop.

## Operating boundary

Install the authoring folder as an editor plugin in an **explicitly trusted,
already open project**, then call `approve_trusted_project()`. Approval is not
persisted. Scene/resource loading and PackedScene instantiation can execute trusted
project tool scripts/constructors; this is not an untrusted-project sandbox.
Untrusted project assessment still starts with existing filesystem inventory.

Only the pinned editor may capture or write. Actual Play mode and non-editor
processes are refused, even if a caller sets the trust flag. The proof loads the
unchanged `xace_protocol.gd` in a separate non-editor process while checking that
authoring access fails; no Player-only schema or separate runtime protocol exists.

**Selected scenes must be closed after the user saves or discards changes.**
The installed 4.6.3 API probe confirms no public unsaved-scene query. The integration
therefore refuses every selected open scene rather than guessing cleanliness from
an undo counter. It neither saves nor discards user buffers automatically. See the
official [EditorInterface API](https://docs.godotengine.org/en/4.6/classes/class_editorinterface.html)
and the retained local API probe. This profile reads saved resource data with deep
cache bypass; it does not claim to import unsaved inspector/resource edits.

Approved paths are existing `.tscn`/`.scn` files under `res://`; traversal, linked
paths, duplicates, missing dependencies and unsupported UIDs are refused. Capture
fingerprints include recursive saved dependencies, project input settings and
available `.uid`/`.import` sidecars. Before/after fingerprints must agree. Rescan
always reads the full selected scope, including when a notification was missed.

## Identity and captured content

`xace_identity_v1` metadata stores namespace, authoring ID, a separate persistent
local ID, generation, kind and prefab-definition reference. IDs are supplied
explicitly, not inferred from node names/paths. Document locators use resource
UIDs. Rename/reparent observations retain the same association; duplicate/foreign
metadata fails closed and requires reviewed recovery. Missing metadata is visible
to discovery but cannot silently become an adopted snapshot.

Scene roots are neutral `Node` metadata containers. A transformed scene root is
refused rather than losing its effect when translating hierarchy. Prefab-definition
roots can be Node3D objects. Packed instances and their descendants need distinct
instance-local metadata; source definitions must be included in the selected scope.
Native editable-instance overrides and source PackedScene references survive saves.
Enrollment groups identity and required editable-instance changes into editor undo.

Supported fields are Node3D local position/quaternion/positive scale, native name
(native-owned), external MeshInstance3D mesh/material references, explicitly named
saved InputMap actions and explicit Animation/Audio resource binding declarations.
Asset references use the existing `MESH`, `MATERIAL`, `ANIMATION_CLIP` and
`AUDIO_CLIP` types. Binary resources are loaded by Godot, never text-parsed.
Inline resources without a persistent external identity and scripted resources are
refused by this profile.

Unowned native properties remain in serialized scenes. Unknown node behavior,
scripts, project autoloads and persistent signal connections receive blocking opaque dispositions;
the Python bridge refuses schema admission for those captures. There is no inferred
GDScript, signal, animation-graph or physics behavior. Authoritative collision
conversion is not certified in this Godot profile: native physics remains opaque
and blocking. Reflected/sheared/degenerate transforms are also refused.

The native reader preserves decimal precision in text; NEC-003 reports any
fixed-point rounding and requires its existing bound review. Writes are narrower:
the inverse must survive Godot float storage exactly. The shared position golden
is written and restored. The shared 0.6/0.8 quaternion is explicitly refused as
inexact; an exactly representable rotation and scale are saved and checked.
No silent float approximation is introduced.

## Native writer and recovery

The Python `write_request` requires a matching native inventory, current identity
map, validated base/target snapshots and the explicit write-enabled policy.
Structural changes, component additions/removals, opaque changes and native-owned
name writes are refused. Native `prepare` accepts only the approved documents and
existing object identities. Supported writes are position/rotation/positive scale,
external mesh replacement and existing explicit input/playback bindings.

Preparation saves native copies under `.xace_authoring/transactions/<id>/`, reopens
them, verifies approved field readback and confirms the original inventory stayed
unchanged. Original bytes, staged bytes, dependency hashes and field previews are
bound into a canonical receipt. Publication requires that receipt's approval hash,
rechecks source/staged/dependency hashes and replaces only the approved files.
Temporary files stay in the transaction directory. No regex edits to native scenes
or binary assets are used.

Receipts persist before replacement and after each document. Recovery validates
the expected receipt hash, approved scope and backups. It restores only matching
owned after-images; newer edits are retained with `recovery_conflict`. Failure after
replacement, byte-exact undo, conflicting newer edits and recovery in a fresh
editor process are exercised. Retain the transaction directory until the later
coordinator resolves it. The proof explicitly resets its conflict fixture; the
production writer never silently resolves that conflict.

This is a native file transaction primitive, not the NEC-009 multi-store coordinator.
It does not lock arbitrary external programs, guarantee power-loss durability across
all storage devices, publish a CGS/native baseline or claim multi-editor crash
certification. Recovery after deleting backups is not supported. Approval UI,
cross-store orchestration, archive retention and cleanup policy remain later work.

## Verification

- **239 Python tests:** 11 focused Godot bridge tests and all 228 previously checked
  Unity/shared identity, contract, project, asset, World and edit-router tests.
- **74 installed-Godot checks:** 62 native save/capture/undo/staging/recovery checks,
  5 cold-process recovery/Python-write checks, 4 actual Play checks and 3 non-editor
  privilege/protocol checks. Native binary `.scn` writing and `.res` replacement
  are included, not just fixture-file presence.
- Native canonical JSON matches Python byte-for-byte. A Python-generated request
  is saved by Godot and re-imported as `(11000000,12000000,13000000)` with the same
  native identity map. The unknown-behavior native capture is rejected by admission.
- Early failures in a native type annotation, decimal canonicalization and animation
  asset enum mapping were corrected. Native attempt reports remain under
  `target/nec005/native-attempt*`. The headless editor emits a nonfatal dummy-renderer thumbnail error
  during scene save; save return values, bytes and reopened content pass. This is
  authoring proof, not rendering/shipping certification.

The fixtures certify this bounded scene/resource subset. The 10,000-object parser
limit is not a measured performance promise; arbitrary imported scene inheritance,
extension/custom resource ecosystems, general animation graphs and full-scale
latency remain outside this matrix. External engine toolchains were not upgraded.

Reproduce in a fresh output folder, in this order:

```powershell
python -m unittest discover -s packages/project-system/tests -p test_godot_authoring.py -v
python tools/nec005_godot_proof.py --out target/nec005/my-proof --phase run
python tools/nec005_godot_proof.py --out target/nec005/my-proof --phase reload
python tools/nec005_godot_proof.py --out target/nec005/my-proof --phase play
python tools/nec005_godot_proof.py --out target/nec005/my-proof --phase privilege
```

The `run` phase intentionally leaves a committed fixture transaction for the
fresh `reload` process to recover. The runner creates only a trusted fixture under
`target/nec005`; it does not open arbitrary developer or sealed XP-022 projects.

## Preservation and next handoff

[Evidence](recovery/evidence/nec005-20261016/summary.json) binds source, native proof files,
test commands/logs and seal verification. All 2,140 protected XP-022 files remain
unchanged. Historical NEC receipts are unchanged; NEC-004's live master/roadmap
versions are retained under `target/nec005/entry-documents/`.

No new task or reorder is required. NEC-007/009/010 must consume the explicit
trusted-project and save/close/recapture boundary, instance enrollment, loss review,
exact-write refusals and retained native transaction receipts. They still own
adoption through GDE, merge, coordinated recovery and user-facing synchronization.
No native shipping, runtime-free export or automatic CGS synchronization claim is
added. **Stop before NEC-006.** No commit or push was performed.
