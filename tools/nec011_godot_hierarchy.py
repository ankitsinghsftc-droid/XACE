"""Installed-editor static hierarchy round trip through the production host."""
import copy,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(ROOT/'packages/project-system/tests')]
from tools.nec010_playback_host_proof import NativeEditorGateway,NativeMaterializationHost,IdentityMap,WorldBinding,canonical,sha,load_json,TransactionRequest,file_change,ACTIVATION,SavedPair,MAP,CGS,NATIVE,verify_baseline_receipts,Snapshot,digest,rehash
from test_native_adoption import inputs,plan,actor_id,oid
from native_instance_transforms import PROFILE
import godot_authoring as reader

def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists();root=out/'project';root.mkdir(parents=True)
    addon='addons/xace_authoring';shutil.copytree(ROOT/'adapters/godot/authoring',root/addon,ignore=shutil.ignore_patterns('*proof*'))
    shutil.copyfile(ROOT/'adapters/godot/xace_protocol.gd',root/'xace_protocol.gd')
    (root/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC011 Static Hierarchy"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    def identity(n,kind):return json.dumps(dict(authoring_id=oid(n),generation='1',kind=kind,local_id=oid(1000+n),namespace_id=oid(100),prefab_id=None))
    (root/'Fixture').mkdir()
    scene='[gd_scene format=3 uid="uid://2bmadhhkmmqv"]\n[node name="World" type="Node"]\nmetadata/xace_identity_v1 = '+identity(1,'scene')+'\n[node name="Parent" type="Node3D" parent="."]\nposition = Vector3(2, 0, 0)\nmetadata/xace_identity_v1 = '+identity(2,'object')+'\n[node name="Child" type="Node3D" parent="Parent"]\nposition = Vector3(1, 0, 0)\nmetadata/xace_identity_v1 = '+identity(3,'object')+'\n'
    (root/'Fixture/World.tscn').write_text(scene)
    exe=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
    pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in (root/addon).rglob('*') if p.is_file()}
    gateway=NativeEditorGateway(root,engine='godot',executable=str(exe),executable_sha256=sha(exe.read_bytes()),documents=['res://Fixture/World.tscn'],source_roots=['Fixture','addons','project.godot','xace_protocol.gd'],plugin_hashes=pins,trusted_closed_project=True)
    roundtrip(out,root,gateway,"godot","Fixture/World.tscn")

def roundtrip(out,root,gateway,engine,scene_path):
    import importlib
    reader=importlib.import_module(engine+"_authoring")
    raw=gateway.capture();mapping=reader.prepare_identity_map(raw,project_id='nec011-hierarchy',branch_id='b'*32);snapshot=reader.capture(raw,mapping,enable_writes=True).admit();rows=snapshot.to_dict()['inspection']['normalized']
    _,_,cgs,selection,choices=inputs(engine);cgs['native_instance_profile']=PROFILE;rehash(cgs)
    adopted=plan(raw,mapping,cgs,selection,choices).to_dict();(out/'adoption.json').write_bytes(canonical(adopted));assert adopted['candidate_valid'],adopted['losses'];cgs=adopted['proposed_cgs']
    for key in selection:mapping.objects[key].world_binding=WorldBinding(actor_id(mapping,key),actor_id(mapping,key),0)
    (root/'game.cgs.json').write_bytes(canonical(cgs));host=NativeMaterializationHost(root,lambda:None,gateway)
    pair=SavedPair(root,mapping=mapping,expected_cgs=cgs,expected_normalized=rows,recapture=gateway.capture)
    request=TransactionRequest('explicit-fixture-baseline','a'*64,dict(canonical=dict(files=[file_change('game.cgs.json',sha(canonical(cgs)),canonical(cgs))]),native=dict(write_request=None)),ACTIVATION,dict(mapping=mapping.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows)),dict(cgs=cgs,normalized=rows,accepted_loss_digest=None))
    host._coordinator(pair).commit(request,authorize=lambda _:True)
    def context():
        current=load_json(root/'game.cgs.json');m=IdentityMap.from_dict(load_json(root/MAP));native=gateway.capture()
        return dict(baseline=Snapshot((root/NATIVE).read_bytes()),baseline_cgs=load_json(root/CGS),mapping=m,current_mapping=copy.deepcopy(m),current_cgs=current,native_inventory=native,expected_current_cgs_digest=digest(current),expected_source_digest=sha(native),verify_baseline=lambda b:verify_baseline_receipts(root,b),trusted_project=True)
    def apply():
        host=NativeMaterializationHost(root,context,gateway);opened=host.review.open('proof');assert opened['report']['reviewable'],opened['report']['losses'];approval=host.review.approve('proof',opened['token'],opened['proposal_digest']);assert host.apply('proof',approval,approval['proposal_digest'])['state']=='committed'
    # Engine-local child edit through the real native writer.
    m=IdentityMap.from_dict(load_json(root/MAP));raw=gateway.capture();base=reader.capture(raw,m,enable_writes=True).admit();target=json.loads(raw);axis='y' if engine=='unreal' else 'x';target['objects'][oid(3)]['fields']['transform.position'][axis]='400' if engine=='unreal' else '4'
    desired=reader.capture(canonical(target),m,enable_writes=True).admit();prepared=gateway.prepare('native-child-edit',dict(write_request=json.loads(reader.write_request(raw,base,desired,m))));gateway.commit(prepared);apply()
    cgs=load_json(root/'game.cgs.json');actors={a['id']:a for a in cgs['modes'][0]['actors']};child=actors[actor_id(mapping,oid(3))]['components'][0]['defaults'];assert child['position']['x']==6000000 and child['parent_entity_id']==0
    # Canonical world child edit must preserve native parent and write local space.
    child['position']['x']=7000000;rehash(cgs);(root/'game.cgs.json').write_bytes(canonical(cgs));apply();final=json.loads(gateway.capture());assert final['objects'][oid(3)]['parent_id']==oid(2);assert final['objects'][oid(3)]['fields']['transform.position'][axis]==('500' if engine=='unreal' else '5')
    repeated=NativeMaterializationHost(root,context,gateway).review.open('proof');assert repeated['report']['noop'] and repeated['report']['reviewable']
    monitor=NativeMaterializationHost(root,context,gateway)
    before={name:(root/name).read_bytes() for name in ['game.cgs.json',scene_path,MAP,CGS,NATIVE]}
    notifications=[monitor.poll_saved_changes()['state'] for _ in range(3)]
    assert notifications==['waiting','review_available','unchanged'],notifications
    assert not monitor.review._sessions
    assert before=={name:(root/name).read_bytes() for name in before}
    (out/'proof.json').write_bytes(canonical(dict(ok=True,engine=engine,real_native_editor=True,production_host=True,native_local_to_canonical_world=True,canonical_world_to_native_local=True,parent_identity_preserved=True,cold_noop=True,profile=PROFILE,runtime_parenting=False,native_saved_change_batching=notifications,monitor_published=False)))
    print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
