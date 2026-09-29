"""Read-only SGC identity verification, mirroring core/execution_plan.rs v1.

No scheduling or compilation. Field order is normative in the existing Rust hash;
shared compiler vectors test this reader against the actual SGC output.
"""
import hashlib
import json


def verify_sgc_identity(plan, definitions):
    def require(ok,message):
        if not ok: raise ValueError(message)
    def fields(value,names):
        require(isinstance(value,dict) and set(value)==set(names),"unknown/missing SGC identity fields")
        return {k:value[k] for k in names}
    def hash_value(value):
        return hashlib.sha256(json.dumps(value,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf8")).hexdigest()
    system_fields=("id","display_name","phase","reads","writes","depends_on","deterministic","version","description")
    systems={}
    for raw in sorted(definitions,key=lambda s:s["id"]):
        s=fields(raw,system_fields)
        s["display_name"]=s["display_name"] if s["display_name"].strip() else s["id"]
        s["version"]=fields(s["version"],("major","minor"))
        for key in ("reads","writes","depends_on"):s[key]=sorted(set(s[key]))
        systems[s["id"]]=s
    input_hash=hash_value({"schema":"xace.sgc.input_hash.v1","schema_version":plan["schema_version"],"plan_version":plan["plan_version"],
        "compiled_from_cgs_hash":plan["compiled_from_cgs_hash"],"systems":systems})
    require(input_hash==plan["proof_bundle"]["input_hash"],"SGC input hash mismatch")
    phases={}
    for key,raw in sorted(plan["phases"].items(),key=lambda kv:int(kv[0])):
        p=fields(raw,("phase","groups","total_system_count"))
        p["groups"]=[fields(g,("group_id","phase","parallel","systems","serialization_constraints","execution_index")) for g in p["groups"]]
        phases[key]=p
    access=fields(plan["component_access_sets"],("schema","by_system","all_reads","all_writes","component_ids"))
    access["by_system"]={key:fields(v,("reads","writes")) for key,v in sorted(access["by_system"].items())}
    metadata=fields(plan["system_metadata"],("schema","systems"))
    metadata["systems"]={key:fields(v,("display_name","phase","depends_on","deterministic","version","description")) for key,v in sorted(metadata["systems"].items())}
    for m in metadata["systems"].values():m["version"]=fields(m["version"],("major","minor"))
    identity={"schema":"xace.sgc.execution_plan_identity.v1"}
    identity.update({key:plan[key] for key in ("schema_version","plan_version","created_tick","compiled_from_cgs_hash","adapter_protocol_version","migration_status","all_system_ids")})
    identity.update(phases=phases,component_access_sets=access,system_metadata=metadata,input_hash=input_hash)
    require(hash_value(identity)==plan["plan_hash"],"SGC plan identity hash mismatch")
    validation={"schema":"xace.sgc.validation_hash.v1"}
    validation.update({key:plan[key] for key in ("compiled_from_cgs_hash","plan_hash","adapter_protocol_version","migration_status")})
    validation.update(component_access_sets=access,system_metadata=metadata)
    require(hash_value(validation)==plan["proof_bundle"]["validation_hash"],"SGC validation hash mismatch")
