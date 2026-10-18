"""Exercise the registered factory, not an editor proof-only entry point."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from native_setup_factory import create_native_setup_stage
from native_setup_plan import NativeSetupPlan
from authoring_identity import canonical
from authoring_transaction_files import sha
from nec010_editor_gateway_proof import SOURCES

def main(engine,source,out,compiled=None):
    assert out.is_relative_to(ROOT/'evidence/nec010') and not out.exists();out.mkdir(parents=True)
    config=json.loads((source/'gateway-config.json').read_text());root=source/(engine+'-project')
    files={}
    for relative in config['source_roots']:
        p=root/relative
        for f in ([p] if p.is_file() else p.rglob('*')):
            key=f.relative_to(root).as_posix()
            if f.is_file() and 'xacegenerated' not in key.casefold() and '__XaceAuthoringStage' not in key:files[key]=f.read_bytes()
    if engine=='godot':
        for p in (ROOT/'adapters/godot/authoring').iterdir():
            if p.is_file() and 'proof' not in p.name:files['addons/xace_authoring/'+p.name]=p.read_bytes()
        config['plugin_hashes']={p:sha(b) for p,b in files.items() if p.startswith('addons/')}
    if engine=='unreal':
        assert compiled
        files={p:b for p,b in files.items() if not p.startswith('Plugins/')}
        for p in (compiled/'unreal-project/Plugins').rglob('*'):
            if p.is_file() and 'Intermediate' not in p.parts and p.suffix!='.pdb':files['Plugins/'+p.relative_to(compiled/'unreal-project/Plugins').as_posix()]=p.read_bytes()
        config['plugin_hashes']={p:sha(b) for p,b in files.items() if p.startswith('Plugins/')}
    evidence=ROOT/SOURCES[engine];cgs=json.loads((evidence/'source.cgs.json').read_text());plan=NativeSetupPlan((evidence/'setup-plan.json').read_bytes())
    stage=create_native_setup_stage(plan,cgs,out/(engine+'-project'),template_files=files,gateway_config=config)
    assert stage(cgs)['files']
    (out/'gateway-config.json').write_bytes(canonical(config))
    (out/'proof.json').write_bytes(canonical(dict(ok=True,engine=engine,production_factory=True,fresh_native_capture=True,review_files=len(stage.files))))
    print((out/'proof.json').read_text())
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve(),Path(sys.argv[4]).resolve() if len(sys.argv)>4 else None)
