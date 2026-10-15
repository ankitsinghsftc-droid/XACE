> Reconstructed historical NEC004 document. Fresh recovery verification pending; original evidence and disposable paths below are historical, not current instructions. See AGENT_PROGRESS.md.

# NEC-004 - Unity editor discovery, capture and staged writes

Completed 2026-10-09 in the local, uncommitted `target/xp016-work` tree.
Certified scope: the shared NEC authoring contracts in the installed Windows
Unity **6000.4.9f1** editor, using real saved scenes and regular prefabs/instances.
NEC-005 has not started. XP-022's engineering seal and REL-01 through REL-05 are
unchanged; this task does not close any external release gate.

## What changed

The new opt-in [Authoring](../adapters/unity/Authoring) folder has its own metadata
and Editor assemblies. It does not modify the frozen adapter/runtime assemblies.

- [XaceAuthoringIdentity](../adapters/unity/Authoring/Runtime/XaceAuthoringIdentity.cs)
  stores namespace, authoring ID, generation, kind and prefab-definition ID on the
  native object. It has no lifecycle callbacks or gameplay behavior.
- [XaceAuthoringBinding](../adapters/unity/Authoring/Runtime/XaceAuthoringBinding.cs)
  stores explicit input/semantic resource declarations. It does not consume input,
  play animations/audio or implement game rules.
- [UnityAuthoringReader](../adapters/unity/Authoring/Editor/UnityAuthoringReader.cs)
  provides saved-content discovery, explicit metadata enrollment, capture, source
  fingerprints, dirty/Play checks and notification invalidation/full rescan.
- [UnityAuthoringWriter](../adapters/unity/Authoring/Editor/UnityAuthoringWriter.cs)
  prepares real native copies, validates saved readback, publishes only the approved
  file set and retains before-images plus a recoverable native transaction receipt.
- [AuthoringJson](../adapters/unity/Authoring/Editor/AuthoringJson.cs) provides the
  bounded, duplicate-key-rejecting string-number wire format and canonical ASCII
  JSON encoding. Native fixed64 conversion refuses unrepresentable float values.
- [unity_authoring.py](../packages/project-system/unity_authoring.py) binds the
  installed reader's output to NEC-002 identities and NEC-003 inspections/snapshots,
  and builds concrete allowlisted write requests from validated snapshots.

These are callable editor/project-system APIs. The default Builder import route
is not rewired and there is no automatic schema mutation or background native
save. Adoption UI/GDE operations, three-way merge, approvals across both stores,
and durable continuous synchronization remain NEC-007 through NEC-010.

## Native operating boundary

The integration operates in an **already open, explicitly trusted Unity project**.
It never launches an imported project to inventory it, copies arbitrary scripts
into a project, or starts Play for discovery. Existing filesystem inventory is
still the first step for an untrusted external project. An already open Unity
project is not a sandbox for its own editor scripts/import callbacks; this work
does not claim to suppress arbitrary user code inside that editor.

To integrate, copy the new Authoring folder into the trusted project's Assets
tree, preserving its assembly directories. The Editor assembly is editor-only;
the two metadata components are inert serialized types. The proof entry points
are explicitly invoked test helpers, not automatic import/session hooks. No
XACE runtime or feedback transport is used by authoring extraction/writing.

`new AuthoringScope(approvedSavedDocuments)` selects existing `.unity`/`.prefab`
files under Assets. Traversal and linked paths are refused. Scenes must already
be open, clean and saved. Dirty prefab stages, persistent prefab components,
resource dependencies and InputManager state are refused. Unknown/builtin
resources without a supported persistent typed reference are not fabricated.

`Discover(scope)` returns `xace.unity_native_discovery.v1`, including persistent
native locators, actual serialized transforms/resources, parent/source locators,
registration status, opaque dependencies and explicit extraction failures. It
works before XACE metadata exists and does not invent IDs, gameplay or defaults.
The installed proof checks an unenrolled object at its real `(12,13,14)` position
and verifies that discovery leaves the saved scene bytes unchanged.

`Attach` is explicit, undoable enrollment of a caller-supplied identity. Failed
validation rolls back the component addition. A scene has a separate metadata
holder, which cannot hide additional components or a child hierarchy. A prefab
definition has its own identity; each placed instance must have distinct instance
metadata and its definition reference. Capture never auto-repairs duplicates.
`ReidentifyDuplicate` requires the exact current native locator/document fingerprint
and an explicitly supplied distinct ID; saving/reassociating the resulting metadata
is a later reviewed identity workflow, not an automatic baseline advance.

## Capture and normalization

`Capture(scope)` emits `xace.unity_authoring_inventory.v1`. The object keys are
authoring IDs; locators combine the asset GUID and Unity GlobalObjectId. Ordinary
and duplicate names are hints, never identity. Scene/prefab/parent references must
close within the selected documents. Lost/foreign/colliding metadata fails closed.
Moving an object between native documents still requires the NEC-002 explicit
locator-rebinding workflow; the reader cannot silently reassign that association.

Unity's persistent-ID API has scene/instance semantics; see the official
[GlobalObjectId reference](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/GlobalObjectId.html).
The implementation and installed save/reopen proofs, rather than that reference
alone, establish the supported pinned-editor behavior here.

Current extraction covers:

- Local transform position/quaternion/scale and explicit hierarchy.
- BoxCollider size/offset/trigger and the existing `world.aabb.v1` profile.
- Persistent MeshFilter mesh, a single renderer material, typed declared
  Animation/Audio binding resources and named saved legacy InputManager actions.
- Native name as a read-only, native-owned field.
- All remaining component serialization retained by Unity, with document-bound
  component fingerprints. Unknown behavior has a **blocking** disposition.

Document fingerprints cover saved document bytes, dependency bytes and `.meta`
files, including InputManager settings. Opaque component hashes use stable native
locators and that dependency fingerprint, not transient editor instance numbers.
Fingerprinting is conservative: an unrelated serialized change in the same
document can invalidate several opaque entries.

The native reader emits decimal strings. `capture(bytes, current_mapping)` in
Python validates persistent metadata associations and invokes NEC-003 with a
pinned Unity reader/materializer policy. Unity Z reflection and quaternion signs
use the shared numeric contract. First adoption has a separate explicit
`prepare_identity_map` candidate API, which never persists or replaces a live map.

Object/project/undo/save/Play notifications invalidate a rescan hint. A rescan
reads the full selected set even if the hint was missed. Saved scene/dependency
fingerprints are checked against the matching editor load/save state; an external
file change cannot silently bind stale loaded values to a newer fingerprint.
The user must refresh/reopen saved content when that state differs. Across Play,
the reader requires saved-scene reopen and excludes gameplay-time edits. Neither
reload-disabled mode nor domain reload grants editor authoring privileges to Play.

## Staged native writer

`write_request(native_inventory, base, target, mapping)` validates NEC snapshots
and emits `xace.unity_authoring_write_request.v1`. The request binds the exact
inventory digest and selected object/field values. It rejects structural changes,
component additions/removals and native-owned name changes. This is a concrete
writer input, not approval to change CGS or a completed reconciliation policy.

`PrepareRequest`/`Prepare` validates the current capture, creates unique native
copies under `Assets/__XaceAuthoringStage/<transaction>/`, uses Unity's own scene
and prefab serialization, reopens the saved copies, and verifies the approved
fields after inverse numeric conversion. Unowned components/properties/overrides
are retained. Canonical values that cannot round-trip through Unity float storage
are refused instead of silently rounded. Gameplay collider writes retain the
frozen unparented, identity-rotation/scale AABB restrictions.

Writer fields are bounded to transform position/rotation/scale, BoxCollider
size/offset/trigger, declared input action and supported Animation/Audio binding
tuple. It does not create/delete/reparent entities, rewrite meshes, translate
scripts/graphs, support arbitrary Vfx materialization, or write arbitrary serialized
properties. Resource references must resolve to their actual persistent native
asset identity/type; the writer does not infer resources from a filename.

Preparation preserves originals and records exact paths, before/staged hashes,
dependency fingerprints, field previews and saved-readback status. `Commit`
requires the prepared receipt digest and rechecks dirty state, source/dependency
and staged bytes before replacing the approved documents. A temporary empty scene
permits safe reload even when an approved document is the last open scene.

Native recovery receipts and before-images are under
`Library/XaceAuthoringTransactions/<id>/`; retain that directory while a write is
unresolved. The task does not promise recovery after deleting Unity's Library
folder. Atomic replacement preserves displaced bytes; bounded retries address
transient Windows sharing failures without a delete-then-write fallback.
`Rollback` restores only matching owned after-images. Newer native edits/dirty
buffers produce `recovery_conflict` and are retained. `Recover` requires the
transaction ID, expected receipt digest and approved document scope; it validates
backup confinement before applying that recovery logic.

This is a native transaction primitive, not the NEC-009 cross-store coordinator.
It does not lock arbitrary external programs or publish a CGS/native baseline,
and no multi-editor crash-certification claim is added. The saved receipt reload,
fault-after-replacement rollback and conflicting-newer-edit paths were exercised
in the installed editor. Cleanup/retention policy and project archive integration
remain with the later coordinator/archive tasks; staged evidence is retained.

## Verified scope and remaining limits

The installed corpus covers real saved scenes, a regular prefab, its instance,
an added child hierarchy, renames/reparenting, duplicate names/metadata, native
Undo, persistent mesh/animation resources, an explicit legacy input declaration,
semantic binding, unowned Light properties/overrides and an unmapped AudioSource.
That unmapped component survives native writing while its behavior remains blocked
from schema adoption. There is no arbitrary MonoBehaviour translation or behavior
inference. New Input System action assets, arbitrary animation-controller graphs,
model prefabs, prefab-variant/nested-prefab coverage and general Unity package
ecosystem compatibility are not certified by this fixture matrix.

The resulting snapshot remains a proposal. Asset registration/readiness, geometry
compilation, adoption through GDE, legacy behavior disablement and Play eligibility
still require their existing/later gates. Godot and Unreal authoring integrations
are not added by this Unity task. Native game builds and runtime-free export are
not part of this task.

## Verification and handoff

- **228 Python tests pass:** 9 new Unity bridge tests plus the 219 shared identity,
  numeric/wire, project, asset, binding, World and edit-router tests from NEC-003.
- **50 installed-Unity checks pass:** 40 discovery/enrollment/capture/staging/
  preservation/recovery checks, 4 cold-reopen/Python-request checks and 6 checks
  across Play with both reload options disabled and both enabled.
- The position/quaternion writer cases are taken from the existing NEC-003 golden
  fixture. C# native JSON bytes match Python canonical encoding. A Python-generated
  request was applied by Unity and re-imported as canonical position
  `(11000000,12000000,-13000000)` with the same mapped native identities.
- Initial compiler, last-open-scene refresh, transient receipt replace and stale
  proof-object-reference failures were corrected; logs of those iterations remain
  under the new task's history directory. A temporary automatic-review usage-limit
  failure prevented one patch; it was later applied through the normal review path.

Reproduce in the authorized worktree:

```powershell
python -m unittest discover -s packages/project-system/tests -p test_unity_authoring.py -v
python tools/nec004_unity_proof.py --out target/nec004/my-proof --phase run
python tools/nec004_unity_proof.py --out target/nec004/my-proof --phase reload
python tools/nec004_unity_proof.py --out target/nec004/my-proof --phase play
```

The runner creates only an isolated trusted fixture under `target/nec004`, requires
the installed pinned editor and retains native files/receipts. It never opens the
sealed XP-022 project or an arbitrary user Unity project.

[Evidence](evidence/nec004-unity-20261009.json) records final source, native artifacts,
test logs and preservation hashes. All 2,140 protected XP-022 files are unchanged;
the only changed frozen source-manifest entry is the permitted live master-plan
addendum. NEC-003's original master/roadmap copies are retained under
`target/nec004/entry-documents/` so its historical receipts remain valid.

No roadmap renumbering or additional task is needed. The concrete handoff to
NEC-007/009/010 is explicit enrollment/discovery, approved writer requests,
retained native receipts, source-reopen refusal and behavior-loss handling.
Those tasks still own the user-facing orchestration and end-to-end continuity
claim. **Stop before NEC-005.** No commit or push was performed.
