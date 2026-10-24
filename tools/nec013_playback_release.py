"""Create a fresh reference-executor package whose authoritative jump event drives Unity playback."""
from pathlib import Path
import copy,hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
import playable_package as package
import native_executor_contract as contract
from tools.cgs_schema_validate import compute_cgs_hash

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec013') and not out.exists();out.mkdir(parents=True)
 base=ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Unity/release'
 cgs=json.loads((base/'package/game.cgs.json').read_bytes());mode=cgs['modes'][0];floor,player=mode['actors']
 floor['components'][0]['defaults']['position']['y']=-1000000
 floor['components'].append(dict(type_id=4,name='COMP_COLLIDER_V1',defaults=dict(shape='BOX',size=dict(x=20000000,y=1000000,z=20000000),offset=dict(x=0,y=0,z=0),is_trigger=False,layer_mask=1)))
 world=mode['world']['contract'];world['geometry_profiles']=[dict(id='world.aabb.v1',required=True)];world['objects'][0]['geometry_profile']='world.aabb.v1';world['objects'][1]['geometry_profile']='world.aabb.v1'
 # Collider bounds and gameplay are computed by the unchanged trusted executor.
 cgs['semantic_bindings']=dict(bindings=[dict(binding_id='nec013.'+kind.lower(),event_name='reference.ground_jump.v1',playback_kind=kind,asset=dict(id=asset,asset_type=typ,status='Linked'),semantic_action='play',entity_selector='SourceEntity',parameters=dict(resource_path=asset,xace_binding_required='true'),priority=i) for i,(kind,asset,typ) in enumerate([('Audio','nec013-tone','AudioClip'),('Animation','nec013-echo','AnimationClip')])])
 cgs['metadata']['cgs_hash']=compute_cgs_hash(cgs)
 compiled,_=package.compiled_artifacts(cgs)
 receipt=json.loads((base/'executor-receipt.json').read_bytes());exe=base/'package/runtime/xace_runtime.exe'
 support=contract.admit(receipt,expected_receipt_digest=contract.digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=compiled)
 sgc=Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-system-graph-compiler.exe')
 request=dict(systems=compiled.to_sgc_input(),schema_version=compiled.schema_version,cgs_hash=compiled.cgs_hash,plan_version=1)
 plan=subprocess.run([str(sgc)],input=package.encode(request),capture_output=True,check=True).stdout
 archive=package.build_package(cgs,plan,exe.read_bytes(),support,package_id='nec013.unity-playback',version='0.1.0')
 release=out/'release';release.mkdir();shutil.copyfile(base/'executor-receipt.json',release/'executor-receipt.json')
 for name,data in package.read_archive(archive).items():
  p=release/'package'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 native=json.loads((base/'native-release.json').read_bytes());native['package_manifest_sha256']=hashlib.sha256((release/'package/playable.manifest.json').read_bytes()).hexdigest()
 (release/'native-release.json').write_bytes(package.encode(native))
 (out/'creator-proof.json').write_bytes(package.encode(dict(ok=True,executor_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),sgc_sha256=hashlib.sha256(sgc.read_bytes()).hexdigest(),release_sha256=hashlib.sha256((release/'native-release.json').read_bytes()).hexdigest(),runtime_not_recompiled=True,native_playback_verified=False)))
 print(str(release))
if __name__=='__main__':main(Path(sys.argv[1]))
