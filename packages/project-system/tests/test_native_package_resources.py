import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
import playable_package as pp
import native_package_resources as native
from tools.xp007_package_proof import package_fixture,compile_plan
from tools.cgs_schema_validate import compute_cgs_hash

class NativePackageResourceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.cgs=package_fixture();cls.cgs.setdefault('assets',[]).append(dict(id='native_mesh',asset_type='MESH',status='LINKED',source='Assets/Mesh.asset'))
  cls.cgs['metadata']['cgs_hash']=compute_cgs_hash(cls.cgs)
  cls.plan,compiled=compile_plan(cls.cgs);cls.runtime=b'inert native-resource unit-test runtime; never executed'
  cls.support=pp.RuntimeSupport(pp.digest(cls.runtime),'xace.runtime_executor.v1',tuple(compiled.to_sgc_input()))
 def build(self,files):return pp.build_package(self.cgs,self.plan,self.runtime,self.support,package_id='native.resource.proof',version='1.0.0',presentation_files=files)
 def resources(self):return native.prepare_resources(self.cgs,'unity',{'Assets/Mesh.asset':b'native serialized bytes'})
 def test_real_package_verification_preserves_cgs_and_native_bytes(self):
  before=pp.encode(self.cgs);files=self.resources();archive=self.build(files)
  self.assertEqual(archive,self.build(files));loaded=pp.read_archive(archive);pp.verify_files(loaded,self.support)
  self.assertEqual(loaded['game.cgs.json'],before);self.assertEqual(pp.encode(self.cgs),before)
  self.assertEqual(loaded['presentation/unity/Assets/Mesh.asset'],b'native serialized bytes')
 def test_missing_mapping_still_refuses_creator_relative_dependency(self):
  with self.assertRaises(pp.PackageError):self.build({'presentation/unity/Assets/Mesh.asset':b'native serialized bytes'})
 def test_missing_or_tampered_payload_refused_with_fresh_archive_hashes(self):
  for missing in [True,False]:
   files=self.resources();path='presentation/unity/Assets/Mesh.asset'
   if missing:del files[path]
   else:files[path]+=b'changed'
   with self.subTest(missing=missing),self.assertRaises(pp.PackageError):self.build(files)
 def test_foreign_identity_type_source_and_duplicate_records_refused(self):
  for key,value in [('id','other'),('asset_type','MATERIAL'),('source','Assets/Other.asset'),('path','presentation/godot/Assets/Mesh.asset')]:
   files=self.resources();p='presentation/unity/native-resources.json';catalog=pp.parse(files[p]);catalog['assets'][0][key]=value;files[p]=pp.encode(catalog)
   with self.subTest(key=key),self.assertRaises(pp.PackageError):self.build(files)
  files=self.resources();p='presentation/unity/native-resources.json';catalog=pp.parse(files[p]);catalog['assets']*=2;files[p]=pp.encode(catalog)
  with self.assertRaises(pp.PackageError):self.build(files)
 def test_unsafe_resource_names_and_catalog_collision_refused(self):
  for name in ['../outside','C:/secret','/absolute','Assets\\Mesh.asset','Assets/../Mesh.asset','CON.txt','native-resources.json']:
   with self.subTest(name=name),self.assertRaises(pp.PackageError):native.prepare_resources(self.cgs,'unity',{'Assets/Mesh.asset':b'a',name:b'b'})
 def test_unknown_engine_and_missing_resource_refused(self):
  with self.assertRaises(pp.PackageError):native.prepare_resources(self.cgs,'player',{'Assets/Mesh.asset':b'a'})
  with self.assertRaises(pp.PackageError):native.prepare_resources(self.cgs,'unity',{})
 def test_catalog_requires_exact_schema_and_engine(self):
  for change in [dict(schema='unknown'),dict(engine='unreal'),dict(extra=True)]:
   files=self.resources();p='presentation/unity/native-resources.json';catalog=pp.parse(files[p]);catalog.update(change);files[p]=pp.encode(catalog)
   with self.subTest(change=change),self.assertRaises(pp.PackageError):self.build(files)
if __name__=='__main__':unittest.main()
