"""New Godot presentation package using the admitted NEC013 reference executor."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
import playable_package as package
import native_executor_contract as contract
from tools.cgs_schema_validate import compute_cgs_hash
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec014') and not out.exists();out.mkdir(parents=True)
 base=ROOT/'evidence/nec013/20261024/playback-package-c/release'
 cgs=json.loads((base/'package/game.cgs.json').read_bytes())
 for b in cgs['semantic_bindings']['bindings']:
  b['binding_id']=b['binding_id'].replace('nec013.','nec014.')
  b['parameters']={'xace_binding_required':'true',**({'resource_path':'res://tone.tres'} if b['playback_kind']=='Audio' else {'animation':'play'})}
 cgs['metadata']['cgs_hash']=compute_cgs_hash(cgs)
 compiled,_=package.compiled_artifacts(cgs);receipt=json.loads((base/'executor-receipt.json').read_bytes());exe=base/'package/runtime/xace_runtime.exe'
 support=contract.admit(receipt,expected_receipt_digest=contract.digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=compiled)
 request=dict(systems=compiled.to_sgc_input(),schema_version=compiled.schema_version,cgs_hash=compiled.cgs_hash,plan_version=1)
 sgc='C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-system-graph-compiler.exe'
 plan=subprocess.run([sgc],input=package.encode(request),capture_output=True,check=True).stdout
 archive=package.build_package(cgs,plan,exe.read_bytes(),support,package_id='nec014.godot-playback',version='0.1.0',presentation_files={'presentation/player/native-bindings.json':package.encode(cgs['semantic_bindings'])})
 release=out/'release';release.mkdir();shutil.copyfile(base/'executor-receipt.json',release/'executor-receipt.json')
 for name,data in package.read_archive(archive).items():
  p=release/'package'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 native=json.loads((base/'native-release.json').read_bytes());native['engine']='Godot';native['package_manifest_sha256']=hashlib.sha256((release/'package/playable.manifest.json').read_bytes()).hexdigest()
 (release/'native-release.json').write_bytes(package.encode(native));print(str(release))
if __name__=='__main__':main(Path(sys.argv[1]))
