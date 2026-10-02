import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
from tools.xp009_player_proof import resources
from player_presentation import validate_presentation,validate_resource,CATALOG
from playable_package import PackageError

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.manifest={"gameplay":{"world":{"artifact":{"content_hash":"trusted-world"}}}}
        self.world={"objects":[{"id":"project.spaceship.v1","geometry":{"size":dict(x=1000000,y=2000000,z=3000000)}}]}
        self.files=resources(self.manifest,self.world)
        self.files["world.json"]=json.dumps(self.world).encode()
        self.catalog=json.loads(self.files[CATALOG])
    def validate(self):
        self.files[CATALOG]=json.dumps(self.catalog).encode()
        return validate_presentation(self.files,self.manifest)
    def test_arbitrary_object_and_event_names(self):
        for event in self.catalog["events"]:event["event_name"]="space.docking.complete.v7"
        self.assertTrue(all(r["status"]=="resolved" for r in self.validate()["records"]))
    def test_optional_absence_reports_fallback(self):
        del self.files["presentation/resources/pulse.json"]
        report=self.validate();self.assertIn("presentation/resources/pulse.json",report["optional_paths"])
        self.assertEqual(next(r for r in report["records"] if r["asset_id"]=="pulse")["status"],"fallback")
    def test_required_absence_rejected(self):
        self.catalog["assets"][0]["required"]=True
        del self.files[self.catalog["assets"][0]["path"]]
        with self.assertRaises(PackageError):self.validate()
    def test_world_hash_mismatch(self):
        self.catalog["world_hash"]="other"
        with self.assertRaises(PackageError):self.validate()
    def test_unresolved_and_mismatched_types(self):
        original=copy.deepcopy(self.catalog)
        for change in [{"status":"Unresolved"},{"asset_type":"AudioClip"}]:
            self.catalog=copy.deepcopy(original);self.catalog["assets"][0]["asset"].update(change)
            with self.assertRaises(PackageError):self.validate()
    def test_unknown_or_duplicate_binding(self):
        original=copy.deepcopy(self.catalog)
        for field in ["objects","events","assets"]:
            self.catalog=copy.deepcopy(original);self.catalog[field].append(copy.deepcopy(self.catalog[field][0]))
            with self.assertRaises(PackageError):self.validate()
        self.catalog=original;self.catalog["objects"][0]["object_id"]="missing"
        with self.assertRaises(PackageError):self.validate()
    def test_unsafe_and_executable_formats(self):
        original=copy.deepcopy(self.catalog)
        for path in ["../escape.json","runtime/xace_runtime.exe","C:/scene.tscn"]:
            self.catalog=copy.deepcopy(original);self.catalog["assets"][0]["path"]=path
            with self.assertRaises(PackageError):self.validate()
        self.catalog=original;self.catalog["assets"][0]["format"]="godot.packed_scene.v1"
        with self.assertRaises(PackageError):self.validate()
    def test_invalid_mesh_effect_audio_and_image(self):
        for fmt,data in [("xace.mesh.v1",b'{"schema":"xace.mesh.v1","vertices":[],"indices":[],"color":[1,1,1,1]}'),("xace.effect.ring.v1",b'{"schema":"xace.effect.ring.v1","radius":1,"duration_ticks":0,"color":[1,1,1,1]}'),("audio.pcm_wav.v1",b'RIFF'),("image.png.v1",b'not png')]:
            with self.subTest(fmt=fmt),self.assertRaises(PackageError):validate_resource(fmt,data)
    def test_legacy_catalog_absent(self):
        del self.files[CATALOG];self.assertIsNone(validate_presentation(self.files,self.manifest)["catalog"])

if __name__=="__main__":unittest.main()
