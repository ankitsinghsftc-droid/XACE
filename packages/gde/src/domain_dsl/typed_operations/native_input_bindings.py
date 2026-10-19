"""Explicit authored input selectors; no runtime input routing or inferred semantics.

A binding joins one World instance to a declared canonical profile/action. Only
its engine action name may be reconciled. Runtime/cooked fidelity is a separate
admission gate; persisted authoring metadata alone never establishes it.
"""
from .native_adoption_operations import exact, require, identifier, index
SCHEMA = 'xace.native_input_bindings.v1'


def validate(cgs):
    contract=cgs.get('native_input_bindings')
    if contract is None:return []
    exact(contract,{'schema','bindings'})
    require(contract['schema']==SCHEMA,'native input binding schema')
    bindings=contract['bindings'];index(bindings,'binding_id')
    require(len(bindings)<=128,'native input binding profile limit')
    modes=index(cgs['modes']);profiles=index(cgs.get('input_profiles',[]));seen=set()
    for binding in bindings:
        exact(binding,{'binding_id','mode_id','world_object_id','input_profile_id','action_id','native_actions'})
        for name in ['binding_id','mode_id','world_object_id','input_profile_id','action_id']:identifier(binding[name])
        require(binding['mode_id'] in modes and binding['input_profile_id'] in profiles,'undeclared input mode/profile')
        mode=modes[binding['mode_id']];objects=index(mode.get('world',{}).get('contract',{}).get('objects',[]))
        require(binding['world_object_id'] in objects,'unknown input World instance')
        actor=index(mode['actors'])[objects[binding['world_object_id']]['actor_id']]
        components=index(actor['components'],'type_id');require(6 in components,'explicit input component required')
        defaults=components[6]['defaults']
        require(defaults.get('input_profile_id')==binding['input_profile_id'] and defaults.get('control_type')=='HUMAN','input routing differs from declared profile')
        profile=profiles[binding['input_profile_id']]
        require(profile.get('schema')=='xace.input_profile.v1' and binding['action_id'] in index(profile.get('actions',[])),'undeclared input action')
        native=binding['native_actions']
        require(type(native) is dict and native and set(native)<={'unity','godot','unreal'},'explicit engine input actions required')
        for engine,name in native.items():
            require(type(name) is str and 0<len(name)<=128 and name.strip()==name and all(ord(c)>=32 and ord(c)!=127 for c in name),'invalid native input action name')
            key=(binding['mode_id'],binding['world_object_id'],engine)
            require(key not in seen,'ambiguous native input selector');seen.add(key)
    return bindings


def for_object(cgs,mode_id,object_id,engine):
    rows=[b for b in validate(cgs) if b['mode_id']==mode_id and b['world_object_id']==object_id and engine in b['native_actions']]
    require(len(rows)<=1,'ambiguous native input selector')
    return rows[0] if rows else None
