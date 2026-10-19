"""Real registered-mesh reconciliation through the production host."""
import copy,json,shutil,sys,importlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from test_native_presentation_reconciliation import context as fixture_context
from native_adoption import _asset_source
from native_editor_gateway import NativeEditorGateway
from native_materialization import NativeMaterializationHost
from authoring_identity import IdentityMap,WorldBinding,canonical
from authoring_transaction_files import sha,load_json
from authoring_transaction_contract import TransactionRequest
from authoring_apply import file_change,ACTIVATION
from authoring_saved_pair import SavedPair,MAP,CGS,NATIVE,verify_baseline_receipts
from native_authoring_contract import Snapshot
from native_adoption import digest
from tools.world_extensibility_proof import rehash


def main(out,engine='unity'):
    reader=importlib.import_module(engine+'_authoring')
    assert out.is_relative_to(ROOT/'evidence/nec010') and not out.exists();root=out/(engine+'-project');root.mkdir(parents=True)
    if engine=='unity':
        source=ROOT/'evidence/nec010/20261016/unity-resources-a/unity-project'
        roots=['Assets','Packages','ProjectSettings'];docs=['Assets/Fixture/World.unity','Assets/Fixture/Template.prefab'];addon='Assets/XaceAuthoring'
        for folder in roots:shutil.copytree(source/folder,root/folder,ignore=shutil.ignore_patterns('*Proof*','__XaceAuthoringStage*'))
        shutil.copytree(ROOT/'adapters/unity/Authoring',root/addon,dirs_exist_ok=True,ignore=shutil.ignore_patterns('*Proof*'))
        exe=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe');key=f'{4:032x}'
    elif engine=='godot':
        source=ROOT/'evidence/nec010/20261017/godot-mapped-preservation-a/godot-project';addon='addons/xace_authoring'
        roots=['Fixture','addons','project.godot','xace_protocol.gd','xace_protocol.gd.uid'];docs=['res://Fixture/Template.tscn','res://Fixture/World.tscn']
        shutil.copytree(source/'Fixture',root/'Fixture')
        for name in ['project.godot','xace_protocol.gd','xace_protocol.gd.uid']:shutil.copyfile(source/name,root/name)
        shutil.copytree(ROOT/'adapters/godot/authoring',root/addon,ignore=shutil.ignore_patterns('*proof*'))
        exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe');key=f'{8:032x}'
        script=out/'prepare_mesh_fixture.gd'
        script.write_text('extends SceneTree\nfunc _initialize():\n    var saved_uid = ResourceLoader.get_resource_uid("res://Fixture/World.tscn")\n    var scene = load("res://Fixture/World.tscn").instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)\n    var mesh = MeshInstance3D.new()\n    mesh.name = "ExplicitRootMesh"\n    mesh.mesh = load("res://Fixture/Mesh.res")\n    var identity = scene.get_meta("xace_identity_v1").duplicate()\n    identity.authoring_id = "%032x" % 8\n    identity.local_id = "%032x" % 1008\n    identity.kind = "object"\n    mesh.set_meta("xace_identity_v1", identity)\n    scene.add_child(mesh)\n    mesh.owner = scene\n    var packed = PackedScene.new()\n    assert(packed.pack(scene) == OK)\n    assert(ResourceSaver.save(packed, "res://Fixture/World.tscn") == OK)\n    assert(ResourceSaver.set_uid("res://Fixture/World.tscn", saved_uid) == OK)\n    scene.free()\n    quit(0)\n')
        with (out/'import-fixture.log').open('wb') as log:
            subprocess.run([str(exe),'--headless','--editor','--import','--path',str(root)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        with (out/'prepare-fixture.log').open('wb') as log:
            subprocess.run([str(exe),'--headless','--path',str(root),'--script',str(script)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        assert engine=='unreal'
        source=ROOT/'evidence/nec010/ue/l/unreal-project';addon='Plugins/XACEAuthoring'
        roots=['Content','Config','Plugins','NEC006.uproject'];docs=['/Game/Fixture/World']
        for folder in ['Content','Config']:shutil.copytree(source/folder,root/folder)
        shutil.copyfile(source/'NEC006.uproject',root/'NEC006.uproject')
        for folder in ['Source','Binaries','Resources']:
            if (source/addon/folder).exists():shutil.copytree(source/addon/folder,root/addon/folder)
        shutil.copyfile(source/addon/'XACEAuthoring.uplugin',root/addon/'XACEAuthoring.uplugin')
        for path in (ROOT/'adapters/unreal/Authoring/Source').rglob('*'):
            if path.is_file():assert path.read_bytes()==(root/addon/'Source'/path.relative_to(ROOT/'adapters/unreal/Authoring/Source')).read_bytes(), 'Rebuild current native source first'
        exe=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe');key=f'{2:032x}'
    pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/addon).rglob('*') if p.is_file() and p.suffix!='.meta'}
    gateway=NativeEditorGateway(root,engine=engine,executable=str(exe),executable_sha256=sha(exe.read_bytes()),documents=docs,source_roots=roots,plugin_hashes=pins,project_file="NEC006.uproject" if engine=="unreal" else None,trusted_closed_project=True)
    data=gateway.capture();mapping=reader.prepare_identity_map(data,project_id='mesh-host',branch_id='b'*32);snapshot=reader.capture(data,mapping,enable_writes=True).admit()
    rows=snapshot.to_dict()['inspection']['normalized'];fields=rows[key]['fields'];original=fields['presentation.asset']
    cgs=fixture_context(engine)['current_cgs'];mode=cgs['modes'][0];actor=mode['actors'][0];mode['actors']=[actor];mode['world']['contract']['objects']=mode['world']['contract']['objects'][:1]
    transform=actor['components'][0]['defaults']
    for name in ['position','rotation','scale']:transform[name]={a:int(v) for a,v in fields['transform.'+name].items()}
    replacement_name={'unity':'ReplacementMesh.asset','godot':'Replacement.res','unreal':'OtherMesh.OtherMesh'}[engine]
    refs=[]
    def find_refs(value):
        if isinstance(value,dict):
            if str(value.get('resolved_path','')).endswith('/'+replacement_name):refs.append(value)
            for child in value.values():find_refs(child)
        elif isinstance(value,list):
            for child in value:find_refs(child)
    journals=source/('.xace_authoring' if engine=='godot' else '.xace')
    for path in journals.rglob('*.json'):find_refs(json.loads(path.read_text(encoding='utf-8-sig')))
    assert refs and all(r==refs[0] for r in refs), 'Unambiguous native-proven replacement required'
    replacement=refs[0];assert replacement['asset_type']=='MESH'
    cgs['assets']=[dict(id=r['asset_id'],asset_type='MESH',status='LINKED',source=_asset_source(engine,r['resolved_path'])) for r in [original,replacement]]
    obj=mode['world']['contract']['objects'][0]
    obj['asset_bindings']={'project.visual.v1':dict(id=original['asset_id'],asset_type='MESH',status='LINKED')}
    # Other enrolled fixture objects remain native-owned and unchanged.
    if 'binding.playback' in fields:
        from test_native_playback_reconciliation import context as playback_context
        playback=fields['binding.playback'];ref=playback['asset']
        binding=copy.deepcopy(playback_context(engine)['current_cgs']['semantic_bindings']['bindings'][0])
        binding.update(binding_id=playback['binding_id'],event_name=playback['event_name'],playback_kind=playback['playback_kind'],asset=dict(id=ref['asset_id'],asset_type='AnimationClip',status='Linked'))
        binding['parameters']['resource_path']=ref['resolved_path']
        cgs['semantic_bindings']=copy.deepcopy(playback_context(engine)['current_cgs']['semantic_bindings']);cgs['semantic_bindings']['bindings']=[binding]
        cgs['semantic_events']=[dict(name=playback['event_name'],payload_fields=[],version='1.0.0')]
        cgs['assets'].append(dict(id=ref['asset_id'],asset_type=ref['asset_type'],status='LINKED',source=_asset_source(engine,ref['resolved_path'])))
    rehash(cgs)
    mapping.objects[key].world_binding=WorldBinding(mode['world']['contract']['objects'][0]['id'],actor['id'],0)
    (root/'game.cgs.json').write_bytes(canonical(cgs));host=NativeMaterializationHost(root,lambda:None,gateway)
    pair=SavedPair(root,mapping=mapping,expected_cgs=cgs,expected_normalized=rows,recapture=gateway.capture)
    request=TransactionRequest('explicit-fixture-baseline','a'*64,dict(canonical=dict(files=[file_change('game.cgs.json',sha(canonical(cgs)),canonical(cgs))]),native=dict(write_request=None)),ACTIVATION,dict(mapping=mapping.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows)),dict(cgs=cgs,normalized=rows,accepted_loss_digest=None))
    host._coordinator(pair).commit(request,authorize=lambda _:True)
    def context():
        current=load_json(root/'game.cgs.json');m=IdentityMap.from_dict(load_json(root/MAP));native=gateway.capture()
        return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load_json(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=current,native_inventory=native,expected_current_cgs_digest=digest(current),expected_source_digest=sha(native),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
    obj['asset_bindings']['project.visual.v1']['id']=replacement['asset_id'];rehash(cgs);(root/'game.cgs.json').write_bytes(canonical(cgs))
    host=NativeMaterializationHost(root,context,gateway);opened=host.review.open('proof');assert opened['report']['reviewable'],opened['report']['losses']
    (out/'review.json').write_bytes(canonical(opened));approval=host.review.approve('proof',opened['token'],opened['proposal_digest']);result=host.apply('proof',approval,approval['proposal_digest']);assert result['state']=='committed'
    final=json.loads(gateway.capture());assert final['objects'][key]['fields']['presentation.asset']==replacement
    repeated=NativeMaterializationHost(root,context,gateway).review.open('proof');assert repeated['report']['noop'] and repeated['report']['reviewable']
    m=IdentityMap.from_dict(load_json(root/MAP));raw=gateway.capture();base=reader.capture(raw,m,enable_writes=True).admit();target=json.loads(raw)
    target['objects'][key]['fields']['presentation.asset']=original
    desired=reader.capture(canonical(target),m,enable_writes=True).admit()
    native_request=json.loads(reader.write_request(raw,base,desired,m));prepared=gateway.prepare('explicit-native-fixture-edit',dict(write_request=native_request));gateway.commit(prepared)
    reverse=NativeMaterializationHost(root,context,gateway);opened=reverse.review.open('proof');assert opened['report']['reviewable'],opened['report']['losses']
    assert any(op['kind']=='set_native_presentation' for op in opened['report']['typed_operations']['operations'])
    (out/'reverse-review.json').write_bytes(canonical(opened));approval=reverse.review.approve('proof',opened['token'],opened['proposal_digest']);assert reverse.apply('proof',approval,approval['proposal_digest'])['state']=='committed'
    assert load_json(root/'game.cgs.json')['modes'][0]['world']['contract']['objects'][0]['asset_bindings']['project.visual.v1']['id']==original['asset_id']
    final=NativeMaterializationHost(root,context,gateway).review.open('proof');assert final['report']['noop']
    (out/'proof.json').write_bytes(canonical(dict(ok=True,engine=engine,production_host=True,real_native_editor=True,canonical_to_native_mesh=True,native_to_canonical_mesh=True,verified_saved_pair=True,cold_noop=True,runtime_activation=False)));print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),sys.argv[2] if len(sys.argv)>2 else 'unity')
