> Reconstructed historical NEC002 completion document. Fresh recovery acceptance passes91 tests (24 focused,67 regression); evidence is in recovery/evidence/nec002-20261015/summary.json. Old paths/test receipts are provenance only. See AGENT_PROGRESS.md.

# NEC-002: canonical authoring identities and baselines

Status: complete for the project-side contract and persistence scope, 2026-10-08.
NEC-003 is not started. No runtime or native adapter source changed.

Implementation:

- [authoring_identity.py](../packages/project-system/authoring_identity.py): typed
  project namespace, branch, object, native locator, World binding and baseline
  records; validation; copy-based drafts; metadata association; explicit migration
  and branch conflict detection.
- [authoring_identity_store.py](../packages/project-system/authoring_identity_store.py):
  read-only preparation, content-addressed history, cross-process write lock,
  compare-and-swap publication and explicit recovery.
- [tests](../packages/project-system/tests/test_authoring_identity.py) and
  [retained-map fixture](../packages/project-system/tests/fixtures/authoring_identity_v1.json).
- [closeout evidence](recovery/evidence/nec002-20261015/summary.json).

## Boundary and integration

The store is an opt-in project-system API. It reads the existing
`xace.project.json` project ID and engine as its project boundary; it does not
change that manifest, CGS, compiled World, gameplay/package hashes, runtime entity
allocation, native project files or engine capability declarations. Existing
project creation/open/import remains compatible and does not assign adoption IDs
without an explicit metadata operation. No Builder endpoint or native event
watcher is added by this task.

The following durable files belong to the developer project:

```text
.xace/authoring/head.json                  one committed revision reference
.xace/authoring/revisions/<sha256>.json     immutable mapping/baseline history
.xace/authoring/write.lock                 local OS lock; never delete while in use
```

Version-control/archive the head and revisions together. Exclude the local lock,
temporary `.xace_tmp_*` files and `.xace_bak_*` convenience backups. Backups are
never automatically preferred over a valid head. Keep journal/snapshot artifacts
referenced by baselines when the later transaction/archive integrations supply
them. A mapping history by itself is not a complete project archive.

The current mapping format is `xace.authoring_identity.v2`, revision envelope is
`xace.authoring_revision.v1`, head is `xace.authoring_head.v1`, and emitted native
identity metadata is `xace.native_identity.v1`. Canonical JSON sorts keys, rejects
nonfinite values and duplicate parser keys, and binds exact bytes to SHA-256.
Bounds are 10,000 mapping records including tombstones and 16 MiB per metadata
file. These are admission bounds, not a measured native-authoring scale claim.

## Identity and lifecycle contract

`namespace_id`, `branch_id` and `authoring_id` are opaque 128-bit lowercase hex
values. `new_id()` is an explicit authoring-time UUID allocation helper; loading,
association, migration and recovery never call it. Authoring IDs do not become
runtime EntityIDs, and no native locator enters CGS or gameplay predicates.
The project manifest's human-derived project ID alone is not treated as globally
unique; the persisted namespace distinguishes independent native projects.

Each object contains:

- Kind: scene, prefab definition, prefab instance or object. An instance names its
  definition explicitly; its canonical identity remains distinct from that definition.
- Native locator: engine plus persistent document/object keys. These are opaque
  keys supplied by a trusted future editor reader, not paths/display names/array
  indices. This layer cannot certify that a caller chose a true engine-persistent key.
- Scene and parent references, optional World object/actor/instance binding,
  mutable display-name/path hints, generation, tombstone and immutable provenance.
- Optional duplication provenance pointing to the original canonical object.

Rename, file-path movement and valid reparenting preserve IDs. A reviewed persistent
locator change uses the same canonical ID and a new generation. `IdentityDraft.update`
supports those common changes; callers can stage a validated full mapping for a
multi-object scene move. Cross-scene parents, cycles and dangling references refuse
the whole candidate. Helpers work on copies and expose independent snapshots.

Duplication requires a new ID and native locator, records its source, keeps the
prefab-definition relationship and clears authoritative World binding. Duplicate
names are harmless; duplicate attached canonical metadata or native locators are
not. World-object and actor/instance associations must also be unambiguous.

Delete retains the record and reserves its identity/locator/binding as a tombstone.
Dependent objects must be deleted in the same batch or otherwise validly reassigned.
Undo restores the same authored object with a later generation; it does not reuse
a destroyed runtime EntityID. Missing objects cannot silently disappear from a
committed mapping. Generation rewind, silent kind/provenance reassignment and
namespace replacement are refused.

## Native metadata attachment plan

`metadata_for(mapping, id)` emits exactly the namespace, authoring ID, kind and
generation in a versioned envelope. `associate` validates the entire supplied
observation batch against those fields and the persistent locator. Missing,
unknown, foreign, stale or colliding metadata blocks association. It never matches
by display name/path and never silently repairs metadata.

NEC-004/005/006 must attach this envelope through their verified native serializers:

- Unity: distinct metadata on the selected authored object/instance and separately
  on definitions; obtain persistent asset/object keys from the pinned editor API.
- Godot: persisted per-node identity metadata plus distinct scene/resource identity;
  node paths alone cannot identify authored nodes.
- Unreal: serialized identity on selected actors/instances plus separate asset/
  definition identity; use native asset/map serialization, never text-patch binary maps.

These are attachment requirements, not implemented editor API claims. Each writer
must stage the old/new envelope and expected native source fingerprint, preserve
unowned properties, save and re-read before publishing a new shared baseline.
Renames that advance a record generation require the corresponding attachment
update; an old generation remains visibly stale until resolved. Play-mode mirrors
are not attachment targets. Native save/undo and multi-editor crash recovery remain
NEC-004–010 work, outside this sidecar-only commit.

## Baselines, branches and migration

`Baseline` stores CGS digest, native snapshot digest, mapping digest, transaction
journal reference and canonical/native receipt digests. A changed baseline must
describe the exact current mapping and commit journal. Subsequent object edits
retain the old baseline for a future base/XACE/engine comparison. Receipt/snapshot
digests are references supplied by the trusted caller: NEC-002 checks their shape
and binding, not their native-save authenticity or the referenced content. NEC-003
owns snapshot content, NEC-008 owns comparison, NEC-009/010 own verified save receipts.

`IdentityDraft.fork` changes branch ID explicitly while preserving object IDs and
baseline; the store requires operation `fork` and rejects mixed fork/edit commits.
`branch_conflicts` refuses foreign projects/namespaces or an unresolved same-branch
clone and reports differing object, native-locator and World-binding associations.
It does not perform an automatic merge. A caller must use this check when bringing
two branch/clone maps together; the local store cannot discover unknown copies on
other machines. Independently cloned games require an explicit identity/namespace
resolution, not hidden regeneration.

`migrate_v1` explicitly converts the documented retained-map compatibility format
to v2 by adding generation one and active state. Namespace, branch, canonical IDs,
locators, relationships, provenance and World binding are preserved. It refuses
unknown fields/versions, absent stable IDs and unsupported legacy baseline data.
The v1 fixture is a compatibility corpus introduced in NEC-002; XP-022 did not
previously emit these native mappings. Older manual-migration name/default previews
are not treated as authoritative identity maps. Loading does not migrate on its own.
An approved migrated map can initialize a store with operation `migration`, retaining
the source digest in the journal reference and the original file in project history.

## Commit and recovery

1. `prepare` reads the existing head and project, checks the expected revision,
   validates the transition and returns immutable prepared bytes/digest. It writes
   no project or native files. First initialization requires explicit namespace/
   branch selection and an empty map; a lost head with retained history blocks
   initialization instead of regenerating identities.
2. `commit` takes the platform file lock and repeats project, parent and transition
   validation. It flushes the immutable revision, then publishes the head through
   the existing project-system fsync/atomic-replace primitive. A competing writer
   from the same parent is refused. Identical retries verify bytes and return the
   committed identity.
3. Failure before head publication leaves the previous map readable; a staged
   revision may remain for identical retry. No cleanup deletes retained history.
   Crash after publication is resolved by reading/verifying the head and retrying
   idempotently, not replaying metadata allocation.
4. A missing/corrupt head or revision fails closed. `recover_head` requires the
   observed damaged-head hash (or explicit absence), a selected trusted retained
   revision, namespace and branch. It refuses to roll back a valid head. Valid
   authored undo uses a new edit/tombstone generation rather than pointer rollback.

A wholly lost store must be restored from version control/archive and surviving
native metadata; this local library has no external registry that could recover
unknown IDs. Explicit initialization is not proof of recovery. The guarantees
tested here are local Windows filesystem/process-interruption behavior; no claim
of network-filesystem locking, arbitrary disk-controller power-loss atomicity or
cross-editor distributed transactions is made.

## Verification and checkpoint

The 24 focused tests include 300 rename/move/reparent round trips across three
engine labels, colliding metadata, delete/undo, independent snapshots, same-branch
clone refusal, fork conflicts, v1 migration/reopen, stale writers, baseline binding,
interrupted initialization, invalid JSON/oversized input, explicit restore, a real
child-process exit before publication and two real competing writer processes.
They do not launch native editors. Existing project/Player/authoring suites provide
regression coverage; exact results and commands are in the evidence record.

XP-022 sealed artifacts and detailed release evidence remain untouched. NEC-001
evidence is retained unchanged; its pre-NEC-002 master/roadmap bytes are copied to
`target/nec002/entry-documents/` and match the original NEC-001 receipt. Changes to
the live master/roadmap are new progress, not a rewrite of old evidence.

NEC-002 requires no further roadmap expansion. NEC-003 should consume this mapping
contract and baseline references, define normalized snapshot/delta/loss records,
and retain the distinction between authored IDs and runtime allocation. Stop before
NEC-003 until explicitly instructed.
