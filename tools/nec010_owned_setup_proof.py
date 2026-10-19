"""Reviewed new-project publication with explicit owned resources and declarations."""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from native_setup_plan import plan_setup
from native_setup_factory import create_native_setup_stage
from native_setup_review import NativeSetupReview
from native_editor_gateway import NativeEditorGateway
from native_materialization import NativeMaterializationHost
from authoring_identity import canonical,IdentityMap
from authoring_saved_pair import MAP,NATIVE,verify_baseline_receipts
from authoring_transaction_files import sha
from native_adoption import _asset_source
from tools.world_extensibility_proof import rehash
from nec010_editor_gateway_proof import EXES

def main(engine,out):
    assert engine in ['unity','godot','unreal'] and out.is_relative_to(ROOT/'evidence/nec010') and not out.exists()
    out.mkdir(parents=True);source=ROOT/'evidence/nec010/20261019'/('unreal-bindings-a' if engine=='unreal' else engine+'-input-a')/(engine+'-project')
    cgs=json.loads((source/'game.cgs.json').read_text());snapshot=json.loads((source/NATIVE).read_bytes());rows=snapshot['inspection']['normalized']
    meshes={canonical(r['fields']['presentation.asset']) for r in rows.values() if 'presentation.asset' in r['fields']};assert len(meshes)==1
    ref=json.loads(next(iter(meshes)));obj=cgs['modes'][0]['world']['contract']['objects'][0]
    cgs['assets'].append(dict(id=ref['asset_id'],asset_type='MESH',status='LINKED',source=_asset_source(engine,ref['resolved_path'])))
    obj['asset_bindings']={'project.visual.v1':dict(id=ref['asset_id'],asset_type='MESH',status='LINKED')};rehash(cgs)
    links={obj['id']:cgs['semantic_bindings']['bindings'][0]['binding_id']}
    plan=plan_setup(cgs,engine=engine,namespace_id='e'*32,project_id='owned-setup-proof',branch_id='b'*32,mode_id=cgs['modes'][0]['id'],playback_bindings=links)
    if engine=='unity':roots=['Assets','Packages','ProjectSettings'];addon='Assets/XaceAuthoring';docs=['Assets/XACEGenerated/World.unity'];code=ROOT/'adapters/unity/Authoring'
    elif engine=='godot':roots=['Fixture','addons','project.godot','xace_protocol.gd','xace_protocol.gd.uid'];addon='addons/xace_authoring';docs=['res://XACEGenerated/World.tscn'];code=ROOT/'adapters/godot/authoring'
    else:roots=['Config','Content','Plugins','NEC006.uproject'];addon='Plugins/XACEAuthoring';docs=['/Game/XACEGenerated/World'];code=ROOT/'adapters/unreal/Authoring'
    files={}
    for relative in roots:
        path=source/relative
        for p in ([path] if path.is_file() else path.rglob('*')):
            name=p.relative_to(source).as_posix()
            if p.is_file() and '__xaceauthoringstage' not in name.lower() and (engine=='unreal' or 'proof' not in name.lower()) and 'Intermediate' not in p.parts and p.suffix!='.pdb':files[name]=p.read_bytes()
    for p in code.rglob('*'):
        if p.is_file() and (engine=='unreal' or 'proof' not in p.name.lower()):
            name=addon+'/'+p.relative_to(code).as_posix()
            if engine=='unreal':assert files[name]==p.read_bytes(),'Compiled setup source mismatch'
            else:files[name]=p.read_bytes()
    if engine=='godot':roots.append('XACEGenerated')
    config=dict(engine=engine,executable=str(EXES[engine]),executable_sha256=sha(EXES[engine].read_bytes()),documents=docs,source_roots=roots,plugin_hashes={p:sha(b) for p,b in files.items() if p.startswith(addon+'/') and not p.endswith('.meta')},project_file="NEC006.uproject" if engine=="unreal" else None,trusted_closed_project=True)
    (out/'source.cgs.json').write_bytes(canonical(cgs));(out/'setup-plan.json').write_bytes(plan.payload);(out/'gateway-config.json').write_bytes(canonical(config))
    stage=create_native_setup_stage(plan,cgs,out/'native-stage',template_files=files,gateway_config=config)
    assert all({'presentation.asset','input.action','binding.playback'}<=set(r['fields']) for r in plan.to_dict()['native_request']['objects'])
    root=out/'published-project';root.mkdir();(root/'game.cgs.json').write_bytes(canonical(cgs))
    gateway=NativeEditorGateway(root,**config);host=NativeMaterializationHost(root,lambda:None,gateway);review=NativeSetupReview(host,stage)
    opened=review.open('proof');(out/'review.json').write_bytes(canonical(opened));approval=review.approve('proof',opened['token'],opened['proposal_digest'])
    result=review.apply('proof',approval['token'],approval['proposal_digest'],approval['approval']);assert result['state']=='committed'
    assert gateway.capture()==stage.inventory
    mapping=IdentityMap.from_dict(json.loads((root/MAP).read_text()));assert verify_baseline_receipts(root,mapping.baseline)
    assert not NativeMaterializationHost(root,lambda:None,NativeEditorGateway(root,**config)).status()['play_build_blocked']
    try:review.open('proof')
    except ValueError:pass
    else:raise AssertionError('Existing project must not be replaced')
    report=dict(ok=True,engine=engine,production_factory=True,explicit_playback_association=True,owned_mesh=True,owned_input_selector=True,owned_playback_declaration=True,separate_approval=True,verified_saved_pair=True,cold_capture_identical=True,existing_content_refused=True,runtime_activation=False,runtime_playback_or_input_execution=False)
    (out/'proof.json').write_bytes(canonical(report));print(json.dumps(report))
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]).resolve())
