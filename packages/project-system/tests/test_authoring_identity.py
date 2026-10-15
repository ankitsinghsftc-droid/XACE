import copy
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
from authoring_identity import (
    Baseline, IdentityDraft, IdentityError, IdentityMap, NativeLocator, ObjectRecord,
    WorldBinding, associate, branch_conflicts, canonical, digest, metadata_for, migrate_v1,
)
from authoring_identity_store import AuthoringIdentityStore, PreparedIdentityRevision, parse
from project_manifest import XaceProjectManifest, save_manifest


def oid(n):
    return f"{n:032x}"


def fixture(engine="godot"):
    mapping = IdentityMap("fixture-project", oid(100), oid(200), engine)
    draft = IdentityDraft(mapping)
    for n, kind, scene, prefab, parent in [
        (1, "scene", None, None, None),
        (2, "prefab_definition", None, None, None),
        (3, "prefab_instance", oid(1), oid(2), None),
        (4, "object", oid(1), None, oid(3)),
        (5, "object", oid(1), None, None),
    ]:
        draft.add(ObjectRecord(oid(n), kind, NativeLocator(engine, "document-guid", f"native-{n}"),
                               scene, prefab, parent, "Same name", "scene/same-name", provenance="fixture:original"))
    return draft.snapshot()


class ContractTests(unittest.TestCase):
    def test_all_engines_persist_identity_not_duplicate_names(self):
        for engine in ("unity", "unreal", "godot"):
            mapping = fixture(engine)
            encoded = canonical(mapping.to_dict())
            self.assertEqual(canonical(IdentityMap.from_dict(json.loads(encoded)).to_dict()), encoded)
            observations = [(row.locator, metadata_for(mapping, key)) for key, row in mapping.objects.items()]
            self.assertEqual(associate(mapping, observations), list(mapping.objects))
            self.assertEqual(len({r.display_name for r in mapping.objects.values()}), 1)
            self.assertEqual(len(set(associate(mapping, observations))), 5)

    def test_rename_move_reparent_property_corpus(self):
        rng = random.Random(27002)
        for engine in ("unity", "unreal", "godot"):
            original = fixture(engine)
            draft = IdentityDraft(original)
            for step in range(100):
                draft.update(oid(4), display_name=f"name-{rng.randrange(10000)}",
                             path_hint=f"renamed/scene-{step}/object", parent_id=oid(5) if step % 2 else oid(3),
                             set_parent=True)
                current = IdentityMap.from_dict(json.loads(canonical(draft.snapshot().to_dict())))
                self.assertEqual(set(current.objects), set(original.objects))
                self.assertEqual(current.objects[oid(4)].locator, original.objects[oid(4)].locator)
                self.assertEqual(associate(current, [(current.objects[oid(4)].locator,
                                                     metadata_for(current, oid(4)))]), [oid(4)])
            self.assertEqual(draft.snapshot().objects[oid(4)].generation, 101)
            self.assertEqual(original.objects[oid(4)].generation, 1)

    def test_duplicate_preserves_definition_but_not_world_binding(self):
        mapping = fixture()
        mapping.objects[oid(3)].world_binding = WorldBinding("world-3", "actor", 0)
        draft = IdentityDraft(mapping)
        draft.duplicate(oid(3), oid(6), NativeLocator("godot", "document-guid", "native-6"), "duplicate:reviewed")
        copy_record = draft.snapshot().objects[oid(6)]
        self.assertEqual(copy_record.prefab_id, oid(2))
        self.assertEqual(copy_record.duplicate_of, oid(3))
        self.assertIsNone(copy_record.world_binding)
        with self.assertRaises(IdentityError):
            draft.duplicate(oid(3), oid(3), NativeLocator("godot", "doc", "new"), "invalid")

    def test_colliding_copy_paste_and_lost_metadata_refuse_whole_batch(self):
        mapping = fixture()
        row = mapping.objects[oid(4)]
        metadata = metadata_for(mapping, oid(4))
        for observations in [
            [(row.locator, None)],
            [(row.locator, metadata), (NativeLocator("godot", "doc", "copy"), metadata)],
            [(NativeLocator("godot", "doc", "different"), metadata)],
            [(row.locator, dict(metadata, namespace_id=oid(999)))],
            [(row.locator, dict(metadata, generation=0))],
            [(row.locator, dict(metadata, generation=True))],
        ]:
            with self.subTest(observations=observations), self.assertRaises(IdentityError):
                associate(mapping, observations)
        self.assertEqual(mapping.objects[oid(4)], row)

    def test_delete_undo_reserves_identity_and_rejects_dependent_parent_delete(self):
        draft = IdentityDraft(fixture())
        before = canonical(draft.snapshot().to_dict())
        with self.assertRaises(IdentityError):
            draft.tombstone([oid(3)])
        self.assertEqual(canonical(draft.snapshot().to_dict()), before)
        draft.tombstone([oid(3), oid(4)])
        with self.assertRaises(IdentityError):
            draft.add(ObjectRecord(oid(4), "object", NativeLocator("godot", "doc", "reused"), provenance="bad"))
        with self.assertRaises(IdentityError):
            metadata_for(draft.snapshot(), oid(4))
        draft.tombstone([oid(3), oid(4)], deleted=False)
        row = draft.snapshot().objects[oid(4)]
        self.assertFalse(row.tombstone)
        self.assertEqual(row.generation, 3)
        self.assertEqual(row.locator, fixture().objects[oid(4)].locator)

    def test_invalid_cycles_references_and_world_collision_leave_draft_unchanged(self):
        draft = IdentityDraft(fixture())
        before = canonical(draft.snapshot().to_dict())
        with self.assertRaises(IdentityError):
            draft.update(oid(3), parent_id=oid(4), set_parent=True)
        self.assertEqual(canonical(draft.snapshot().to_dict()), before)
        for change in ("scene", "prefab", "world", "locator"):
            data = fixture()
            if change == "scene": data.objects[oid(4)].scene_id = oid(99)
            if change == "prefab": data.objects[oid(3)].prefab_id = oid(1)
            if change == "world":
                for n in (4, 5): data.objects[oid(n)].world_binding = WorldBinding("same-world", "actor", 0)
            if change == "locator": data.objects[oid(4)].locator = data.objects[oid(5)].locator
            with self.subTest(change=change), self.assertRaises(IdentityError):
                data.validate()

    def test_noop_order_and_snapshot_isolation(self):
        mapping = fixture()
        reordered = copy.deepcopy(mapping)
        reordered.objects = dict(reversed(list(reordered.objects.items())))
        self.assertEqual(digest(mapping.to_dict()), digest(reordered.to_dict()))
        draft = IdentityDraft(mapping)
        draft.update(oid(4), display_name="Same name")
        leaked = draft.snapshot()
        leaked.objects.clear()
        self.assertEqual(draft.snapshot().objects[oid(4)].generation, 1)

    def test_clone_branch_conflicts_are_explicit_and_never_merge(self):
        left = fixture()
        with self.assertRaises(IdentityError):
            branch_conflicts(left, copy.deepcopy(left))
        draft = IdentityDraft(left)
        draft.fork(oid(201))
        self.assertEqual(branch_conflicts(left, draft.snapshot()), [])
        draft.update(oid(4), display_name="Independent branch edit")
        self.assertEqual(branch_conflicts(left, draft.snapshot()), [oid(4)])
        right = draft.snapshot()
        right.namespace_id = oid(777)
        with self.assertRaises(IdentityError): branch_conflicts(left, right)

    def test_explicit_legacy_migration_keeps_all_ids_and_native_locators(self):
        path = Path(__file__).parent / "fixtures/authoring_identity_v1.json"
        raw = path.read_bytes()
        data = json.loads(raw)
        mapping = migrate_v1(data)
        self.assertEqual(set(mapping.objects), set(data["objects"]))
        self.assertEqual(mapping.namespace_id, data["namespace_id"])
        for key, row in mapping.objects.items():
            self.assertEqual(row.locator.object_id, data["objects"][key]["locator"]["object_id"])
            self.assertEqual(row.generation, 1)
            self.assertFalse(row.tombstone)
        self.assertEqual(path.read_bytes(), raw)
        with self.assertRaises(IdentityError): IdentityMap.from_dict(data)
        data["objects"][next(iter(data["objects"]))]["authoring_id"] = "old-name-only"
        with self.assertRaises(IdentityError): migrate_v1(data)

    def test_branch_world_binding_collision_requires_manual_resolution(self):
        left = fixture()
        left.objects[oid(4)].world_binding = WorldBinding('world.shared', 'actor.shared', 0)
        right = fixture()
        right.branch_id = oid(201)
        del right.objects[oid(4)]
        right.objects[oid(5)].world_binding = WorldBinding('world.shared', 'actor.shared', 0)
        self.assertEqual(branch_conflicts(left, right), [oid(4), oid(5)])

    def test_malformed_corpus_rejects_unknown_fields_versions_and_scalars(self):
        for field, value in [("namespace_id", "name"), ("branch_id", 42), ("schema", "unknown"), ("objects", []), ("engine", [])]:
            data = fixture().to_dict(); data[field] = value
            with self.subTest(field=field), self.assertRaises(IdentityError): IdentityMap.from_dict(data)
        for raw in [b'{"a":1,"a":2}', b'{"x":NaN}', b'[]', b'{bad']:
            with self.assertRaises(IdentityError): parse(raw)
        data = fixture().to_dict(); data["objects"][oid(4)]["generation"] = True
        with self.assertRaises(IdentityError): IdentityMap.from_dict(data)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        save_manifest(self.root, XaceProjectManifest("fixture-project", "Fixture", "godot", "blank_3d"))
        (self.root / "game.cgs.json").write_bytes(b'{"untouched_gameplay":true}')
        self.original = {name: (self.root / name).read_bytes() for name in ("xace.project.json", "game.cgs.json")}
        self.store = AuthoringIdentityStore(self.root)
        initial = IdentityMap("fixture-project", oid(100), oid(200), "godot")
        prepared = self.store.prepare(initial, expected_revision=None, journal_ref="init:approved", operation="initialize")
        self.first = self.store.commit(prepared)
        self.current = self.store.commit(self.store.prepare(fixture(), expected_revision=self.first, journal_ref="adopt:approved"))

    def tearDown(self):
        for name, raw in self.original.items(): self.assertEqual((self.root / name).read_bytes(), raw)
        self.tmp.cleanup()

    def proposal(self, name="new name"):
        draft = IdentityDraft(self.store.load().mapping)
        draft.update(oid(4), display_name=name)
        return self.store.prepare(draft.snapshot(), expected_revision=self.current, journal_ref="edit:approved")

    def test_prepare_is_read_only_and_commit_reopens_with_idempotent_retry(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        prepared = self.proposal()
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(self.store.commit(prepared), self.store.commit(prepared))
        loaded = AuthoringIdentityStore(self.root).load()
        self.assertEqual(loaded.mapping.objects[oid(4)].display_name, "new name")
        self.assertEqual(loaded.mapping.objects[oid(4)].authoring_id, oid(4))
        self.assertEqual(self.store.history(self.current).mapping.objects[oid(4)].display_name, "Same name")

    def test_failed_head_write_keeps_previous_map_and_retry_is_safe(self):
        prepared = self.proposal()
        from authoring_identity_store import atomic_write_text_file
        def fail_head(path, text):
            if path.name == 'head.json': raise OSError("simulated full disk/locked head")
            atomic_write_text_file(path, text)
        with patch('authoring_identity_store.atomic_write_text_file', side_effect=fail_head):
            with self.assertRaises(OSError): self.store.commit(prepared)
        self.assertEqual(self.store.load().revision, self.current)
        self.assertEqual(self.store.commit(prepared), prepared.revision)

    def test_changed_proposal_and_stale_writer_fail_without_overwriting(self):
        a, b = self.proposal("A"), self.proposal("B")
        with self.assertRaises(IdentityError): self.store.commit(replace(a, payload=a.payload + b' '))
        self.store.commit(a)
        with self.assertRaises(IdentityError): self.store.commit(b)
        self.assertEqual(self.store.load().revision, a.revision)

    def test_lost_corrupt_head_requires_explicit_pinned_restore(self):
        path = self.root / '.xace/authoring/head.json'
        path.write_bytes(b'corrupt')
        with self.assertRaises(IdentityError): self.store.load()
        with self.assertRaises(IdentityError):
            self.store.recover_head(self.current, expected_head_digest='0'*64, namespace_id=oid(100), branch_id=oid(200))
        self.store.recover_head(self.current, expected_head_digest=hashlib.sha256(b'corrupt').hexdigest(),
                                namespace_id=oid(100), branch_id=oid(200))
        self.assertEqual(self.store.load().revision, self.current)
        with self.assertRaises(IdentityError):
            self.store.recover_head(self.first, expected_head_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
                                    namespace_id=oid(100), branch_id=oid(200))
        path.unlink()
        with self.assertRaises(IdentityError):
            self.store.prepare(IdentityMap('fixture-project', oid(100), oid(200), 'godot'),
                               expected_revision=None, journal_ref='lost', operation='initialize')
        self.store.recover_head(self.current, expected_head_digest=None, namespace_id=oid(100), branch_id=oid(200))
        self.assertEqual(set(self.store.load().mapping.objects), set(fixture().objects))

    def test_corrupt_revision_never_silently_uses_backup(self):
        path = self.root / f'.xace/authoring/revisions/{self.current}.json'
        path.write_bytes(b'{}')
        with self.assertRaises(IdentityError): self.store.load()
        with self.assertRaises(IdentityError):
            self.store.recover_head(self.current, expected_head_digest=hashlib.sha256((self.root/'.xace/authoring/head.json').read_bytes()).hexdigest(), namespace_id=oid(100), branch_id=oid(200))

    def test_baseline_receipts_bind_mapping_and_journal_but_edits_keep_old_base(self):
        draft = IdentityDraft(self.store.load().mapping)
        baseline = Baseline('a'*64, 'b'*64, draft.snapshot().mapping_digest(), 'baseline:approved', 'c'*64, 'd'*64)
        draft.set_baseline(baseline)
        with self.assertRaises(IdentityError):
            self.store.prepare(draft.snapshot(), expected_revision=self.current, journal_ref='wrong-journal')
        prepared = self.store.prepare(draft.snapshot(), expected_revision=self.current, journal_ref='baseline:approved')
        self.current = self.store.commit(prepared)
        self.store.commit(self.proposal())
        loaded = self.store.load().mapping
        self.assertEqual(loaded.baseline, baseline)
        self.assertNotEqual(loaded.mapping_digest(), baseline.mapping_digest)

    def test_direct_reassignment_removal_and_generation_rewind_refused(self):
        for change in ('namespace', 'remove', 'kind', 'generation', 'provenance'):
            mapping = self.store.load().mapping
            if change == 'namespace': mapping.namespace_id = oid(999)
            if change == 'remove': del mapping.objects[oid(5)]
            if change == 'kind': mapping.objects[oid(5)].kind = 'scene'
            if change == 'generation': mapping.objects[oid(5)].display_name = 'changed'
            if change == 'provenance': mapping.objects[oid(5)].provenance = 'reassigned'
            with self.subTest(change=change), self.assertRaises(IdentityError):
                self.store.prepare(mapping, expected_revision=self.current, journal_ref='invalid')

    def test_explicit_fork_retains_objects_without_reassigning(self):
        draft = IdentityDraft(self.store.load().mapping); draft.fork(oid(201))
        with self.assertRaises(IdentityError):
            self.store.prepare(draft.snapshot(), expected_revision=self.current, journal_ref='fork')
        prepared = self.store.prepare(draft.snapshot(), expected_revision=self.current, journal_ref='fork', operation='fork')
        self.store.commit(prepared)
        self.assertEqual(self.store.load().mapping.objects, fixture().objects)

    def test_process_exit_before_publication_preserves_previous_map(self):
        prepared = self.proposal()
        payload_file = self.root/'prepared.json'
        payload_file.write_bytes(prepared.payload)
        code = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import authoring_identity_store as s
root=Path(sys.argv[2]); raw=(root/'prepared.json').read_bytes()
real=s.atomic_write_text_file
def crash(path,text):
    if path.name=='head.json': os._exit(23)
    real(path,text)
s.atomic_write_text_file=crash
s.AuthoringIdentityStore(root).commit(s.PreparedIdentityRevision(sys.argv[3],sys.argv[4],raw))
'''
        result = subprocess.run([sys.executable, '-c', code, str(PACKAGE), str(self.root),
                                 prepared.expected_revision, prepared.revision], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.store.load().revision, self.current)
        self.assertEqual(self.store.commit(prepared), prepared.revision)

    def test_two_process_writers_cannot_publish_from_the_same_parent(self):
        a, b = self.proposal('branch A'), self.proposal('branch B')
        for name, prepared in [('a.json', a), ('b.json', b)]:
            (self.root/name).write_bytes(prepared.payload)
        code = '''import sys,time,json,hashlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import authoring_identity_store as s
root=Path(sys.argv[2]); raw=(root/sys.argv[3]).read_bytes()
class SlowStore(s.AuthoringIdentityStore):
    def _head(self):
        value=super()._head(); time.sleep(.2); return value
try:
    SlowStore(root).commit(s.PreparedIdentityRevision(json.loads(raw)['parent_revision'],hashlib.sha256(raw).hexdigest(),raw))
    print('accepted')
except s.IdentityError:
    print('stale')
'''
        def run(name):
            return subprocess.run([sys.executable, '-c', code, str(PACKAGE), str(self.root), name],
                                  capture_output=True, text=True, timeout=30)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ['a.json', 'b.json']))
        self.assertEqual([result.returncode for result in results], [0, 0], [r.stderr for r in results])
        self.assertEqual(sorted(result.stdout.strip() for result in results), ['accepted', 'stale'])
        self.assertIn(self.store.load().revision, (a.revision, b.revision))

    def test_migrated_retained_mapping_persists_without_id_changes(self):
        root = self.root/'legacy-import'
        save_manifest(root, XaceProjectManifest('fixture-project', 'Legacy fixture', 'godot', 'blank_3d'))
        raw = json.loads((Path(__file__).parent/'fixtures/authoring_identity_v1.json').read_text())
        migrated = migrate_v1(raw)
        store = AuthoringIdentityStore(root)
        prepared = store.prepare(migrated, expected_revision=None,
                                 journal_ref='migration:' + digest(raw), operation='migration')
        store.commit(prepared)
        restored = AuthoringIdentityStore(root).load().mapping
        self.assertEqual(restored.to_dict(), migrated.to_dict())
        self.assertEqual(set(restored.objects), set(raw['objects']))

    def test_initialization_failure_does_not_regenerate_namespace_on_retry(self):
        root = self.root/'new'
        save_manifest(root, XaceProjectManifest('fixture-project', 'New fixture', 'godot', 'blank_3d'))
        store = AuthoringIdentityStore(root)
        mapping = IdentityMap('fixture-project', oid(123), oid(234), 'godot')
        prepared = store.prepare(mapping, expected_revision=None, journal_ref='initialize', operation='initialize')
        from authoring_identity_store import atomic_write_text_file
        def fail(path, text):
            if path.name == 'head.json': raise OSError('interrupted initialization')
            atomic_write_text_file(path, text)
        with patch('authoring_identity_store.atomic_write_text_file', side_effect=fail):
            with self.assertRaises(OSError): store.commit(prepared)
        with self.assertRaises(IdentityError):
            store.prepare(mapping, expected_revision=None, journal_ref='different initialization', operation='initialize')
        store.commit(prepared)
        self.assertEqual(store.load().mapping.namespace_id, oid(123))

    def test_foreign_project_and_oversized_metadata_refuse_without_changes(self):
        mapping = fixture(); mapping.project_id = 'different-project'
        with self.assertRaises(IdentityError):
            self.store.prepare(mapping, expected_revision=self.current, journal_ref='foreign')
        with patch('authoring_identity_store.MAX_BYTES', 16):
            with self.assertRaises(IdentityError): self.store.load()
        self.assertEqual(self.store.load().revision, self.current)


if __name__ == '__main__':
    unittest.main()
