"""Exact static translation hierarchy projection; no runtime IDs or publication."""
import copy
import json
from pathlib import Path
from authoring_identity import require
PROFILE='native.static_translation_hierarchy.v1'
SCALE=1000000
LIMIT=json.loads((Path(__file__).resolve().parents[1]/'core/src/world/profiles.json').read_text(encoding='utf-8'))['profiles']['aabb_v1']['coordinate_limit_raw']

def validate(value):
    require(type(value) is dict and set(value)=={'position','rotation','scale','parent_entity_id'},'Exact structured transform required')
    for name,axes in [('position',set('xyz')),('rotation',set('xyzw')),('scale',set('xyz'))]:
        require(type(value[name]) is dict and set(value[name])==axes and all(type(v) is int for v in value[name].values()),'Integer fixed-point transform required')
    require(value['rotation']==dict(x=0,y=0,z=0,w=SCALE) and value['scale']==dict(x=SCALE,y=SCALE,z=SCALE),'Static hierarchy supports translation only')
    require(type(value['parent_entity_id']) is int and value['parent_entity_id']==0,'Authoring ID cannot be a runtime EntityID')
    require(all(-LIMIT<=v<=LIMIT for v in value['position'].values()),'Coordinate bound exceeded')

def resolve(local,parents):
    require(type(local) is dict and 0<len(local)<=1000 and type(parents) is dict and set(local)==set(parents),'Complete bounded instance closure required')
    for key,value in local.items():
        require(type(key) is str and 0<len(key)<=128,'Stable instance identity required');validate(value)
        require(parents[key] is None or (type(parents[key]) is str and parents[key] in local),'Unbound parent instance')
    world={}
    for key in sorted(local):
        chain=[];seen=set();current=key
        while current is not None and current not in world:
            require(current not in seen,'Parent cycle');seen.add(current);chain.append(current);current=parents[current]
        for child in reversed(chain):
            value=copy.deepcopy(local[child]);parent=parents[child]
            if parent is not None:value['position']={axis:value['position'][axis]+world[parent]['position'][axis] for axis in 'xyz'}
            validate(value);world[child]=value
    return {key:world[key] for key in sorted(world)}

def localize(world,parents):
    require(type(world) is dict,'World instances required')
    for value in world.values():validate(value)
    resolve({key:{**copy.deepcopy(value),'position':dict(x=0,y=0,z=0)} for key,value in world.items()},parents)
    local={}
    for key,value in sorted(world.items()):
        row=copy.deepcopy(value);parent=parents[key]
        if parent is not None:row['position']={axis:row['position'][axis]-world[parent]['position'][axis] for axis in 'xyz'}
        validate(row);local[key]=row
    require(resolve(local,parents)==world,'Hierarchy inverse mismatch')
    return local
