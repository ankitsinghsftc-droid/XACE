import copy
import dataclasses
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
import playable_package as pp
from tools.xp007_package_proof import package_fixture,compile_plan
from tools.xp005_reference_proof import fixture,factory

class PlayablePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cgs=package_fixture();cls.plan,cls.compiled=compile_plan(cls.cgs)
        cls.runtime=b"inert unit-test runtime identity; never executed"
        cls.support=pp.RuntimeSupport(pp.digest(cls.runtime),"xace.runtime_executor.v1",tuple(cls.compiled.to_sgc_input()))
        cls.blob=cls.build()

    @classmethod
    def build(cls,**kw):
        return pp.build_package(cls.cgs,cls.plan,cls.runtime,cls.support,package_id="project.proof",version="1.0.0",**kw)

    def test_deterministic_archive_and_factory_projection(self):
        self.assertEqual(self.blob,self.build())
        files=pp.read_archive(self.blob)
        self.assertEqual(pp.archive_files(files),self.blob)
        manifest=pp.verify_files(files,self.support)
        self.assertEqual(manifest["gameplay"]["world"]["contract_version"],3)
        self.assertEqual(len(pp.parse(files["world.json"])["objects"]),12)

    def test_presentation_variants_share_gameplay_identity(self):
        a=self.build(presentation_files={"presentation/godot/bindings.json":b"plain"})
        b=self.build(presentation_files={"presentation/unreal/bindings.json":b"detailed"})
        ma=pp.verify_archive(a,self.support);mb=pp.verify_archive(b,self.support)
        self.assertEqual(ma["gameplay_hash"],mb["gameplay_hash"])
        self.assertNotEqual(ma["package_content_hash"],mb["package_content_hash"])

    def test_missing_and_tampered_artifacts_reject(self):
        for name in pp.CORE_FILES:
            files=pp.read_archive(self.blob);files[name]+=b"tamper"
            with self.subTest(name=name),self.assertRaises(Exception):pp.verify_files(files,self.support)
            files=pp.read_archive(self.blob);del files[name]
            with self.assertRaises(pp.PackageError):pp.verify_files(files,self.support)

    def test_untrusted_runtime_executor_and_profiles_reject(self):
        for support in [dataclasses.replace(self.support,executable_sha256="0"*64),dataclasses.replace(self.support,system_contracts=()),
                        dataclasses.replace(self.support,world_versions=(2,)),dataclasses.replace(self.support,abi="unknown")]:
            with self.assertRaises(pp.PackageError):pp.verify_archive(self.blob,support)

    def test_forged_sgc_identity_rejected_even_when_file_checksums_recomputed(self):
        plan=json.loads(self.plan);plan["plan_hash"]="0"*64;plan["proof_bundle"]["plan_hash"]="0"*64
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            pp.build_package(self.cgs,pp.encode(plan),self.runtime,self.support,package_id="p",version="1.0.0")

    def test_rehashed_world_tamper_still_fails_factory_source_check(self):
        files=pp.read_archive(self.blob)
        world=pp.parse(files["world.json"]);world["objects"][0]["properties"]["strength"]=999
        files["world.json"]=pp.encode(world)
        manifest=pp.parse(files[pp.MANIFEST])
        for record in manifest["files"]:
            record.update(size=len(files[record["path"]]),sha256=pp.digest(files[record["path"]]))
        manifest.pop("package_content_hash")
        manifest["package_content_hash"]=pp._sha256_json(manifest)
        files[pp.MANIFEST]=pp.encode(manifest)
        with self.assertRaisesRegex(pp.PackageError,"Factory projection"):
            pp.verify_files(files,self.support)

    def test_creator_machine_asset_paths_are_not_package_dependencies(self):
        from tools.world_extensibility_proof import rehash
        for location in ["C:/creator/hull.mesh","../outside.mesh","assets/unpackaged.mesh"]:
            cgs=copy.deepcopy(self.cgs);cgs["assets"][0]["source"]=location;rehash(cgs)
            with self.subTest(location=location),self.assertRaisesRegex((pp.PackageError,factory.SchemaFactoryError),"source|asset location"):
                plan,compiled=compile_plan(cgs)
                support=dataclasses.replace(self.support,system_contracts=tuple(compiled.to_sgc_input()))
                pp.build_package(cgs,plan,self.runtime,support,package_id="p",version="1.0.0")

    def test_archive_traversal_links_duplicates_and_limits(self):
        for name in ["../escape","/absolute","C:/drive","nested/../../escape","a\\escape","CON","a:stream","a./b"]:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,"w") as z:z.writestr(name,b"x")
            archive=stream.getvalue()
            if chr(92) in name:archive=archive.replace(name.replace(chr(92),"/").encode(),name.encode())
            with self.subTest(name=name),self.assertRaises(pp.PackageError):pp.read_archive(archive)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w") as z:
            info=zipfile.ZipInfo("link");info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,b"outside")
        with self.assertRaises(pp.PackageError):pp.read_archive(stream.getvalue())
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,"w") as z:z.writestr("File",b"a");z.writestr("file",b"b")
        with self.assertRaises(pp.PackageError):pp.read_archive(stream.getvalue())
        with patch.object(pp,"MAX_FILE_BYTES",1),self.assertRaises(pp.PackageError):pp.read_archive(self.blob)
        with patch.object(pp,"MAX_FILES",1),self.assertRaises(pp.PackageError):pp.read_archive(self.blob)
        with patch.object(pp,"MAX_TOTAL_BYTES",1),self.assertRaises(pp.PackageError):pp.read_archive(self.blob)

    def test_install_relocation_and_interruption_preserve_previous_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);destination,manifest=pp.install_archive(self.blob,root,self.support)
            self.assertEqual(pp.verify_files(pp.read_installed(destination),self.support),manifest)
            before=(root/"active.json").read_bytes()
            replacement=self.build(presentation_files={"presentation/new/bindings.json":b"new"})
            with patch.object(Path,"write_bytes",side_effect=OSError("interrupted extraction")),self.assertRaises(OSError):
                pp.install_archive(replacement,root,self.support)
            self.assertEqual((root/"active.json").read_bytes(),before)
            with patch.object(pp.os,"replace",side_effect=OSError("interrupted activation")),self.assertRaises(OSError):
                pp.install_archive(replacement,root,self.support)
            self.assertEqual((root/"active.json").read_bytes(),before)
            self.assertTrue(destination.exists())
            pp.install_archive(replacement,root,self.support)
            self.assertNotEqual((root/"active.json").read_bytes(),before)

    def test_import_never_executes_payload(self):
        with patch("subprocess.Popen",side_effect=AssertionError("payload executed")):
            pp.verify_archive(self.blob,self.support)
            with tempfile.TemporaryDirectory() as tmp:pp.install_archive(self.blob,tmp,self.support)

    def test_legacy_reference_package_uses_same_generic_verifier(self):
        cgs=fixture();plan=(ROOT/"examples/reference-mechanic/fixtures/execution_plan.json").read_bytes()
        support=dataclasses.replace(self.support,system_contracts=tuple(factory.compile_portable_cgs(cgs).to_sgc_input()))
        blob=pp.build_package(cgs,plan,self.runtime,support,package_id="reference.proof",version="1.0.0")
        self.assertEqual(pp.verify_archive(blob,support)["gameplay"]["world"]["contract_version"],2)
        with self.assertRaises(pp.PackageError):pp.verify_archive(blob,dataclasses.replace(support,geometry_profiles=()))

if __name__=="__main__":unittest.main()
