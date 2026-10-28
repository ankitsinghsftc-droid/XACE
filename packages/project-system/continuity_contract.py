"""NEC-016 explicit continuity closure contracts and read-only source inventory.

A complete declared closure is not independent rebuild/engine certification.
Inventory never executes archived instructions or changes authoring/runtime state.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json,os,re,stat,unicodedata
from pathlib import Path,PurePosixPath

SCHEMA='xace.continuity_archive.v1'
ROLES=frozenset({'project-source','native-project','executor-source','runtime','history','notices'})
RESERVED={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
SECRET_NAMES={'.env','.npmrc','.pypirc','id_rsa','id_ed25519','credentials.json','session-ticket.json','native-ticket.json','ticket.json'}
class ContinuityError(ValueError):pass

def require(value,message):
    if not value:raise ContinuityError(message)

def portable_path(value:str)->str:
    require(type(value) is str and 0<len(value)<=240,'invalid relative path')
    require(unicodedata.normalize('NFC',value)==value,'path must be NFC normalized')
    path=PurePosixPath(value)
    require(bool(path.parts) and not path.is_absolute() and path.as_posix()==value and '\\' not in value,'noncanonical relative path')
    for part in path.parts:
        require(part not in {'.','..'} and not part.endswith(('.', ' ')),'unsafe path component')
        require(not any(ord(c)<32 or c in '<>:"|?*' for c in part),'nonportable path character')
        require(part.split('.')[0].upper() not in RESERVED,'reserved device path')
    return value

def canonical(value)->bytes:
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')

def plain(path:Path):
    info=path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0),'links/reparse points forbidden')
    require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),'special file forbidden')
    return info

@dataclass(frozen=True)
class Limits:
    files:int=100_000
    file_bytes:int=4*1024**3
    total_bytes:int=32*1024**3
    def validate(self):
        require(all(type(v) is int and v>0 for v in (self.files,self.file_bytes,self.total_bytes)),'invalid archive limits')

@dataclass(frozen=True)
class SourceRoot:
    key:str
    role:str
    path:Path

@dataclass(frozen=True)
class Omission:
    root:str
    path:str
    reason:str
    essential:bool=True

@dataclass(frozen=True)
class Dependency:
    name:str
    archive_path:str|None
    essential:bool=True
    unavailable_reason:str=''

@dataclass(frozen=True)
class Checkpoint:
    archive_path:str
    sha256:str

@dataclass(frozen=True)
class Prerequisite:
    name:str
    version:str
    instructions:str

@dataclass(frozen=True)
class ArchiveRequest:
    project_id:str
    roots:tuple[SourceRoot,...]
    dependencies:tuple[Dependency,...]
    checkpoints:tuple[Checkpoint,...]
    prerequisites:tuple[Prerequisite,...]
    omissions:tuple[Omission,...]=()
    reviewed_declared_closure:bool=False

@dataclass(frozen=True)
class Inventory:
    manifest:dict
    sources:dict[str,Path]

def inventory(request:ArchiveRequest,limits:Limits=Limits())->Inventory:
    limits.validate();require(type(request) is ArchiveRequest,'typed archive request required')
    require(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',request.project_id) is not None,'invalid project identity')
    require(type(request.reviewed_declared_closure) is bool,'explicit closure-review flag required')
    require(1<=len(request.roots)<=64,'invalid root count')
    keys=set();roots={};root_rows=[];files=[];sources={};seen=set();total=0;unavailable=[];omitted=[]
    for root in request.roots:
        require(type(root) is SourceRoot and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',root.key) is not None,'invalid source root')
        require(root.key not in keys and root.role in ROLES,'duplicate root or unsupported role');keys.add(root.key)
        original=Path(root.path).absolute()
        for ancestor in [original,*original.parents]:plain(ancestor)
        require(original.is_dir(),'source root must be a directory');roots[root.key]=original.resolve(strict=True)
        root_rows.append(dict(key=root.key,role=root.role))
    exclusions={};used=set()
    for item in request.omissions:
        require(type(item) is Omission and item.root in roots and type(item.essential) is bool,'invalid omission')
        portable_path(item.path);require(type(item.reason) is str and bool(item.reason.strip()),'omission reason required')
        key=(item.root,item.path)
        require(key not in exclusions,'duplicate omission');exclusions[key]=item
    for root in sorted(request.roots,key=lambda r:r.key):
        base=roots[root.key];before=len(files)
        def walk(directory):
            nonlocal total
            for child in sorted(directory.iterdir(),key=lambda p:p.name):
                info=plain(child);relative=child.relative_to(base).as_posix();portable_path(relative)
                matches=[(key,item) for key,item in exclusions.items() if key[0]==root.key and (relative==item.path or relative.startswith(item.path+'/'))]
                if matches:
                    require(len(matches)==1,'overlapping omissions');key,item=matches[0];used.add(key)
                    if key not in {(v['root'],v['path']) for v in omitted}:omitted.append(dict(root=item.root,path=item.path,reason=item.reason,essential=item.essential))
                    continue
                require(child.name.casefold() not in SECRET_NAMES and not child.name.casefold().startswith('.env.') and child.name.casefold()!='.git','sensitive material requires explicit omission: '+relative)
                if stat.S_ISDIR(info.st_mode):walk(child);continue
                name=portable_path('payload/'+root.key+'/'+relative);folded=name.casefold()
                require(folded not in seen,'case-colliding archive paths');seen.add(folded)
                require(info.st_size<=limits.file_bytes,'file size limit');total+=info.st_size
                require(len(files)<limits.files and total<=limits.total_bytes,'archive inventory limit')
                digest=hashlib.sha256();size=0
                with child.open('rb') as stream:
                    opened=os.fstat(stream.fileno());require((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'source changed before read')
                    for block in iter(lambda:stream.read(1024*1024),b''):
                        size+=len(block);require(size<=limits.file_bytes,'growing source exceeds limit');digest.update(block)
                    after=os.fstat(stream.fileno())
                require(size==info.st_size and (after.st_size,after.st_mtime_ns)==(info.st_size,info.st_mtime_ns),'source changed during inventory')
                files.append(dict(path=name,size=size,sha256=digest.hexdigest(),role=root.role));sources[name]=child
        walk(base)
        if len(files)==before:unavailable.append(dict(name='root:'+root.key,essential=True,reason='no included files'))
    require(used==set(exclusions),'omission does not match source')
    names=set();dependencies=[]
    for dep in request.dependencies:
        require(type(dep) is Dependency and type(dep.essential) is bool and type(dep.name) is str and bool(dep.name.strip()) and dep.name not in names,'invalid/duplicate dependency');names.add(dep.name)
        if dep.archive_path is None:
            require(type(dep.unavailable_reason) is str and bool(dep.unavailable_reason.strip()),'unavailable dependency reason required')
            unavailable.append(dict(name=dep.name,essential=dep.essential,reason=dep.unavailable_reason))
        else:portable_path(dep.archive_path);require(dep.archive_path in sources,'dependency references absent archive file')
        dependencies.append(dict(name=dep.name,archive_path=dep.archive_path,essential=dep.essential,unavailable_reason=dep.unavailable_reason))
    indexed={v['path']:v for v in files};checkpoints=[]
    for point in request.checkpoints:
        require(type(point) is Checkpoint,'typed checkpoint required');portable_path(point.archive_path)
        require(point.archive_path in indexed and re.fullmatch('[a-f0-9]{64}',point.sha256) is not None and indexed[point.archive_path]['sha256']==point.sha256,'protected checkpoint mismatch')
        checkpoints.append(dict(path=point.archive_path,sha256=point.sha256))
    prerequisites=[]
    for item in request.prerequisites:
        require(type(item) is Prerequisite and all(type(x) is str and bool(x.strip()) for x in (item.name,item.version,item.instructions)),'explicit prerequisite name/version/instructions required')
        prerequisites.append(dict(name=item.name,version=item.version,instructions=item.instructions))
    missing_roles=sorted(ROLES-{r.role for r in request.roots})
    for role in missing_roles:unavailable.append(dict(name='role:'+role,essential=True,reason='required closure role absent'))
    if not checkpoints:unavailable.append(dict(name='protected-checkpoint',essential=True,reason='no protected checkpoint supplied'))
    complete=request.reviewed_declared_closure and not any(v['essential'] for v in unavailable+omitted)
    manifest=dict(schema=SCHEMA,project_id=request.project_id,roots=sorted(root_rows,key=lambda v:v['key']),files=sorted(files,key=lambda v:v['path']),dependencies=sorted(dependencies,key=lambda v:v['name']),checkpoints=sorted(checkpoints,key=lambda v:v['path']),prerequisites=sorted(prerequisites,key=lambda v:v['name']),omissions=sorted(omitted,key=lambda v:(v['root'],v['path'])),unavailable=sorted(unavailable,key=lambda v:v['name']),declared_closure_complete=complete,reviewed_declared_closure=request.reviewed_declared_closure,rebuild_verified=False)
    manifest['content_sha256']=hashlib.sha256(canonical(manifest)).hexdigest()
    return Inventory(manifest,sources)
