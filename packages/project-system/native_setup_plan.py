"""Source-bound new-project setup contract; no source or engine writes.

The initial setup profile admits explicit, single-instance root World objects.
Native serialization happens in a registered editor factory. Captured native
identities and exact canonical transforms must match this plan before review.
"""
import copy
from dataclasses import dataclass
from authoring_identity import canonical,digest,opaque_id,require,WorldBinding
from native_adoption import factory,bridge
from tools.cgs_schema_validate import compute_cgs_hash


@dataclass(frozen=True)
class NativeSetupPlan:
    payload: bytes
    @property
    def sha256(self):return digest(self.to_dict())
    def to_dict(self):
        import json
        return json.loads(self.payload)


def plan_setup(cgs,*,engine,namespace_id,project_id,branch_id,mode_id,playback_bindings=None):
    require(engine in {'unity','unreal','godot'},'unsupported setup engine')
    opaque_id(namespace_id);opaque_id(branch_id)
    require(cgs['metadata']['cgs_hash']==compute_cgs_hash(cgs),'invalid source CGS hash')
    factory.compile_portable_cgs(cgs)
    modes=[m for m in cgs['modes'] if m['id']==mode_id]
    require(len(modes)==1,'select one existing mode')
    mode=modes[0];objects=mode.get('world',{}).get('contract',{}).get('objects',[])
    require(0<len(objects)<=128,'setup requires1..128 explicit World objects')
    playback_bindings={} if playback_bindings is None else copy.deepcopy(playback_bindings)
    require(type(playback_bindings) is dict and set(playback_bindings)<={o['id'] for o in objects},'explicit setup playback World bindings required')
    require(all(type(v) is str for v in playback_bindings.values()) and len(set(playback_bindings.values()))==len(playback_bindings),'ambiguous setup playback binding')
    from native_reconciliation_plan import _presentation,_playback,gde
    scene_id=digest(dict(namespace=namespace_id,kind='scene',mode=mode_id))[:32]
    def identity(key,kind):
        value=dict(namespace_id=namespace_id,authoring_id=key,generation='1',kind=kind)
        if engine=='unreal':value['schema']='xace.native_identity.v1'
        else:value['prefab_id']=None
        if engine=='godot':value['local_id']=digest(dict(namespace=namespace_id,local=key))[:32]
        return value
    rows=[];bindings={};seen=set()
    for obj in sorted(objects,key=lambda v:v['id']):
        actors=[a for a in mode['actors'] if a['id']==obj['actor_id']]
        require(len(actors)==1 and actors[0]['spawn_count']==1 and obj['instance_index']==0,'ambiguous native instance')
        actor=actors[0];require(actor['id'] not in seen,'duplicate actor instance');seen.add(actor['id'])
        components=[c for c in actor['components'] if c['type_id']==1]
        require(len(components)==1,'explicit transform required');transform=components[0]['defaults']
        require(transform['parent_entity_id']==0 and not obj.get('relationships',{}).get('xace.authoring_parent.v1'),'root transform setup profile required')
        require(all(type(v) is int for name in ['position','rotation','scale'] for v in transform[name].values()),'fixed-point transform required')
        key=digest(dict(namespace=namespace_id,world_object=obj['id']))[:32]
        fields={'transform.'+name:{axis:str(value) for axis,value in transform[name].items()} for name in ['position','rotation','scale']}
        roles=obj.get('asset_bindings',{})
        if roles:
            require(len(roles)==1,'setup supports one explicit mesh presentation role')
            ref=next(iter(roles.values()))
            if ref.get('status')=='LINKED':fields['presentation.asset']=_presentation(cgs,obj,engine,dict(asset_id='',resolved_path=''))
            else:require(ref.get('status')=='PLACEHOLDER','setup resource is missing or unresolved')
        input_binding=gde.native_input_bindings.for_object(cgs,mode_id,obj['id'],engine)
        if input_binding:fields['input.action']=input_binding['native_actions'][engine]
        if obj['id'] in playback_bindings:fields['binding.playback']=_playback(cgs,playback_bindings[obj['id']],engine)
        rows.append(dict(identity=identity(key,'object'),name=actor['id'][:128],fields=fields))
        bindings[key]=dict(world_object_id=obj['id'],actor_id=actor['id'],instance_index=0)
    require(seen=={a['id'] for a in mode['actors']},'every actor must have an explicit World instance')
    spec=dict(schema='xace.'+engine+'_native_setup.v1',scene=identity(scene_id,'scene'),objects=rows)
    result=dict(schema='xace.native_setup_plan.v1',engine=engine,project_id=project_id,branch_id=branch_id,namespace_id=namespace_id,mode_id=mode_id,cgs_digest=digest(cgs),native_request=spec,bindings=bindings,scope='single_instance_root_world_objects',runtime_activation=False)
    if playback_bindings:result['playback_bindings']=playback_bindings
    return NativeSetupPlan(canonical(result))


def verify_setup(plan,cgs,native_inventory):
    data=plan.to_dict()
    expected=plan_setup(cgs,engine=data['engine'],namespace_id=data['namespace_id'],project_id=data['project_id'],branch_id=data['branch_id'],mode_id=data['mode_id'],playback_bindings=data.get('playback_bindings'))
    require(expected.payload==plan.payload,'setup plan/source changed')
    reader=bridge(data['engine']);mapping=reader.prepare_identity_map(native_inventory,project_id=data['project_id'],branch_id=data['branch_id'])
    require(mapping.namespace_id==data['namespace_id'],'foreign generated namespace')
    require(set(mapping.objects)==set(data['bindings'])|{data['native_request']['scene']['authoring_id']},'generated object set differs from plan')
    snapshot=reader.capture(native_inventory,mapping,enable_writes=True).admit();rows=snapshot.to_dict()['inspection']['normalized']
    for obj in data['native_request']['objects']:
        key=obj['identity']['authoring_id'];actual=rows[key]
        require(not actual['deleted'] and actual['parent_id'] is None,'unexpected generated hierarchy')
        require({field:actual['fields'].get(field) for field in obj['fields']}==obj['fields'],'generated transform differs from CGS')
        mapping.objects[key].world_binding=WorldBinding(**data['bindings'][key])
    mapping.validate()
    from native_reconciliation_plan import _project
    require(_project(cgs,rows,mapping)==rows,'generated CGS/native projection differs')
    return mapping,copy.deepcopy(rows)
