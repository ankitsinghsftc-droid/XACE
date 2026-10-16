"""NEC-008 typed transform proposals, separate from durable publication."""
import copy
from .native_adoption_operations import digest, exact, require, identifier, index, AdoptionOperationResult
from ...cgs.cgs_serializer import CGSSerializer

SCHEMA='xace.native_reconciliation_operations.v1'


def preview(batch, current, *, validate):
    exact(batch,{'schema','expected_cgs_digest','operations'})
    require(batch['schema']==SCHEMA and batch['expected_cgs_digest']==digest(current),'stale reconciliation CGS')
    require(callable(validate) and type(batch['operations']) is list and len(batch['operations'])<=128,'invalid reconciliation batch')
    proposed=copy.deepcopy(current);ids=set()
    for op in batch['operations']:
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
    validate(copy.deepcopy(proposed))
    return AdoptionOperationResult(proposed,digest(batch),changed)
