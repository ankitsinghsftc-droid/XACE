"""XP-009 data-only Player presentation admission; no engine resources execute here."""
import io,json,math,re,struct,wave
from playable_package import PackageError,require,safe_path,parse,digest

CATALOG="presentation/player/presentation.json"
FORMATS={"xace.mesh.v1":"Mesh","image.png.v1":"Sprite","audio.pcm_wav.v1":"AudioClip","xace.effect.ring.v1":"Particle","xace.camera.impulse.v1":None}
MAX_RESOURCE=16*1024*1024

def number(value,lo,hi):
    return type(value) in (int,float) and math.isfinite(value) and lo<=value<=hi

def vector(value,size,lo,hi):
    return isinstance(value,list) and len(value)==size and all(number(v,lo,hi) for v in value)

def typed_ref(value,status=False):
    fields={"id","asset_type"}|({"status"} if status else set())
    require(isinstance(value,dict) and set(value)==fields,"invalid typed presentation asset reference")
    require(all(isinstance(value[k],str) and 0<len(value[k])<=128 for k in ("id","asset_type")),"invalid asset identity")
    if status:require(value["status"] in {"Linked","Missing","Placeholder"},"unresolved or invalid presentation asset")
    return value["id"]

def validate_resource(fmt,data):
    require(len(data)<=MAX_RESOURCE,"presentation resource limit exceeded")
    if fmt=="image.png.v1":
        require(len(data)>=33 and data[:8]==b"\x89PNG\r\n\x1a\n" and data[12:16]==b"IHDR","invalid PNG")
        w,h=struct.unpack(">II",data[16:24]);require(0<w<=4096 and 0<h<=4096 and w*h<=4194304,"PNG dimensions exceed profile")
        return
    if fmt=="audio.pcm_wav.v1":
        try:
            with wave.open(io.BytesIO(data),"rb") as wav:
                require(wav.getcomptype()=="NONE" and wav.getnchannels() in (1,2) and wav.getsampwidth() in (1,2),"WAV requires PCM8/PCM16 mono/stereo")
                require(8000<=wav.getframerate()<=96000 and 0<wav.getnframes()<=wav.getframerate()*10,"WAV duration/rate exceeds profile")
                require(len(wav.readframes(wav.getnframes()))==wav.getnframes()*wav.getnchannels()*wav.getsampwidth(),"truncated WAV")
        except (wave.Error,EOFError) as exc:raise PackageError("invalid PCM WAV") from exc
        return
    value=parse(data);require(isinstance(value,dict) and value.get("schema")==fmt,"resource schema mismatch")
    if fmt=="xace.mesh.v1":
        require(set(value)=={"schema","vertices","indices","color"},"invalid mesh descriptor")
        vertices=value["vertices"];indices=value["indices"]
        require(isinstance(vertices,list) and 3<=len(vertices)<=65536 and all(vector(v,3,-10000,10000) for v in vertices),"invalid mesh vertices")
        require(isinstance(indices,list) and 3<=len(indices)<=196608 and len(indices)%3==0 and all(type(i) is int and 0<=i<len(vertices) for i in indices),"invalid mesh indices")
        require(vector(value["color"],4,0,1),"invalid mesh color")
    elif fmt=="xace.effect.ring.v1":
        require(set(value)=={"schema","radius","duration_ticks","color"},"invalid effect descriptor")
        require(number(value["radius"],0.1,100) and vector(value["color"],4,0,1),"invalid ring parameters")
        require(type(value["duration_ticks"]) is int and 1<=value["duration_ticks"]<=600,"invalid effect duration")
    elif fmt=="xace.camera.impulse.v1":
        require(set(value)=={"schema","offset","duration_ticks"} and vector(value["offset"],3,-5,5),"invalid camera impulse")
        require(type(value["duration_ticks"]) is int and 1<=value["duration_ticks"]<=120,"invalid camera duration")
    else:raise PackageError("unsupported resource format")

def validate_presentation(files,manifest):
    if CATALOG not in files:return {"schema":"xace.player.presentation_admission.v1","catalog":None,"optional_paths":[],"records":[]}
    catalog=parse(files[CATALOG]);world=parse(files["world.json"])
    require(isinstance(catalog,dict) and set(catalog)=={"schema","world_hash","assets","objects","events","camera_offset","collision_overlay"},"invalid presentation catalog")
    require(catalog["schema"]=="xace.player.presentation.v1","unsupported presentation catalog")
    require(catalog["world_hash"]==manifest["gameplay"]["world"]["artifact"]["content_hash"],"presentation/world binding mismatch")
    require(vector(catalog["camera_offset"],3,-1000,1000) and any(catalog["camera_offset"]),"invalid camera offset")
    require(type(catalog["collision_overlay"]) is bool,"invalid collision overlay")
    for field in ("assets","objects","events"):
        require(isinstance(catalog[field],list) and len(catalog[field])<=4096,"presentation catalog limit")
    assets={};optional=[];records=[]
    for entry in catalog["assets"]:
        require(isinstance(entry,dict) and set(entry)=={"asset","format","path","required","fallback"},"invalid presentation asset entry")
        key=typed_ref(entry["asset"],True);require(key not in assets,"duplicate asset ID")
        fmt=entry["format"];require(fmt in FORMATS,"unsupported presentation format")
        expected=FORMATS[fmt]
        require(entry["asset"]["asset_type"]==expected if expected else re.fullmatch(r"[A-Za-z0-9_]+(?:[.][A-Za-z0-9_]+)+[.]v[1-9][0-9]*",entry["asset"]["asset_type"]) is not None,"asset type/format mismatch")
        require(type(entry["required"]) is bool and entry["fallback"] in {"canonical","marker","silent"},"invalid asset policy")
        path=entry["path"]
        if path is not None:
            safe_path(path);require(path.startswith("presentation/") and path!=CATALOG,"resource must be in presentation namespace")
            if not entry["required"]:optional.append(path)
        available=entry["asset"]["status"]=="Linked" and path in files
        require(available or not entry["required"],"required presentation asset missing")
        if available:validate_resource(fmt,files[path])
        records.append({"asset_id":key,"status":"resolved" if available else "fallback","reason":"available" if available else "cosmetic_missing","format":fmt})
        assets[key]=entry
    objects={o["id"]:o for o in world["objects"]};bound=set();event_ids=set()
    def reference(ref):
        key=typed_ref(ref);require(key in assets and ref["asset_type"]==assets[key]["asset"]["asset_type"],"presentation reference mismatch");return assets[key]
    for binding in catalog["objects"]:
        require(isinstance(binding,dict) and set(binding)=={"object_id","asset"},"invalid object binding")
        key=binding["object_id"];require(key in objects and key not in bound,"unknown or duplicate object binding");bound.add(key)
        entry=reference(binding["asset"]);require(entry["format"] in {"xace.mesh.v1","image.png.v1"},"unsupported static visual format")
    for binding in catalog["events"]:
        require(isinstance(binding,dict) and set(binding)=={"binding_id","event_name","entity_selector","asset"},"invalid event binding")
        key=binding["binding_id"];require(isinstance(key,str) and 0<len(key)<=128 and key not in event_ids,"invalid event binding ID");event_ids.add(key)
        require(isinstance(binding["event_name"],str) and re.fullmatch(r"[A-Za-z0-9_]+(?:[.][A-Za-z0-9_]+)+",binding["event_name"]) is not None,"invalid project event name")
        require(binding["entity_selector"] in {"source","target"},"invalid event entity selector")
        entry=reference(binding["asset"]);require(entry["format"] in {"xace.effect.ring.v1","audio.pcm_wav.v1","xace.camera.impulse.v1"},"unsupported event presentation")
    return {"schema":"xace.player.presentation_admission.v1","catalog":CATALOG,"optional_paths":sorted(set(optional)),"records":records}
