"""Installed native authoring gateway proof in fresh persistent projects."""
import sys,shutil,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from native_editor_gateway import NativeEditorGateway
from native_adoption import bridge
from authoring_identity import canonical
from authoring_transaction_files import sha
from native_reconciliation_plan import _native_transform
EXES={'godot':Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe'),'unity':Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe'),'unreal':Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')}
SOURCES={'godot':'evidence/nec010/20261018/godot-setup-c','unity':'evidence/nec010/20261018/unity-setup-c','unreal':'evidence/nec010/ue/setup-a'}

def main(engine,out,compiled=None):
    assert out.is_relative_to(ROOT/'evidence/nec010') and not out.exists();out.mkdir(parents=True)
    source=ROOT/SOURCES[engine];root=out/(engine+'-project');root.mkdir()
    if engine=='unity':
        roots=['Assets','Packages','ProjectSettings'];docs=['Assets/XACEGenerated/World.unity'];plugin='Assets/XaceAuthoring';project_file=None
        for folder in roots:shutil.copytree(source/'unity-project'/folder,root/folder,ignore=shutil.ignore_patterns('*Proof*'))
        shutil.copytree(ROOT/'adapters/unity/Authoring',root/plugin,dirs_exist_ok=True,ignore=shutil.ignore_patterns('*Proof*'))
    elif engine=='godot':
        roots=['addons','XACEGenerated','project.godot'];docs=['res://XACEGenerated/World.tscn'];plugin='addons/xace_authoring';project_file=None
        shutil.copytree(source/'godot-project/XACEGenerated',root/'XACEGenerated')
        shutil.copyfile(source/'godot-project/project.godot',root/'project.godot')
        shutil.copytree(ROOT/'adapters/godot/authoring',root/plugin,ignore=shutil.ignore_patterns('*proof*'))
    else:
        assert compiled is not None
        roots=['Config','Content','Plugins','XACESetup.uproject'];docs=['/Game/XACEGenerated/World'];plugin='Plugins/XACEAuthoring';project_file='XACESetup.uproject'
        for folder in ['Config','Content']:shutil.copytree(source/'unreal-project'/folder,root/folder)
        shutil.copyfile(source/'unreal-project'/project_file,root/project_file)
        shutil.copytree(compiled/'unreal-project/Plugins',root/'Plugins',ignore=shutil.ignore_patterns('Intermediate','*.pdb'))
    pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/plugin).rglob('*') if p.is_file() and p.suffix!='.meta'}
    config=dict(engine=engine,executable=str(EXES[engine]),executable_sha256=sha(EXES[engine].read_bytes()),documents=docs,source_roots=roots,plugin_hashes=pins,project_file=project_file,trusted_closed_project=True)
    (out/'gateway-config.json').write_bytes(canonical(config))
    gateway=NativeEditorGateway(root,**config);data=gateway.capture();reader=bridge(engine)
    mapping=reader.prepare_identity_map(data,project_id='gateway-proof',branch_id='b'*32);baseline=reader.capture(data,mapping,enable_writes=True).admit()
    noop=gateway.prepare('noop',{'write_request':None});assert gateway.inspect(noop)=='before';gateway.commit(noop);assert gateway.inspect(noop)=='after';gateway.recover(noop);assert gateway.inspect(noop)=='before'
    key=next(k for k,r in mapping.objects.items() if r.kind=='object');target=json.loads(data)
    fixed=copy.deepcopy(baseline.to_dict()['inspection']['normalized'][key]['fields']['transform.position']);fixed['x']=str(int(fixed['x'])+1000000)
    target['objects'][key]['fields']['transform.position']=_native_transform(engine,'transform.position',fixed)
    desired=reader.capture(canonical(target),mapping,enable_writes=True).admit();request=json.loads(reader.write_request(data,baseline,desired,mapping))
    prepared=gateway.prepare('gateway-transform',{'write_request':request});assert gateway.inspect(prepared)=='before';gateway.commit(prepared);assert gateway.inspect(prepared)=='after'
    after=reader.capture(gateway.capture(),mapping,enable_writes=True).admit();assert after.to_dict()['inspection']['normalized']==desired.to_dict()['inspection']['normalized']
    gateway.recover(prepared);assert gateway.inspect(prepared)=='before';assert gateway.capture()==data
    (out/'proof.json').write_bytes(canonical(dict(ok=True,engine=engine,production_entrypoint=True,real_native_editor=True,capture=True,noop_receipt=True,prepare_commit_recapture=True,exact_rollback=True)))
    print((out/'proof.json').read_text())
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve() if len(sys.argv)>3 else None)
