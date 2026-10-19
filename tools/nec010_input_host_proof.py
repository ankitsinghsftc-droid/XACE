"""Real explicit input-selector reconciliation through the production host."""
import copy,json,shutil,sys,importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from test_native_playback_reconciliation import context as fixture_context
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
    else:
        assert engine=='godot'
        source=ROOT/'evidence/nec010/20261017/godot-mapped-preservation-a/godot-project';addon='addons/xace_authoring'
        roots=['Fixture','addons','project.godot','xace_protocol.gd','xace_protocol.gd.uid'];docs=['res://Fixture/Template.tscn','res://Fixture/World.tscn']
        shutil.copytree(source/'Fixture',root/'Fixture')
        for name in ['project.godot','xace_protocol.gd','xace_protocol.gd.uid']:shutil.copyfile(source/name,root/name)
        shutil.copytree(ROOT/'adapters/godot/authoring',root/addon,ignore=shutil.ignore_patterns('*proof*'))
        exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe');key=f'{3:032x}'
    pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/addon).rglob('*') if p.is_file() and p.suffix!='.meta'}
    gateway=NativeEditorGateway(root,engine=engine,executable=str(exe),executable_sha256=sha(exe.read_bytes()),documents=docs,source_roots=roots,plugin_hashes=pins,trusted_closed_project=True)
    data=gateway.capture();mapping=reader.prepare_identity_map(data,project_id='input-host',branch_id='b'*32);snapshot=reader.capture(data,mapping,enable_writes=True).admit()
    rows=snapshot.to_dict()['inspection']['normalized'];fields=rows[key]['fields'];playback=fields['binding.playback']
    cgs=fixture_context(engine)['current_cgs'];mode=cgs['modes'][0];actor=mode['actors'][0];mode['actors']=[actor];mode['world']['contract']['objects']=mode['world']['contract']['objects'][:1]
    transform=actor['components'][0]['defaults']
    for name in ['position','rotation','scale']:transform[name]={a:int(v) for a,v in fields['transform.'+name].items()}
    ref=playback['asset'];cgs['assets']=[dict(id=ref['asset_id'],asset_type=ref['asset_type'],status='LINKED',source=ref['resolved_path'][6:] if engine=='godot' else ref['resolved_path'])]
    cgs['semantic_events']=[dict(name=n,payload_fields=[],version='1.0.0') for n in [playback['event_name'],'actor.reviewed']]
    binding=cgs['semantic_bindings']['bindings'][0];binding.update(binding_id=playback['binding_id'],event_name=playback['event_name'],playback_kind=playback['playback_kind'],asset=dict(id=ref['asset_id'],asset_type='AnimationClip',status='Linked'));binding['parameters']['resource_path']=ref['resolved_path'];rehash(cgs)
    original_input=fields['input.action'];replacement_input='Vertical' if engine=='unity' else 'jump'
    actor['components'].append(dict(type_id=6,name='COMP_INPUT_V1',defaults=dict(controller_id=1,control_type='HUMAN',input_profile_id='explicit.input.v1')))
    cgs['input_profiles']=[dict(id='explicit.input.v1',schema='xace.input_profile.v1',network_ready=True,actions=[dict(id='move',kind='axis2',packet_fields=['move_x','move_z'])])]
    cgs['native_input_bindings']=dict(schema='xace.native_input_bindings.v1',bindings=[dict(binding_id='input.player',mode_id=mode['id'],world_object_id=mode['world']['contract']['objects'][0]['id'],input_profile_id='explicit.input.v1',action_id='move',native_actions={engine:original_input})]);rehash(cgs)
    mapping.objects[key].world_binding=WorldBinding(mode['world']['contract']['objects'][0]['id'],actor['id'],0)
    (root/'game.cgs.json').write_bytes(canonical(cgs));host=NativeMaterializationHost(root,lambda:None,gateway)
    pair=SavedPair(root,mapping=mapping,expected_cgs=cgs,expected_normalized=rows,recapture=gateway.capture)
    request=TransactionRequest('explicit-fixture-baseline','a'*64,dict(canonical=dict(files=[file_change('game.cgs.json',sha(canonical(cgs)),canonical(cgs))]),native=dict(write_request=None)),ACTIVATION,dict(mapping=mapping.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows)),dict(cgs=cgs,normalized=rows,accepted_loss_digest=None))
    host._coordinator(pair).commit(request,authorize=lambda _:True)
    def context():
        current=load_json(root/'game.cgs.json');m=IdentityMap.from_dict(load_json(root/MAP));native=gateway.capture()
        return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load_json(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=current,native_inventory=native,expected_current_cgs_digest=digest(current),expected_source_digest=sha(native),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
    cgs['native_input_bindings']['bindings'][0]['native_actions'][engine]=replacement_input;rehash(cgs);(root/'game.cgs.json').write_bytes(canonical(cgs))
    host=NativeMaterializationHost(root,context,gateway);opened=host.review.open('proof');assert opened['report']['reviewable'],opened['report']['losses']
    (out/'review.json').write_bytes(canonical(opened));approval=host.review.approve('proof',opened['token'],opened['proposal_digest']);result=host.apply('proof',approval,approval['proposal_digest']);assert result['state']=='committed'
    final=json.loads(gateway.capture());assert final['objects'][key]['fields']['input.action']==replacement_input
    repeated=NativeMaterializationHost(root,context,gateway).review.open('proof');assert repeated['report']['noop'] and repeated['report']['reviewable']
    m=IdentityMap.from_dict(load_json(root/MAP));raw=gateway.capture();base=reader.capture(raw,m,enable_writes=True).admit();target=json.loads(raw)
    target['objects'][key]['fields']['input.action']=original_input
    desired=reader.capture(canonical(target),m,enable_writes=True).admit()
    native_request=json.loads(reader.write_request(raw,base,desired,m));prepared=gateway.prepare('explicit-native-fixture-edit',dict(write_request=native_request));gateway.commit(prepared)
    reverse=NativeMaterializationHost(root,context,gateway);opened=reverse.review.open('proof');assert opened['report']['reviewable'],opened['report']['losses']
    assert any(op['kind']=='set_native_input' for op in opened['report']['typed_operations']['operations'])
    (out/'reverse-review.json').write_bytes(canonical(opened));approval=reverse.review.approve('proof',opened['token'],opened['proposal_digest']);assert reverse.apply('proof',approval,approval['proposal_digest'])['state']=='committed'
    assert load_json(root/'game.cgs.json')['native_input_bindings']['bindings'][0]['native_actions'][engine]==original_input
    final=NativeMaterializationHost(root,context,gateway).review.open('proof');assert final['report']['noop']
    (out/'proof.json').write_bytes(canonical(dict(ok=True,engine=engine,production_host=True,real_native_editor=True,canonical_to_native_input_selector=True,native_to_canonical_input_selector=True,runtime_input_execution=False,verified_saved_pair=True,cold_noop=True,runtime_activation=False)));print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),sys.argv[2] if len(sys.argv)>2 else 'unity')
