"""NEC-008 typed transform proposals, separate from durable publication."""
import copy
from .native_adoption_operations import digest, exact, require, identifier, index, AdoptionOperationResult
from ...cgs.cgs_serializer import CGSSerializer
from . import native_input_bindings

SCHEMA='xace.native_reconciliation_operations.v1'


def preview(batch, current, *, validate):
    exact(batch,{'schema','expected_cgs_digest','operations'})
    require(batch['schema']==SCHEMA and batch['expected_cgs_digest']==digest(current),'stale reconciliation CGS')
    require(callable(validate) and type(batch['operations']) is list and len(batch['operations'])<=128,'invalid reconciliation batch')
    native_input_bindings.validate(current)
    proposed=copy.deepcopy(current);ids=set()
    for op in batch['operations']:
        if op.get('kind')=='set_native_input':
            exact(op,{'operation_id','kind','binding_id','expected_binding_digest','engine','native_action'})
            oid=identifier(op['operation_id']);require(oid not in ids,'duplicate operation');ids.add(oid)
            bindings=index(native_input_bindings.validate(proposed),'binding_id')
            require(op['binding_id'] in bindings,'explicit input binding required');binding=bindings[op['binding_id']]
            require(digest(binding)==op['expected_binding_digest'],'stale input binding')
            require(op['engine'] in binding['native_actions'],'engine input enrollment required')
            binding['native_actions'][op['engine']]=op['native_action']
            native_input_bindings.validate(proposed);continue
        if op.get('kind')=='set_native_presentation':
            exact(op,{'operation_id','kind','mode_id','object_id','expected_object_digest','role','asset'})
            oid=identifier(op['operation_id']);require(oid not in ids,'duplicate operation');ids.add(oid)
            modes=index(proposed['modes']);require(op['mode_id'] in modes,'unknown mode')
            objects=index(modes[op['mode_id']].get('world',{}).get('contract',{}).get('objects',[]))
            require(op['object_id'] in objects,'unknown World object');obj=objects[op['object_id']]
            require(digest(obj)==op['expected_object_digest'],'stale World object')
            require(set(obj['asset_bindings'])=={op['role']},'explicit single presentation role required')
            ref=op['asset'];exact(ref,{'id','asset_type','status'})
            asset=index(proposed.get('assets',[])).get(ref['id'])
            require(asset is not None and ref=={k:asset[k] for k in ['id','asset_type','status']} and ref['asset_type']=='MESH' and ref['status']=='LINKED','registered linked mesh required')
            obj['asset_bindings'][op['role']]=copy.deepcopy(ref);continue
        if op.get('kind')=='set_native_playback':
            exact(op,{'operation_id','kind','binding_id','expected_binding_digest','binding'})
            oid=identifier(op['operation_id']);require(oid not in ids,'duplicate operation');ids.add(oid)
            bindings=index(proposed.get('semantic_bindings',{}).get('bindings',[]),'binding_id')
            require(op['binding_id'] in bindings,'unknown playback binding')
            previous=bindings[op['binding_id']];value=op['binding']
            require(digest(previous)==op['expected_binding_digest'],'stale playback binding')
            exact(value,set(previous));require(value['binding_id']==previous['binding_id'],'binding identity change refused')
            for key in previous:
                if key not in {'event_name','playback_kind','asset','parameters'}:require(value[key]==previous[key],'gameplay semantics require separate operation')
            exact(value['parameters'],set(previous['parameters']))
            for key in previous['parameters']:
                if key!='resource_path':require(value['parameters'][key]==previous['parameters'][key],'playback parameter semantics changed')
            require(value['event_name'] in {e['name'] for e in proposed.get('semantic_events',[])},'undeclared playback event')
            ref=value['asset'];exact(ref,{'id','asset_type','status'})
            asset=index(proposed.get('assets',[])).get(ref['id'])
            require(asset is not None and asset['status']=='LINKED' and ref['status']=='Linked','registered linked playback asset required')
            require(ref['asset_type']==''.join(part.title() for part in asset['asset_type'].split('_')),'playback asset type mismatch')
            expected={'Animation':{'ANIMATION_CLIP','ANIMATION_CONTROLLER'},'Audio':{'AUDIO_CLIP'}}
            require(asset['asset_type'] in expected.get(value['playback_kind'],set()),'playback kind/type mismatch')
            previous.clear();previous.update(copy.deepcopy(value));continue
        exact(op,{'operation_id','kind','mode_id','actor_id','expected_actor_digest','transform'})
        oid=identifier(op['operation_id']);require(oid not in ids,'duplicate operation');ids.add(oid)
        require(op['kind']=='set_native_transform','unsupported reconciliation operation')
        modes=index(proposed['modes']);require(op['mode_id'] in modes,'unknown mode')
        actors=index(modes[op['mode_id']]['actors']);require(op['actor_id'] in actors,'unknown actor')
        actor=actors[op['actor_id']];require(digest(actor)==op['expected_actor_digest'],'stale actor')
        transform=op['transform'];exact(transform,{'position','rotation','scale','parent_entity_id'})
        require(type(transform['parent_entity_id']) is int and transform['parent_entity_id']==0,'runtime parent binding unproved')
        for name,axes in [('position','xyz'),('rotation','xyzw'),('scale','xyz')]:
            exact(transform[name],set(axes))
            require(all(type(v) is int and -(2**63)<=v<2**63 for v in transform[name].values()),'invalid fixed64 transform')
        components=index(actor['components'],'type_id');require(1 in components,'missing transform')
        components[1]['defaults']=copy.deepcopy(transform)
    changed=proposed!=current
    if changed:
        unhashed=copy.deepcopy(proposed);unhashed['metadata'].pop('cgs_hash',None)
        proposed['metadata']['cgs_hash']=CGSSerializer.compute_hash(unhashed)
    native_input_bindings.validate(proposed)
    validate(copy.deepcopy(proposed))
    return AdoptionOperationResult(proposed,digest(batch),changed)
