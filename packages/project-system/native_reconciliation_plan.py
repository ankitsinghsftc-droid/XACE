"""Host-bound NEC-008 CGS/native reconciliation previews.

No baseline is established here. The caller supplies a verified NEC-002 baseline
and an out-of-band receipt verifier. Native documents are never written.
"""
from native_authoring_limits import MAX_BOUND_OBJECTS
import copy
import hashlib
import importlib
from decimal import Decimal

from authoring_identity import IdentityMap, canonical, require
from native_authoring_contract import Snapshot, load_snapshot, parse
from native_reconciliation import reconcile_records, MergeProposal
from native_adoption import bridge, digest, encode, factory, _asset_source
from tools.cgs_schema_validate import compute_cgs_hash

gde=importlib.import_module('gde.src.domain_dsl.typed_operations.native_reconciliation_operations')
PARENT='xace.authoring_parent.v1'
TRANSFORMS={'transform.position','transform.rotation','transform.scale'}
from native_instance_transforms import PROFILE as HIERARCHY_PROFILE, resolve as resolve_hierarchy, localize as localize_hierarchy

def hierarchy_enabled(cgs):
    value=cgs.get('native_instance_profile')
    require(value is None or value==HIERARCHY_PROFILE,'Unsupported native instance profile')
    return value==HIERARCHY_PROFILE

def row_transforms(rows,keys):
    return {key:dict(**{name:{a:int(v) for a,v in rows[key]['fields']['transform.'+name].items()} for name in ['position','rotation','scale']},parent_entity_id=0) for key in keys}



def _binding(cgs, binding):
    found=[]
    for mode in cgs['modes']:
        for obj in mode.get('world',{}).get('contract',{}).get('objects',[]):
            if obj['id']==binding.world_object_id:
                require(obj['actor_id']==binding.actor_id and obj['instance_index']==binding.instance_index,'World binding identity changed')
                actors=[a for a in mode['actors'] if a['id']==binding.actor_id]
                require(len(actors)==1 and actors[0]['spawn_count']==1 and binding.instance_index==0,'ambiguous actor instance')
                found.append((mode,actors[0],obj))
    require(len(found)<=1,'ambiguous World binding');return found[0] if found else None


def _playback(cgs,binding_id,engine):
    bindings=[b for b in cgs.get('semantic_bindings',{}).get('bindings',[]) if b['binding_id']==binding_id]
    require(len(bindings)==1,'explicit canonical playback binding required')
    binding=bindings[0];ref=binding['asset'];assets=[a for a in cgs.get('assets',[]) if a['id']==ref['id']]
    require(len(assets)==1,'registered playback asset required');asset=assets[0]
    path=binding.get('parameters',{}).get('resource_path')
    require(asset['status']=='LINKED' and ref['status']=='Linked' and asset.get('source')==_asset_source(engine,path),'playback resource registration disagrees')
    require(ref['asset_type']==''.join(p.title() for p in asset['asset_type'].split('_')),'playback asset type mismatch')
    return dict(binding_id=binding_id,event_name=binding['event_name'],playback_kind=binding['playback_kind'],asset=dict(asset_id=asset['id'],asset_type=asset['asset_type'],status='LINKED',resolved_path=path))


def _presentation(cgs,obj,engine,previous):
    roles=obj.get('asset_bindings',{})
    require(len(roles)==1,'explicit single presentation role required')
    ref=next(iter(roles.values()));assets=[a for a in cgs.get('assets',[]) if a['id']==ref['id']]
    require(len(assets)==1,'registered presentation asset required');asset=assets[0]
    require(ref=={k:asset[k] for k in ['id','asset_type','status']} and ref['asset_type']=='MESH' and ref['status']=='LINKED','linked mesh presentation profile required')
    source=asset.get('source');require(type(source) is str,'saved native mesh source required')
    if previous['asset_id']==ref['id']:path=previous['resolved_path']
    elif engine=='godot':path='res://'+source
    elif engine=='unity':path=source
    else:
        require(source.startswith('Content/') and source.endswith('.uasset'),'Unreal project mesh package required')
        package=source[len('Content/'):-len('.uasset')];path='/Game/'+package+'.'+package.rsplit('/',1)[-1]
    require(_asset_source(engine,path)==source,'registered mesh source differs')
    return dict(asset_id=ref['id'],asset_type='MESH',status='LINKED',resolved_path=path)


def _project(cgs,base,mapping):
    rows=copy.deepcopy(base)
    by_world={r.world_binding.world_object_id:k for k,r in mapping.objects.items() if r.world_binding}
    for key,record in mapping.objects.items():
        if not record.world_binding:continue
        require(key in rows,'bound object outside capture')
        found=_binding(cgs,record.world_binding)
        if found is None:
            rows[key]=dict(generation=rows[key]['generation'],deleted=True,parent_id=None,fields={},dependencies=[],opaque=[]);continue
        mode,actor,obj=found
        components=[c for c in actor['components'] if c['type_id']==1]
        require(len(components)==1,'bound actor needs one transform')
        value=components[0]['defaults'];require(value['parent_entity_id']==0,'runtime parent identity cannot be projected')
        for name in ['position','rotation','scale']:
            require(all(type(v) is int for v in value[name].values()),'structured fixed-point transform required')
            rows[key]['fields']['transform.'+name]={axis:str(v) for axis,v in value[name].items()}
        input_binding=gde.native_input_bindings.for_object(cgs,mode['id'],obj['id'],mapping.engine)
        if input_binding:
            require('input.action' in rows[key]['fields'],'native input selector enrollment required')
            rows[key]['fields']['input.action']=input_binding['native_actions'][mapping.engine]
        if 'presentation.asset' in rows[key]['fields'] and obj.get('asset_bindings'):
            rows[key]['fields']['presentation.asset']=_presentation(cgs,obj,mapping.engine,rows[key]['fields']['presentation.asset'])
        if 'binding.playback' in rows[key]['fields']:
            rows[key]['fields']['binding.playback']=_playback(cgs,rows[key]['fields']['binding.playback']['binding_id'],mapping.engine)
        parents=obj.get('relationships',{}).get(PARENT,[])
        require(len(parents)<=1 and all(p in by_world for p in parents),'unbound semantic parent')
        rows[key]['parent_id']=by_world[parents[0]] if parents else None
    if hierarchy_enabled(cgs):
        keys=sorted(by_world.values())
        require(all(not rows[k]['deleted'] for k in keys),'Hierarchy deletion needs explicit structural review')
        local=localize_hierarchy(row_transforms(rows,keys),{k:rows[k]['parent_id'] for k in keys})
        for key,value in local.items():
            for name in ['position','rotation','scale']:rows[key]['fields']['transform.'+name]={a:str(v) for a,v in value[name].items()}
    return rows


def _native_transform(engine,field,value):
    # Exact inverse of NEC-003 coordinate normalization, without binary floats.
    kind=field.split('.')[1];axes='xyzw' if kind=='rotation' else 'xyz'
    n=[Decimal(value[k])/Decimal(1000000) for k in axes]
    if engine=='unity':
        if kind=='position':n[2]=-n[2]
        elif kind=='rotation':n[0]=-n[0];n[1]=-n[1]
    elif engine=='unreal':
        x,y,z=n[:3]
        if kind=='rotation':n=[z,-x,-y,n[3]]
        else:n=[-z if kind=='position' else z,x,y]
        if kind=='position':n=[v*100 for v in n]
    return {k:format(v,'f') if v else '0' for k,v in zip(axes,n)}


def plan_reconciliation(*, baseline:Snapshot, baseline_cgs:dict, mapping:IdentityMap,
                        current_mapping:IdentityMap, current_cgs:dict, native_inventory:bytes,
                        expected_current_cgs_digest:str, expected_source_digest:str,
                        verify_baseline, trusted_project:bool, resolutions:dict|None=None,
                        accepted_loss_digest=None, trusted_executor=None) -> MergeProposal:
    require(trusted_project is True,'trusted native extraction required')
    mapping.validate();current_mapping.validate()
    require(mapping.to_dict()==current_mapping.to_dict(),'branch/identity/baseline drift requires explicit identity review')
    require(current_cgs.get('native_instance_profile')==baseline_cgs.get('native_instance_profile'),'Instance profile changes need explicit re-adoption')
    hierarchy=hierarchy_enabled(current_cgs)
    saved=mapping.baseline;require(saved is not None,'verified reconciliation baseline required')
    require(saved.mapping_digest==mapping.mapping_digest() and saved.cgs_digest==digest(baseline_cgs)
            and saved.native_snapshot_digest==baseline.sha256,'baseline identity mismatch')
    require(callable(verify_baseline) and verify_baseline(copy.deepcopy(saved)) is True,'baseline receipts not verified by host')
    require(digest(current_cgs)==expected_current_cgs_digest,'stale current CGS')
    require(hashlib.sha256(native_inventory).hexdigest()==expected_source_digest,'stale native source')
    for cgs in [baseline_cgs,current_cgs]:
        require(cgs.get('metadata',{}).get('cgs_hash')==compute_cgs_hash(cgs),'invalid CGS hash')
        factory.compile_portable_cgs(cgs)
    reader=bridge(mapping.engine);policy=reader.policy(enable_writes=True)
    before=load_snapshot(baseline.payload,mapping,policy).to_dict()['inspection']['normalized']
    require(_project(baseline_cgs,before,mapping)==before,'baseline canonical/native projection disagrees')
    bound=[k for k,r in mapping.objects.items() if r.world_binding]
    require(0<len(bound)<=MAX_BOUND_OBJECTS,'select 1..1000 verified instance bindings')
    inspection=reader.capture(native_inventory,current_mapping,enable_writes=True)
    observed=parse(inspection.payload);engine=observed['normalized']
    xace=_project(current_cgs,before,mapping)
    merge=reconcile_records(before,xace,engine,policy,resolutions=resolutions).to_dict()
    losses=copy.deepcopy(merge['losses'])+copy.deepcopy(observed['losses'])
    def block(code,key='',field=''):
        losses.append(dict(code=code,object_id=key,field=field,severity='blocking'))
    if any(r['severity']=='review' for r in observed['losses']):
        if accepted_loss_digest!=inspection.loss_digest:block('unreviewed_precision_loss')
    else:require(accepted_loss_digest is None,'unexpected precision review')
    if not merge['resolved']:block('unresolved_conflict')
    for key,row in merge['merged'].items():
        if key in bound and row['parent_id'] is not None and not hierarchy:block('runtime_parent_binding_required',key)
        record=mapping.objects[key]
        if not row['deleted']:
            for reference in [record.scene_id,record.prefab_id]:
                if reference and merge['merged'][reference]['deleted']:block('implicit_dependency_deleted',key)
    for key in bound:
        previous=_binding(baseline_cgs,mapping.objects[key].world_binding)
        current=_binding(current_cgs,mapping.objects[key].world_binding)
        if previous is not None and current is not None:
            old_object,new_object=copy.deepcopy(previous[2]),copy.deepcopy(current[2])
            for obj in [old_object,new_object]:obj.get('relationships',{}).pop(PARENT,None)
            if 'presentation.asset' in before[key]['fields'] and len(old_object.get('asset_bindings',{}))==1 and set(old_object['asset_bindings'])==set(new_object.get('asset_bindings',{})):
                old_object.pop('asset_bindings');new_object.pop('asset_bindings')
            if old_object!=new_object:block('unprojected_canonical_world_change',key)
    for op in merge['canonical_proposals']+merge['native_proposals']:
        if op['kind']!='set_field':block('structural_materialization_requires_coordinator',op['object_id'])
        elif op['field'] not in TRANSFORMS|{'binding.playback','presentation.asset','input.action'} or not op['value']['present']:block('field_mapping_not_certified',op['object_id'],op['field'])
        elif op['object_id'] not in bound:block('unbound_native_object',op['object_id'],op['field'])
    operations=[]
    resolved=None
    if hierarchy:
        try:resolved=resolve_hierarchy(row_transforms(merge['merged'],bound),{k:merge['merged'][k]['parent_id'] for k in bound})
        except (ValueError,KeyError,TypeError):block('hierarchy_profile_refused')
    for key in bound:
        desired=merge['merged'][key];current=_binding(current_cgs,mapping.objects[key].world_binding)
        if current is None or desired['deleted']:continue
        mode,actor,_=current
        if not TRANSFORMS <= set(desired['fields']):block('incomplete_transform',key);continue
        transform={name:{axis:int(value) for axis,value in desired['fields']['transform.'+name].items()} for name in ['position','rotation','scale']}
        transform['parent_entity_id']=0
        if resolved is not None:transform=resolved[key]
        if next(c['defaults'] for c in actor['components'] if c['type_id']==1)!=transform:
            operations.append(dict(operation_id='reconcile.'+key,kind='set_native_transform',mode_id=mode['id'],actor_id=actor['id'],expected_actor_digest=digest(actor),transform=transform))
    for key in bound:
        desired=merge['merged'][key];native_action=desired.get('fields',{}).get('input.action')
        if native_action is None:continue
        found=_binding(current_cgs,mapping.objects[key].world_binding)
        if found is None:continue
        mode,_,obj=found
        binding=gde.native_input_bindings.for_object(current_cgs,mode['id'],obj['id'],mapping.engine)
        if binding is None:
            if before[key]['fields'].get('input.action')!=native_action:block('explicit_input_binding_required',key)
            continue
        if binding['native_actions'][mapping.engine]!=native_action:
            operations.append(dict(operation_id='input.'+key,kind='set_native_input',binding_id=binding['binding_id'],expected_binding_digest=digest(binding),engine=mapping.engine,native_action=native_action))
    for key in bound:
        desired=merge['merged'][key];native_asset=desired.get('fields',{}).get('presentation.asset')
        if native_asset is None:continue
        found=_binding(current_cgs,mapping.objects[key].world_binding)
        if found is None:continue
        mode,_,obj=found
        if not obj.get('asset_bindings'):
            if before[key]['fields'].get('presentation.asset')!=native_asset:block('explicit_presentation_role_required',key)
            continue
        try:
            projected=_presentation(current_cgs,obj,mapping.engine,before[key]['fields']['presentation.asset'])
            if projected==native_asset:continue
            asset=next(a for a in current_cgs.get('assets',[]) if a['id']==native_asset['asset_id'])
            require(asset['asset_type']==native_asset['asset_type']=='MESH' and asset['status']==native_asset['status']=='LINKED' and asset.get('source')==_asset_source(mapping.engine,native_asset['resolved_path']),'unregistered native mesh')
            operations.append(dict(operation_id='presentation.'+key,kind='set_native_presentation',mode_id=mode['id'],object_id=obj['id'],expected_object_digest=digest(obj),role=next(iter(obj['asset_bindings'])),asset={k:asset[k] for k in ['id','asset_type','status']}))
        except (ValueError,KeyError,StopIteration):block('presentation_mapping_not_certified',key)
    for key in bound:
        desired=merge['merged'][key]
        playback=desired.get('fields',{}).get('binding.playback')
        if playback is None:continue
        original=before[key]['fields'].get('binding.playback')
        if original is None or original['binding_id']!=playback['binding_id']:
            block('playback_identity_requires_explicit_enrollment',key);continue
        try:
            existing=next(b for b in current_cgs['semantic_bindings']['bindings'] if b['binding_id']==playback['binding_id'])
            if _playback(current_cgs,playback['binding_id'],mapping.engine)==playback:continue
            replacement=copy.deepcopy(existing);ref=playback['asset']
            asset=next(a for a in current_cgs.get('assets',[]) if a['id']==ref['asset_id'])
            require(asset['status']==ref['status']=='LINKED' and asset['asset_type']==ref['asset_type'] and asset.get('source')==_asset_source(mapping.engine,ref['resolved_path']),'unregistered native playback resource')
            replacement.update(event_name=playback['event_name'],playback_kind=playback['playback_kind'],asset=dict(id=asset['id'],asset_type=''.join(p.title() for p in asset['asset_type'].split('_')),status='Linked'))
            replacement['parameters']['resource_path']=ref['resolved_path']
            operations.append(dict(operation_id='playback.'+key,kind='set_native_playback',binding_id=existing['binding_id'],expected_binding_digest=digest(existing),binding=replacement))
        except (ValueError,KeyError,StopIteration):block('playback_mapping_not_certified',key)
    batch=dict(schema=gde.SCHEMA,expected_cgs_digest=digest(current_cgs),operations=operations)
    candidate=None;native_request=None
    try:
        candidate=gde.preview(batch,current_cgs,validate=factory.compile_portable_cgs).proposed_cgs
        package=factory.compile_portable_cgs(candidate)
        structured=[system for system in package.to_sgc_input() if 1 in system.get('reads',[]) or 1 in system.get('writes',[])]
        if structured:
            from native_executor_contract import TrustedExecutor
            try:
                require(type(trusted_executor) is TrustedExecutor,'Trusted structured executor required')
                trusted_executor.require_structured_transform(package)
            except (ValueError,OSError):
                for system in structured:block('uncertified_structured_transform_system',field=system['id'])
    except (ValueError,KeyError,TypeError):block('gde_factory_rejected')
    if not any(r['severity']=='blocking' for r in losses) and merge['native_proposals']:
        target=reader.inventory(native_inventory)
        for op in merge['native_proposals']:
            target['objects'][op['object_id']]['fields'][op['field']]=(_native_transform(mapping.engine,op['field'],op['value']['value']) if op['field'] in TRANSFORMS else copy.deepcopy(op['value']['value']))
        try:
            admitted=inspection.admit(accepted_loss_digest)
            desired=reader.capture(canonical(target),mapping,enable_writes=True).admit(accepted_loss_digest)
            require(desired.to_dict()['inspection']['normalized']==merge['merged'],'native materialization does not match merged values')
            native_request=parse(reader.write_request(native_inventory,admitted,desired,mapping))
        except ValueError:block('native_materialization_rejected')
    report=dict(schema='xace.native_reconciliation_plan.v1',preview_only=True,can_commit=False,play_eligible=False,
                identities=dict(project_id=mapping.project_id,branch_id=mapping.branch_id,namespace_id=mapping.namespace_id,
                                mapping_digest=mapping.mapping_digest(),baseline=digest(mapping.to_dict()),
                                current_cgs=digest(current_cgs),native_source=expected_source_digest,policy=digest(policy.description()),executor_receipt=trusted_executor.receipt_digest if trusted_executor is not None else None),
                merge=merge,losses=sorted(losses,key=encode),typed_operations=batch,proposed_cgs=candidate,native_write_preview=native_request,
                reviewable=candidate is not None and not any(r['severity']=='blocking' for r in losses),
                noop=not operations and not merge['native_proposals'] and not merge['canonical_proposals'])
    return MergeProposal(encode(report))
