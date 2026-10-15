> Reconstructed historical NEC006 document. Fresh recovery verification pending; historical disposable paths below are not current instructions. See AGENT_PROGRESS.md.

# NEC-006 — Unreal saved native authoring

Date: 2026-10-10. Status: complete within the declared profile; NEC-007 not started.

This task adds an opt-in editor module and callable host APIs against the actual
post-XP-022 working tree. It does not alter the frozen runtime or the existing
Unreal transport/applicator. The certified profile is Windows x64, Unreal
`5.7.4-51494982+++UE5+Release-5.7`, one clean saved persistent map.

## Implementation

- [Editor module](../adapters/unreal/Authoring/XACEAuthoring.uplugin) loads only in
  the editor. Authoring requires explicit project trust; runtime/PIE worlds are
  refused. The fixture command is opt-in and requires its isolated-project marker.
- [Trusted staging](../packages/project-system/unreal_authoring_stage.py) inventories
  descriptor, Content, Config and Plugins with bounded byte/file counts and SHA-256.
  It refuses untrusted execution, stale approval, linked content, nested/existing
  destinations and native C++ project modules. It copies into an independent folder,
  checks both sides and never launches the engine itself. Trusted project/plugin
  code can execute when the caller subsequently opens the copy; copying is not a sandbox.
- [Reader](../adapters/unreal/Authoring/Source/XACEAuthoring/Private/XaceAuthoringReader.cpp)
  explicitly loads the saved map and captures actual persistent actors, relative
  transforms, typed mesh references, native class/label and attachment parents.
  WorldSettings carries scene enrollment; actors carry explicit versioned identity
  tags. Native package persistent GUID and actor GUID locate objects independently
  of labels. Duplicate enrollment blocks capture until an explicit distinct rekey.
  Discovery precedes enrollment. Blueprint instances retain actor identities and
  class/dependency provenance as opaque native behavior; no prefab translation is implied.
- Dependency fingerprints include native package bytes, transitive AssetRegistry
  dependencies and project `.ini` files. Each dependency is synchronously read from
  disk rather than relying on a warm registry. Dirty or drifted sources require
  save/discard and an explicit reload. `DependencyInventory` exposes the package/hash
  inventory. This is explicit capture/full rescan, not a filesystem watcher.
- [Python bridge](../packages/project-system/unreal_authoring.py) uses NEC-002 identity
  association and NEC-003 bounded capture/admission, ownership and loss contracts.
  Unreal centimeters/axes become canonical fixed values. Only relative position,
  rotation, scale and linked static mesh reference are writable. Native label/class
  are native-owned. Structural changes and arbitrary fields are not writable here.
- [Writer](../adapters/unreal/Authoring/Source/XACEAuthoring/Private/XaceAuthoringWriter.cpp)
  validates the exact capture digest and request, backs up the native map, stages
  changes through `UPackage::SavePackage`, reopens the binary stage and checks exact
  values. Temporary autosave semantics retain persistent package identity; memory
  values, loaded path, GUID and clean state are restored before returning approval.
  This avoids Unreal's Save-As GUID regeneration. No binary text patching is used.
- New mesh references and their transitive dependencies are separately hash-bound,
  even when absent from the original map. Approval becomes stale if they change.
  Native publication requires unloading the approved map, rechecks all stamps and
  uses Windows native file replacement with an actual displaced image and a durable
  receipt. Failure recovery restores only an owned after-image; newer files and
  concurrent displaced content remain available for explicit conflict recovery.
  Enrollment uses `FScopedTransaction` and editor Undo/Redo. Published map rollback
  uses the retained native receipt/before-image, not the editor undo stack.

## Verification

The [runner](../tools/nec006_unreal_proof.py) builds the plugin against the installed
engine and runs actual commandlet, independent staged-copy, cold-process bridge and
non-commandlet editor fixtures. Run phases in order: `build`, `run`, `staged`,
`reload`, `interactive`, with `--out target/nec006/<fresh-folder>`.
The editor phase uses D3D11 offscreen rendering; NullRHI crashed in installed editor
startup before the authoring command. Failed diagnostic attempts remain in history.

255 Python tests pass across 14 suites, including 16 new Unreal bridge/staging
cases. All 73 installed-Unreal checks pass: 57 commandlet, 1 trusted-copy,
6 cold-process and 9 real-editor checks. The final seal check confirms all 2,140
protected XP-022 files and historical NEC receipts unchanged. Proofs exercise meaningful binary maps and meshes, saved mesh replacement,
identity collisions/rekey, rename/reparent, native Blueprint opacity and drift,
untrusted/runtime/streaming refusal, approval/dependency checks, fault rollback,
newer-edit preservation, canonical Python interoperability and real editor Undo/Redo.
The PIE refusal case supplies an actual native world with PIE type; it does not
claim a full gameplay Play-session certification.

## Explicit boundaries and remaining roadmap

Unknown classes, native Blueprint/level behavior, additional components and physics
are retained as critical opaque losses and block ordinary schema admission. This
profile does not convert Blueprint graphs, C++, input mappings, animation graphs,
materials, arbitrary geometry, World Partition, streamed levels or split/bulk
packages. These must be explicitly preserved/reviewed or refused; they are not
silently treated as migrated gameplay. The wire profile is bounded canonical ASCII JSON with decimal string numbers.
Only the allowlisted StaticMeshActor fields
have a native writer. Mesh files are referenced/replaced, not reconstructed from CGS.

The staged-copy profile is for trusted content/Blueprint projects and their plugins;
C++ project modules require a separately certified build profile. Package GUIDs are
locators, not permission to match duplicated projects across branches automatically.
Concurrent arbitrary external editors are not locked, and this proof does not certify
power-loss recovery or distributed multi-store publication. Keep transaction backups.
No shipping, broad performance/compatibility or commercial release gate is closed.

No tasks need adding or reordering. NEC-007/009/010 must consume explicit trust,
identity enrollment and loss review; save/reload/unload gates; exact numeric refusals;
replacement-resource stamps; native receipts and conflict-preserving recovery.
C++/partition/graph support stays outside the declared profile unless separately
expanded with proofs. CGS adoption/commit, baseline advancement, automatic continuous
sync and runtime-free export are not supplied by NEC-006. NEC-007 remains unstarted.

## Preservation and evidence

Pre-NEC-006 master/roadmap copies are retained in
`target/nec006/entry-documents/`; the full entry seal check is
`target/nec006/verification-20261009/entry.json`. Final verification lives under
`target/nec006/verification-20261010/`, native evidence under
`target/nec006/native-20261009/`. The folder date records the start of native work.
XP-022 sealed baseline, release binaries and certification evidence remain protected;
REL-01 through REL-05 stay OPEN. No commit or push is performed. See the
[hash-bound evidence receipt](evidence/nec006-unreal-20261010.json).
