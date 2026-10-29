import copy
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
sys.path.insert(0, str(PACKAGE))
from authoring_identity import IdentityError, IdentityMap, NativeLocator, ObjectRecord, canonical, digest
from native_authoring_values import integer, normalize
from native_authoring_contract import (SCHEMA, AuthoringPolicy, FieldPolicy, Snapshot, apply_delta,
                                       core_fields, inspect_capture, load_snapshot, make_delta,
                                       parse, writable_fields)


class TextValidationBoundaryTests(unittest.TestCase):
    def test_all_surrogates_refused_and_unicode_scalar_boundaries_accepted(self):
        from native_authoring_contract import bounded
        for code in range(0xD800,0xE000):
            with self.assertRaises(IdentityError):bounded({'value':'prefix'+chr(code)+'suffix'})
        for value in ['ASCII', '\u0000', '\u001f', '\u007f', '\u0080', '\ud7ff', '\ue000', '\uffff', '\U00010000', '\U0010ffff', 'x'*4096]:
            bounded({'value':value})
        with self.assertRaises(IdentityError):bounded({'value':'x'*4097})

    def test_identity_token_controls_and_size_contract_unchanged(self):
        from authoring_identity import token
        for code in range(32):
            with self.assertRaises(IdentityError):token('prefix'+chr(code)+'suffix','test')
        for value in [' ', '\u007f', '\u0080', '\ud7ff', '\ue000', '\U0010ffff', 'x'*256]:
            token(value,'test')
        for value in ['', 'x'*257, None, 42, True]:
            with self.assertRaises(IdentityError):token(value,'test')


def oid(n):
    return f"{n:032x}"


def vec(x="0", y="0", z="0"):
    return dict(x=x, y=y, z=z)


def fixture(engine="godot", count=3):
    mapping = IdentityMap("contract-test", oid(10001), oid(10002), engine)
    for n in range(1, count + 1):
        mapping.objects[oid(n)] = ObjectRecord(oid(n), "scene" if n == 1 else "object",
            NativeLocator(engine, "persistent-document", f"object-{n}"),
            scene_id=None if n == 1 else oid(1), provenance="fixture")
    policy = AuthoringPolicy(engine, "pinned-test-version", "reader.v1", "writer.v1", core_fields())
    capture = dict(schema=SCHEMA, project_id=mapping.project_id, namespace_id=mapping.namespace_id, branch_id=mapping.branch_id,
        mapping_digest=mapping.mapping_digest(), source=dict(engine=engine, engine_version=policy.engine_version,
        reader_version=policy.reader_version, materializer_version=policy.materializer_version,
        documents=[dict(id="persistent-document", before="a"*64, after="a"*64, dirty=False)], play_mode=False),
        scope=sorted(mapping.objects), objects={k:dict(generation="1", deleted=False, parent_id=None,
        fields={}, dependencies=[], opaque=[]) for k in mapping.objects})
    return mapping, policy, capture


def add_geometry(capture, key=oid(2)):
    capture["objects"][key]["fields"].update({"transform.position":vec(),
        "transform.rotation":dict(vec(), w="1"), "transform.scale":vec("1","1","1"),
        "collision.size":vec("2","2","2"), "collision.offset":vec(),
        "collision.shape":"BOX", "collision.profile":"world.aabb.v1", "collision.trigger":False})


class NumericTests(unittest.TestCase):
    def test_independent_javascript_golden_json_and_digest(self):
        path = PACKAGE / "tests/fixtures/native_authoring_golden.json"
        corpus = json.loads(path.read_text())
        outputs = []
        for row in corpus:
            with self.subTest(row=row):
                if row.get("reject"):
                    with self.assertRaises(ValueError):
                        normalize(row["engine"], row["kind"], row["value"])
                    outputs.append(dict(rejected=True))
                else:
                    value, losses = normalize(row["engine"], row["kind"], row["value"])
                    self.assertEqual((value, losses), (row["expected"], row["losses"]))
                    outputs.append(dict(value=value, losses=losses))
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for NEC-003 cross-language proof")
        result = subprocess.run([node, str(ROOT / "tools/nec003_golden_check.mjs"), str(path)],
                                capture_output=True, text=True, timeout=30, check=True)
        actual = json.loads(result.stdout)
        self.assertEqual(actual["outputs"], outputs)
        self.assertEqual(actual["sha256"], digest(outputs))
        self.assertEqual(actual["cases"], 30)

    def test_typed_assets_and_bindings_reuse_playback_rules(self):
        asset = dict(asset_id="run_clip", asset_type="ANIMATION_CLIP", status="PLACEHOLDER", resolved_path=None)
        binding = dict(binding_id="run", event_name="player.run", playback_kind="Animation", asset=asset)
        self.assertEqual(normalize("godot", "binding", binding), (binding, []))
        for updates in [dict(asset_type="MESH"), dict(status="UNRESOLVED"), dict(status="LINKED"),
                        dict(resolved_path="unapproved/path")]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                normalize("godot", "binding", dict(binding, asset=dict(asset, **updates)))
        with self.assertRaises(ValueError):
            normalize("godot", "asset", "run_clip")

    def test_cross_language_full_snapshot_canonical_unicode_and_int64(self):
        mapping, policy, capture = fixture()
        policy.fields.update({"custom.label":FieldPolicy("text",owner="native"),
                              "custom.counter":FieldPolicy("int64")})
        capture["objects"][oid(2)]["fields"] = {"custom.label":"na\u00efve \U0001f680 \u007f", "custom.counter":"9007199254740993"}
        snapshot = inspect_capture(capture,mapping,policy).admit()
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"snapshot.json"; path.write_bytes(snapshot.payload)
            result = subprocess.run([shutil.which("node"),str(ROOT/"tools/nec003_golden_check.mjs"),
                str(PACKAGE/"tests/fixtures/native_authoring_golden.json"),str(path)],
                capture_output=True,text=True,timeout=30,check=True)
            self.assertEqual(json.loads(result.stdout)["snapshot_sha256"],snapshot.sha256)

    def test_large_integer_never_coerces_number_bool_or_noncanonical_text(self):
        for value in [1, True, 1.0, "-0", "00", "+1", "1.0", "1e3", "9"*1000]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                integer(value)

    def test_normal_is_not_position_and_size_is_not_signed_direction(self):
        self.assertEqual(normalize("unreal", "normal", vec("1"))[0], vec("0","0","-1000000"))
        self.assertEqual(normalize("unreal", "size", vec("100","200","300"))[0],
                         vec("2000000","3000000","1000000"))


class SnapshotTests(unittest.TestCase):
    def test_roundtrip_all_engines_and_no_input_or_baseline_mutation(self):
        for engine in ("unity", "unreal", "godot"):
            mapping, policy, capture = fixture(engine)
            original = canonical(capture), canonical(mapping.to_dict())
            snapshot = inspect_capture(capture, mapping, policy).admit()
            self.assertEqual(load_snapshot(snapshot.payload, mapping, policy), snapshot)
            self.assertEqual((canonical(capture), canonical(mapping.to_dict())), original)

    def test_geometry_world_profile_boundary(self):
        mapping, policy, capture = fixture()
        add_geometry(capture)
        self.assertEqual(inspect_capture(capture, mapping, policy).losses, [])
        for path, value in [("collision.shape","MESH"), ("collision.profile","terrain.v1"),
                            ("transform.scale",vec("2","1","1")),
                            ("transform.rotation",dict(vec("1"),w="0")),
                            ("collision.size",vec("0.000001","2","2")),
                            ("transform.position",vec("8192"))]:
            changed = copy.deepcopy(capture)
            changed["objects"][oid(2)]["fields"][path] = value
            inspection = inspect_capture(changed, mapping, policy)
            self.assertIn("unsupported_geometry", [r["code"] for r in inspection.losses])
            with self.subTest(path=path), self.assertRaises(ValueError):
                inspection.admit(inspection.loss_digest)

    def test_nested_hierarchy_retained_never_flattened_and_cycle_refused(self):
        mapping, policy, capture = fixture(count=1500)
        for n in range(3,1501):
            capture["objects"][oid(n)]["parent_id"] = oid(n-1)
        snapshot = inspect_capture(capture, mapping, policy).admit()
        self.assertEqual(snapshot.to_dict()["inspection"]["normalized"][oid(1500)]["parent_id"], oid(1499))
        capture["objects"][oid(2)]["parent_id"] = oid(1500)
        with self.assertRaisesRegex(ValueError, "cyclic"):
            inspect_capture(capture, mapping, policy)

    def test_nested_gameplay_geometry_blocks_without_approximation(self):
        mapping, policy, capture = fixture()
        add_geometry(capture)
        capture["objects"][oid(2)]["parent_id"] = oid(3)
        inspection = inspect_capture(capture, mapping, policy)
        self.assertIn("unsupported_geometry", [r["code"] for r in inspection.losses])
        with self.assertRaises(ValueError):
            inspection.admit()

    def test_loss_review_bound_to_full_capture_and_not_reusable(self):
        mapping, policy, capture = fixture()
        capture["objects"][oid(2)]["fields"]["transform.position"] = vec("0.0000005")
        inspection = inspect_capture(capture, mapping, policy)
        with self.assertRaises(ValueError):
            inspection.admit()
        snapshot = inspection.admit(inspection.loss_digest)
        self.assertEqual(load_snapshot(snapshot.payload,mapping,policy), snapshot)
        capture["source"]["documents"][0].update(before="b"*64, after="b"*64)
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy).admit(inspection.loss_digest)

    def test_dirty_racing_and_play_mode_sources_block(self):
        mapping, policy, original = fixture()
        for change in ("dirty", "after", "play_mode"):
            capture = copy.deepcopy(original)
            if change == "play_mode":
                capture["source"][change] = True
            else:
                capture["source"]["documents"][0][change] = True if change == "dirty" else "b"*64
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect_capture(capture, mapping, policy).admit()

    def test_unknown_and_unreadable_fields_are_blocking_losses(self):
        mapping, policy, capture = fixture()
        for path in ["arbitrary.nativeCode", "transform.position"]:
            policy.fields["transform.position"] = FieldPolicy("position", read=False)
            capture["objects"][oid(2)]["fields"] = {path:vec()}
            inspection = inspect_capture(capture, mapping, policy)
            self.assertEqual(inspection.losses[0]["code"], "field_not_readable")
            with self.assertRaises(ValueError):
                inspection.admit(inspection.loss_digest)

    def test_native_owned_values_readable_but_never_writeable(self):
        mapping, policy, capture = fixture()
        policy.fields["native.label"] = FieldPolicy("text", owner="native")
        capture["objects"][oid(2)]["fields"]["native.label"] = "opaque native name"
        snapshot = inspect_capture(capture,mapping,policy).admit()
        with self.assertRaises(ValueError):
            writable_fields(snapshot,oid(2),["native.label"],mapping,policy)
        with self.assertRaises(ValueError):
            FieldPolicy("text", owner="native", write=True).validate()

    def test_writes_require_out_of_band_pinned_capability(self):
        mapping, policy, capture = fixture()
        capture["objects"][oid(2)]["fields"]["transform.position"] = vec("1")
        snapshot = inspect_capture(capture,mapping,policy).admit()
        with self.assertRaises(ValueError):
            writable_fields(snapshot,oid(2),["transform.position"],mapping,policy)
        enabled = replace(policy,fields=dict(policy.fields, **{"transform.position":FieldPolicy("position",write=True)}))
        with self.assertRaises(ValueError):
            load_snapshot(snapshot.payload,mapping,enabled)
        permitted = inspect_capture(capture,mapping,enabled).admit()
        self.assertEqual(writable_fields(permitted,oid(2),["transform.position"],mapping,enabled),
                         {"transform.position":vec("1000000")})
        capture["source"]["write"] = True
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,enabled)

    def test_opaque_content_disposition_and_critical_unknown_block(self):
        mapping, policy, capture = fixture()
        capture["objects"][oid(2)]["opaque"] = [dict(id="native-script",sha256="a"*64,
            critical=False,reason="retained cosmetic script; not translated")]
        inspection = inspect_capture(capture,mapping,policy)
        self.assertEqual(inspection.losses[0]["severity"],"info")
        inspection.admit()
        capture["objects"][oid(2)]["opaque"][0]["critical"] = True
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy).admit()

    def test_dependency_closure_and_explicit_deletions(self):
        mapping, policy, capture = fixture()
        capture["objects"][oid(2)]["dependencies"] = [dict(target=oid(3),kind="binding")]
        inspect_capture(capture,mapping,policy).admit()
        capture["objects"][oid(3)]["deleted"] = True
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)
        capture["objects"][oid(2)]["dependencies"] = []
        inspect_capture(capture,mapping,policy).admit()
        del capture["objects"][oid(3)]
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)

    def test_version_mapping_branch_and_generation_mismatch(self):
        mapping, policy, original = fixture()
        for field in ("engine_version","reader_version","materializer_version"):
            capture = copy.deepcopy(original)
            capture["source"][field] = "other"
            with self.assertRaises(ValueError):
                inspect_capture(capture,mapping,policy)
        for field in ("mapping_digest","branch_id","namespace_id","project_id"):
            capture = copy.deepcopy(original)
            capture[field] = "b"*len(capture[field])
            with self.assertRaises(ValueError):
                inspect_capture(capture,mapping,policy)
        original["objects"][oid(2)]["generation"] = "2"
        with self.assertRaises(ValueError):
            inspect_capture(original,mapping,policy)

    def test_tampered_snapshot_cannot_forge_normalization_or_losses(self):
        mapping, policy, capture = fixture()
        snapshot = inspect_capture(capture,mapping,policy).admit()
        for key, value in [("policy_digest","b"*64),("numeric_profile","other"),("normalized",{}),
                           ("losses",[dict(code="forged")])]:
            changed = snapshot.to_dict()
            changed["inspection"][key] = value
            with self.assertRaises(ValueError):
                load_snapshot(canonical(changed),mapping,policy)
        with self.assertRaises(ValueError):
            load_snapshot(snapshot.payload+b" ",mapping,policy)

    def test_malformed_json_numbers_depth_duplicates_and_size(self):
        for data in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1.0}',b'{"x":9007199254740993}',
                     b'[]',b'{',b'{"x":"\\ud800"}',b'\xff',b'['*1000+b']'*1000):
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                parse(data)
        with patch("native_authoring_contract.MAX_BYTES",20), self.assertRaises(ValueError):
            parse(b'{"long":"xxxxxxxxxxxxxx"}')

    def test_malformed_frames_corpus_fails_closed(self):
        mapping, policy, original = fixture()
        cases = []
        for value in (None,True,"x",[],{}):
            for field in ("source","scope","objects"):
                changed=copy.deepcopy(original); changed[field]=value; cases.append(changed)
            changed=copy.deepcopy(original); changed["objects"][oid(3)]=value; cases.append(changed)
        for changed in cases:
            with self.subTest(capture=changed), self.assertRaises(ValueError):
                inspect_capture(changed,mapping,policy)

    def test_seeded_malformed_leaf_corpus_has_no_untyped_crashes_or_side_effects(self):
        mapping, policy, original = fixture()
        add_geometry(original)
        paths=[]
        def walk(value,path):
            if isinstance(value,dict):
                for key,child in value.items():
                    paths.append(path+[key]); walk(child,path+[key])
            elif isinstance(value,list):
                for key,child in enumerate(value):
                    paths.append(path+[key]); walk(child,path+[key])
        walk(original,[])
        rng=random.Random(3003)
        baseline=canonical(mapping.to_dict())
        for _ in range(300):
            capture=copy.deepcopy(original); path=rng.choice(paths); cursor=capture
            for key in path[:-1]: cursor=cursor[key]
            cursor[path[-1]]=rng.choice([None,True,"",[],{},"NaN",0.5,2**63])
            try:
                inspection=inspect_capture(capture,mapping,policy)
                inspection.admit()
            except ValueError:
                pass
            self.assertEqual(canonical(mapping.to_dict()),baseline)

    def test_order_determinism_and_byte_bounds(self):
        mapping, policy, capture = fixture()
        a = inspect_capture(capture,mapping,policy).admit()
        capture["objects"] = dict(reversed(list(capture["objects"].items())))
        self.assertEqual(inspect_capture(capture,mapping,policy).admit().payload,a.payload)
        capture["objects"][oid(2)]["fields"] = {"x."+str(i):"value" for i in range(65)}
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)

    def test_core_schema_and_protocol_limits_cannot_be_overridden(self):
        mapping, policy, capture = fixture()
        policy.fields["collision.size"] = FieldPolicy("text")
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)
        policy = replace(policy,fields=core_fields())
        capture["objects"][oid(2)]["dependencies"] = [dict(target=oid(3),kind="binding")]
        with patch("native_authoring_contract.MAX_EDGES",0), self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)
        with patch("native_authoring_contract.MAX_OBJECTS",2), self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)
        capture["objects"][oid(2)]["fields"] = {"native.\U0001f680":"x"}
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)

    def test_malformed_nested_metadata_and_duplicate_dependencies(self):
        mapping, policy, original = fixture()
        patches = [("dependencies",[dict(target=oid(3),kind=[])]) ,
                   ("dependencies",[dict(target=oid(3),kind="binding")]*2),
                   ("dependencies",[dict(target=oid(99),kind="resource")]),
                   ("opaque",[dict(id="x",sha256="a"*64,critical="false",reason="unsupported")]),
                   ("parent_id",[]),("generation",True),("deleted","false"),("fields",[])]
        for field,value in patches:
            capture=copy.deepcopy(original); capture["objects"][oid(2)][field]=value
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                inspect_capture(capture,mapping,policy)

    def test_scene_and_prefab_closure_and_cross_scene_parenting(self):
        mapping, policy, capture = fixture(count=4)
        mapping.objects[oid(4)].kind="scene"; mapping.objects[oid(4)].scene_id=None
        mapping.objects[oid(3)].scene_id=oid(4)
        capture["mapping_digest"]=mapping.mapping_digest()
        capture["objects"][oid(2)]["parent_id"]=oid(3)
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)
        capture["objects"][oid(2)]["parent_id"]=None
        capture["objects"][oid(4)]["deleted"]=True
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)
        mapping, policy, capture = fixture()
        mapping.objects[oid(3)].kind="prefab_definition"; mapping.objects[oid(3)].scene_id=None
        mapping.objects[oid(2)].kind="prefab_instance"; mapping.objects[oid(2)].prefab_id=oid(3)
        capture["mapping_digest"]=mapping.mapping_digest()
        inspect_capture(capture,mapping,policy).admit()
        capture["objects"][oid(3)]["deleted"]=True
        with self.assertRaises(ValueError):
            inspect_capture(capture,mapping,policy)


class DeltaTests(unittest.TestCase):
    def test_delta_roundtrip_noop_and_repeat_wrong_base(self):
        mapping, policy, capture = fixture()
        base = inspect_capture(capture,mapping,policy).admit()
        capture["objects"][oid(2)]["fields"]["transform.position"] = vec("1")
        capture["source"]["documents"][0].update(before="b"*64,after="b"*64)
        target = inspect_capture(capture,mapping,policy).admit()
        delta = make_delta(base,target,mapping,policy)
        self.assertEqual(apply_delta(base,delta,mapping,policy),target)
        self.assertEqual(apply_delta(base,make_delta(base,base,mapping,policy),mapping,policy),base)
        with self.assertRaises(ValueError):
            apply_delta(target,delta,mapping,policy)

    def test_delta_stale_precondition_scope_tamper_and_target_hash(self):
        mapping, policy, capture = fixture()
        base = inspect_capture(capture,mapping,policy).admit()
        capture["objects"][oid(2)]["deleted"] = True
        target = inspect_capture(capture,mapping,policy).admit()
        original = parse(make_delta(base,target,mapping,policy))
        for change in ("before","target_digest","scope","after"):
            delta = copy.deepcopy(original)
            if change == "before": delta["changes"][oid(2)]["before"] = "a"*64
            elif change == "target_digest": delta[change] = "a"*64
            elif change == "scope": delta["header"]["scope"] = [oid(1)]
            else: delta["changes"][oid(2)]["after"]["deleted"] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                apply_delta(base,canonical(delta),mapping,policy)

    def test_delta_precision_review_and_dirty_target_are_revalidated(self):
        mapping, policy, capture = fixture()
        base = inspect_capture(capture,mapping,policy).admit()
        capture["objects"][oid(2)]["fields"]["transform.position"] = vec("0.0000015")
        inspection = inspect_capture(capture,mapping,policy)
        target = inspection.admit(inspection.loss_digest)
        delta = make_delta(base,target,mapping,policy)
        self.assertEqual(apply_delta(base,delta,mapping,policy),target)
        bad = parse(delta); bad["header"]["source"]["documents"][0]["dirty"] = True
        with self.assertRaises(ValueError):
            apply_delta(base,canonical(bad),mapping,policy)


if __name__ == "__main__":
    unittest.main()
