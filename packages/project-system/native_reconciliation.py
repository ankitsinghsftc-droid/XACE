"""NEC-008 deterministic B/X/E review proposals; no persistence or activation.

B is verified saved baseline, X is a host-derived CGS projection, E is a fresh
native inspection. This module never interprets timestamps or imported code.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass

from authoring_identity import canonical, digest, exact, require
from native_authoring_contract import AuthoringPolicy, bounded
from native_authoring_values import integer, geometry

SCHEMA = 'xace.native_reconciliation.v1'
MISSING = {'present': False}


def slot(values, key):
    return dict(present=True, value=copy.deepcopy(values[key])) if key in values else dict(MISSING)


def content(row):
    return {k:v for k,v in row.items() if k != 'generation'}


def validate_rows(rows, policy):
    bounded(rows); policy.description()
    require(type(rows) is dict and 0 < len(rows) <= 10000, 'invalid reconciliation scope')
    for key,row in rows.items():
        exact(row, {'generation','deleted','parent_id','fields','dependencies','opaque'})
        require(integer(row['generation']) > 0 and type(row['deleted']) is bool, 'invalid object generation/deletion')
        require(row['parent_id'] is None or row['parent_id'] in rows, 'parent outside scope')
        require(type(row['fields']) is dict and type(row['dependencies']) is list and type(row['opaque']) is list, 'invalid object content')
        require(len(row['fields']) <= 64, 'field limit')
        if row['deleted']:require(row['parent_id'] is None and not row['fields'] and not row['dependencies'] and not row['opaque'], 'deleted object has content')
        require(set(row['fields']) <= {k for k,r in policy.fields.items() if r.read}, 'unknown/unreadable projected field')
        for name,value in row['fields'].items():
            kind=policy.fields[name].value_type
            if kind in {'position','rotation','scale','offset','size','normal'}:
                exact(value,set('xyzw' if kind=='rotation' else 'xyz'))
                numbers=[integer(v) for v in value.values()]
                if kind in {'position','offset','size'}:require(all(abs(n)<=8192_000000 for n in numbers),'coordinate bound')
                if kind=='scale':require(all(numbers),'zero scale')
                if kind=='size':require(all(n>0 for n in numbers),'invalid size')
                if kind in {'rotation','normal'}:require(abs(sum(n*n for n in numbers)-1000000**2)<=4000000,'nonunit vector')
            elif kind=='int64':integer(value)
            elif kind=='bool':require(type(value) is bool,'invalid boolean')
            elif kind=='text':require(type(value) is str,'invalid text')
            else:require(type(value) is dict,'invalid typed reference')
        for edge in row['dependencies']:
            exact(edge,{'kind','target'});require(edge['kind'] in {'resource','binding','behavior'} and edge['target'] in rows,'invalid dependency')
        require(len({(e['kind'],e['target']) for e in row['dependencies']})==len(row['dependencies']),'duplicate dependency')
        for opaque in row['opaque']:
            exact(opaque,{'id','sha256','critical','reason'});require(type(opaque['critical']) is bool,'invalid opaque flag')
        require(len({o['id'] for o in row['opaque']})==len(row['opaque']),'duplicate opaque ID')


@dataclass(frozen=True)
class MergeProposal:
    payload: bytes

    @property
    def sha256(self):
        import hashlib
        return hashlib.sha256(self.payload).hexdigest()

    def to_dict(self):
        import json
        return json.loads(self.payload)


def reconcile_records(base:dict, xace:dict, engine:dict, policy:AuthoringPolicy, *, resolutions:dict|None=None) -> MergeProposal:
    """Pure normalized-record kernel. Host integration must validate captures/CGS.

    No missing-record deletion inference. Structural conflicts keep all versions.
    Quaternion/reference values are atomic; position/scale axes merge separately.
    """
    resolutions={} if resolutions is None else copy.deepcopy(resolutions)
    require(type(resolutions) is dict and all(v in {'xace','engine'} for v in resolutions.values()),'invalid resolution')
    for rows in [base,xace,engine]:validate_rows(rows,policy)
    require(set(base)==set(xace)==set(engine),'scope change requires explicit enrollment; absence is not deletion')
    # Ordering in dictionaries and dependency/opaque inventories has no merge meaning.
    def ordered(rows):
        value=copy.deepcopy(rows)
        for row in value.values():
            row['dependencies'].sort(key=canonical);row['opaque'].sort(key=lambda o:o['id'])
        return value
    base,xace,engine=map(ordered,[base,xace,engine])
    inputs=digest(dict(base=base,xace=xace,engine=engine,policy=policy.description()))
    merged=copy.deepcopy(base);conflicts=[];decisions=[];losses=[]

    def blocked(code,key,field=''):
        losses.append(dict(code=code,object_id=key,field=field,severity='blocking'))

    def choose(key,path,b,x,e,*,force=None,allowed=('xace','engine')):
        if force is None:
            if x==e:result=x;reason='same_value'
            elif x==b:result=e;reason='engine_only'
            elif e==b:result=x;reason='xace_only'
            else:force='same_field'
        if force is not None:
            identity=digest(dict(inputs=inputs,object_id=key,path=path,reason=force))
            selected=resolutions.get(identity)
            require(selected is None or selected in allowed,'resolution violates field ownership')
            conflicts.append(dict(id=identity,object_id=key,path=path,reason=force,base=copy.deepcopy(b),xace=copy.deepcopy(x),engine=copy.deepcopy(e),allowed=list(allowed),resolution=selected))
            result=({'xace':x,'engine':e}[selected] if selected else b);reason='resolved' if selected else 'unresolved'
        decisions.append(dict(object_id=key,path=path,reason=reason,value=copy.deepcopy(result)))
        return copy.deepcopy(result)

    for key in sorted(base):
        b,x,e=base[key],xace[key],engine[key]
        require(b['generation']==x['generation']==e['generation'],'generation collision requires identity review')
        parent_interaction=(x['parent_id']!=b['parent_id'] and e!=b and e!=x) or (e['parent_id']!=b['parent_id'] and x!=b and x!=e)
        # A parent's structure also changes the meaning of descendant placement.
        # Check transitive baseline dependents before considering disjoint fields.
        if x['parent_id']!=b['parent_id'] or e['parent_id']!=b['parent_id'] or x['deleted']!=b['deleted'] or e['deleted']!=b['deleted']:
            dependent={key}
            while True:
                expanded=dependent | {k for k,r in base.items() if r['parent_id'] in dependent or any(edge['target'] in dependent for edge in r['dependencies'])}
                if expanded==dependent:break
                dependent=expanded
            parent_interaction=parent_interaction or any(
                (x!=b and engine[k]!=base[k]) or (e!=b and xace[k]!=base[k]) for k in dependent-{key})
        delete_interaction=(x['deleted']!=e['deleted'] and x!=b and e!=b)
        if delete_interaction or parent_interaction:
            merged[key]=choose(key,['object'],b,x,e,force='delete_edit' if delete_interaction else 'reparent_interaction')
            # Whole-object choice cannot overwrite engine-owned code or fields.
            merged[key]['opaque']=copy.deepcopy(e['opaque'])
            for field,rule in policy.fields.items():
                if rule.owner=='native':
                    if field in e['fields']:merged[key]['fields'][field]=copy.deepcopy(e['fields'][field])
                    else:merged[key]['fields'].pop(field,None)
        elif x['deleted'] or e['deleted']:
            merged[key]=choose(key,['object'],b,x,e)
        else:
            row=merged[key]
            row['parent_id']=choose(key,['parent_id'],b['parent_id'],x['parent_id'],e['parent_id'])
            row['dependencies']=choose(key,['dependencies'],b['dependencies'],x['dependencies'],e['dependencies'],force='dependency_change' if x['dependencies']!=b['dependencies'] or e['dependencies']!=b['dependencies'] else None)
            row['opaque']=copy.deepcopy(e['opaque'])
            if x['opaque']!=b['opaque']:blocked('native_code_is_not_cgs',key,'opaque')
            row['fields']={}
            for field in sorted(set(b['fields'])|set(x['fields'])|set(e['fields'])):
                rule=policy.fields[field];bs,xs,es=[slot(v['fields'],field) for v in (b,x,e)]
                if rule.owner=='native':
                    if xs!=bs:choose(key,['fields',field],bs,xs,es,force='native_owned',allowed=('engine',))
                    result=es
                elif rule.value_type in {'position','scale'} and all(s['present'] for s in [bs,xs,es]):
                    result=dict(present=True,value={axis:choose(key,['fields',field,axis],bs['value'][axis],xs['value'][axis],es['value'][axis]) for axis in 'xyz'})
                else:result=choose(key,['fields',field],bs,xs,es)
                if result['present']:row['fields'][field]=copy.deepcopy(result['value'])
        if e['opaque']!=b['opaque']:
            losses.append(dict(code='native_code_retained',object_id=key,field='opaque',severity='info'))
        for opaque in e['opaque']:
            if opaque['critical']:blocked('critical_native_behavior',key,opaque['id'])

    require(set(resolutions)<={c['id'] for c in conflicts},'stale or unknown conflict resolution')
    # Validate the combined graph, not just either independently valid input.
    for key,row in merged.items():
        if row['deleted']:continue
        for target in [row['parent_id']]+[e['target'] for e in row['dependencies']]:
            if target is not None and merged[target]['deleted']:blocked('dangling_dependency',key)
        seen=set();cursor=key
        while cursor is not None:
            if cursor in seen:blocked('parent_cycle',key);break
            seen.add(cursor);cursor=merged[cursor]['parent_id']
        if any(k.startswith('collision.') for k in row['fields']):
            try:geometry(row['fields'],row['parent_id'])
            except ValueError:blocked('unsupported_geometry',key)
    try:validate_rows(merged,policy)
    except ValueError:blocked('invalid_merged_record','')
    native=[];canonical_ops=[]
    for key in sorted(base):
        for label,source,output in [('xace',xace,canonical_ops),('engine',engine,native)]:
            old,new=source[key],merged[key]
            if old==new:continue
            # Native-owned opaque records are carried into the next verified
            # baseline, never converted into a canonical structural mutation.
            # Critical behavior and attempted canonical opaque writes are still
            # blocking losses above. Native publication retains exact checks.
            excluded={'fields','opaque'} if label=='xace' else {'fields'}
            if {k:v for k,v in old.items() if k not in excluded}!={k:v for k,v in new.items() if k not in excluded}:
                output.append(dict(kind='review_structure',object_id=key,before=copy.deepcopy(old),after=copy.deepcopy(new)))
                continue
            for field in sorted(set(old['fields'])|set(new['fields'])):
                before,after=slot(old['fields'],field),slot(new['fields'],field)
                if before==after:continue
                rule=policy.fields[field]
                if rule.owner=='native':continue
                if label=='engine' and not rule.write:blocked('native_field_not_writable',key,field)
                output.append(dict(kind='set_field',object_id=key,field=field,expected_digest=digest(before),value=after))
    result=dict(schema=SCHEMA,inputs_digest=inputs,base=base,xace=xace,engine=engine,merged=merged,
                conflicts=conflicts,decisions=decisions,resolutions=resolutions,losses=sorted(losses,key=canonical),
                canonical_proposals=canonical_ops,native_proposals=native,
                resolved=all(c['resolution'] is not None for c in conflicts),preview_only=True,can_commit=False)
    return MergeProposal(canonical(result))
