"""Exact declared AABB adoption/projection; no physics inference or new backend."""
from authoring_identity import require
from native_authoring_values import geometry
PROFILE='world.aabb.v1'
FIELDS=frozenset({'collision.shape','collision.size','collision.offset','collision.trigger','collision.profile'})

def project_collider(components: list, profile: str) -> dict:
    require(profile==PROFILE,'unsupported authoritative geometry profile')
    found=[c for c in components if c.get('type_id')==4]
    require(len(found)==1,'one explicit collider component required')
    value=found[0]['defaults']
    require(value.get('shape')=='BOX' and type(value.get('is_trigger')) is bool,'explicit BOX/trigger required')
    result={'collision.shape':value['shape'],'collision.trigger':value['is_trigger'],'collision.profile':profile}
    for field in ['size','offset']:
        vector=value.get(field)
        require(type(vector) is dict and set(vector)==set('xyz') and all(type(v) is int for v in vector.values()),'fixed-point collider vector required')
        result['collision.'+field]={k:str(v) for k,v in vector.items()}
    return result

def require_adoption_match(fields: dict, parent: str | None, choice: dict) -> None:
    geometry(fields,parent)
    projected=project_collider(choice['components'],choice['geometry_profile'])
    require(projected=={k:fields[k] for k in FIELDS},'explicit collider choices differ from native capture')
