"""NEC-016 streaming archive and create-only restore. No payload execution.

A restore.started.json without restore.receipt.json is retained incomplete output.
Caller supplies the trusted archive hash; self-hashes are integrity, not signatures.
"""
from __future__ import annotations
import hashlib,json,os,stat,zipfile,shutil
from pathlib import Path
from continuity_contract import (ArchiveRequest,Limits,ContinuityError,ROLES,SCHEMA,
    canonical,inventory,plain,portable_path,require)
MANIFEST='continuity.manifest.json'
MANIFEST_LIMIT=32*1024**2

def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def parents_plain(path):
    for parent in [path,*path.parents]:
        if parent.exists():plain(parent)

def manifest_validate(value,limits):
    fields={'schema','project_id','roots','files','dependencies','checkpoints','prerequisites','omissions','unavailable','declared_closure_complete','reviewed_declared_closure','rebuild_verified','content_sha256'}
    require(type(value) is dict and set(value)==fields and value['schema']==SCHEMA,'unsupported continuity manifest')
    expected=dict(value);claimed=expected.pop('content_sha256')
    require(hashlib.sha256(canonical(expected)).hexdigest()==claimed,'manifest identity mismatch')
    require(value['rebuild_verified'] is False and type(value['reviewed_declared_closure']) is bool and type(value['declared_closure_complete']) is bool,'invalid certification flags')
    require(type(value['project_id']) is str and bool(value['project_id']),'invalid project identity')
    roots=value['roots'];require(type(roots) is list and 1<=len(roots)<=64,'invalid roots')
    root_roles={}
    for row in roots:
        require(type(row) is dict and set(row)=={'key','role'} and type(row['key']) is str,'invalid root record')
        portable_path(row['key']);require('/' not in row['key'] and row['key'].casefold() not in {x.casefold() for x in root_roles} and row['role'] in ROLES,'duplicate/invalid root');root_roles[row['key']]=row['role']
    records=value['files'];require(type(records) is list and 0<len(records)<=limits.files,'invalid file table')
    index={};folded=set();total=0
    for row in records:
        require(type(row) is dict and set(row)=={'path','size','sha256','role'},'invalid file record')
        name=portable_path(row['path']);parts=name.split('/')
        require(len(parts)>=3 and parts[0]=='payload' and parts[1] in root_roles and row['role']==root_roles[parts[1]],'file outside declared root')
        require(name.casefold() not in folded,'duplicate/case-colliding manifest file');folded.add(name.casefold())
        require(type(row['size']) is int and 0<=row['size']<=limits.file_bytes,'file limit');total+=row['size']
        require(type(row['sha256']) is str and len(row['sha256'])==64 and all(c in '0123456789abcdef' for c in row['sha256']),'invalid file hash');index[name]=row
    require(total<=limits.total_bytes and list(index)==sorted(index),'archive limit or unsorted manifest')
    directories={}
    for name in index:
        for length in range(1,len(name.split('/'))):
            parent='/'.join(name.split('/')[:length]);prior=directories.setdefault(parent.casefold(),parent);require(prior==parent,'case-colliding directories')
        require(all('/'.join(name.split('/')[:n]).casefold() not in folded for n in range(1,len(name.split('/')))),'file/directory collision')
    for field in ['dependencies','checkpoints','prerequisites','omissions','unavailable']:require(type(value[field]) is list and len(value[field])<=limits.files,'invalid manifest list')
    for row in value['dependencies']:
        require(type(row) is dict and set(row)=={'name','archive_path','essential','unavailable_reason'} and type(row['essential']) is bool,'invalid dependency')
        require(row['archive_path'] is None or row['archive_path'] in index,'dependency file missing')
        require(row['archive_path'] is not None or bool(row['unavailable_reason']),'unavailable reason missing')
    for row in value['checkpoints']:
        require(type(row) is dict and set(row)=={'path','sha256'} and row['path'] in index and index[row['path']]['sha256']==row['sha256'],'checkpoint mismatch')
    for row in value['prerequisites']:
        require(type(row) is dict and set(row)=={'name','version','instructions'} and all(type(v) is str and bool(v.strip()) for v in row.values()),'invalid prerequisite')
    for field,keys in [('omissions',{'root','path','reason','essential'}),('unavailable',{'name','reason','essential'})]:
        for row in value[field]:
            require(type(row) is dict and set(row)==keys and type(row['essential']) is bool and type(row['reason']) is str and bool(row['reason'].strip()),'invalid omission/unavailable record')
            if field=='omissions':require(row['root'] in root_roles,'omission root absent');portable_path(row['path'])
    complete=value['reviewed_declared_closure'] and set(root_roles.values())==ROLES and bool(value['checkpoints']) and all(any(name.startswith('payload/'+key+'/') for name in index) for key in root_roles) and not any(r['essential'] for r in value['omissions']+value['unavailable']) and not any(r['essential'] and r['archive_path'] is None for r in value['dependencies'])
    require(complete==value['declared_closure_complete'],'false completeness claim')
    return index

def _json(data):
    def unique(pairs):
        out={}
        for key,value in pairs:require(key not in out,'duplicate manifest JSON key');out[key]=value
        return out
    try:return json.loads(data,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ContinuityError('nonfinite manifest JSON')))
    except (ValueError,UnicodeError,RecursionError) as error:raise ContinuityError(str(error)) from error

def verify_archive(path:Path,expected_sha256:str,limits:Limits=Limits()):
    limits.validate();path=Path(path);parents_plain(path);require(path.is_file(),'archive missing')
    require(path.stat().st_size<=limits.total_bytes+MANIFEST_LIMIT+limits.files*1024,'archive size limit')
    require(file_hash(path)==expected_sha256,'archive identity mismatch')
    try:
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist();require(len(entries)<=limits.files+1,'archive entry limit');names={};total=0
            for row in entries:
                name=portable_path(row.orig_filename);require(name==row.filename and name.casefold() not in names,'duplicate/noncanonical archive path');names[name.casefold()]=row
                require(not row.is_dir() and stat.S_IFMT(row.external_attr>>16) in {0,stat.S_IFREG} and not row.flag_bits&1 and row.compress_type in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED},'unsupported archive entry')
                require(0<=row.file_size<=(MANIFEST_LIMIT if name==MANIFEST else limits.file_bytes),'expanded file limit');total+=row.file_size
            require(total<=limits.total_bytes+MANIFEST_LIMIT and MANIFEST in names,'missing manifest or expanded limit')
            value=_json(archive.read(names[MANIFEST]));index=manifest_validate(value,limits)
            require(set(index)|{MANIFEST}=={v.filename for v in entries},'archive file table mismatch')
            for name,row in index.items():
                info=names[name.casefold()];require(info.file_size==row['size'],'entry size mismatch');h=hashlib.sha256();count=0
                with archive.open(info) as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):
                        count+=len(block);require(count<=row['size'],'expanded content exceeds record');h.update(block)
                require(count==row['size'] and h.hexdigest()==row['sha256'],'archive content mismatch')
            return value
    except (zipfile.BadZipFile,RuntimeError,OSError,EOFError,TypeError,KeyError,ValueError) as error:raise ContinuityError(str(error)) from error

def create_archive(request:ArchiveRequest,destination:Path,limits:Limits=Limits(),*,allow_incomplete=False):
    collected=inventory(request,limits);require(collected.manifest['declared_closure_complete'] or allow_incomplete,'essential material unavailable or closure unreviewed')
    destination=Path(destination).absolute();parents_plain(destination.parent)
    require(destination.parent.is_dir() and not destination.exists(),'archive requires fresh path and existing parent')
    require(all(not destination.resolve().is_relative_to(Path(root.path).resolve()) for root in request.roots),'archive output overlaps source')
    manifest_validate(collected.manifest,limits)
    require(len(canonical(collected.manifest))<=MANIFEST_LIMIT,'manifest size limit')
    needed=sum(v['size'] for v in collected.manifest['files'])+len(canonical(collected.manifest))+len(collected.manifest['files'])*1024
    require(shutil.disk_usage(destination.parent).free>needed+2*1024**3,'insufficient archive disk reserve')
    with destination.open('xb') as output,zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
        for row in collected.manifest['files']:
            source=collected.sources[row['path']];plain(source)
            info=zipfile.ZipInfo(row['path'],date_time=(1980,1,1,0,0,0));info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
            h=hashlib.sha256();count=0
            with source.open('rb') as incoming,archive.open(info,'w',force_zip64=row['size']>=2**31) as outgoing:
                for block in iter(lambda:incoming.read(1024*1024),b''):
                    count+=len(block);require(shutil.disk_usage(destination.parent).free>2*1024**3,'archive disk reserve reached');require(count<=row['size'],'source grew while archiving');h.update(block);outgoing.write(block)
            require(count==row['size'] and h.hexdigest()==row['sha256'],'source changed while archiving')
        require(inventory(request,limits).manifest==collected.manifest,'source changed before archive commit')
        info=zipfile.ZipInfo(MANIFEST,date_time=(1980,1,1,0,0,0));info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
        archive.writestr(info,canonical(collected.manifest))
    digest=file_hash(destination);verify_archive(destination,digest,limits)
    return dict(schema='xace.continuity_archive_receipt.v1',archive_sha256=digest,manifest_sha256=collected.manifest['content_sha256'],declared_closure_complete=collected.manifest['declared_closure_complete'],rebuild_verified=False)

def restore_archive(archive_path:Path,expected_sha256:str,destination:Path,limits:Limits=Limits(),*,allow_incomplete=False):
    value=verify_archive(archive_path,expected_sha256,limits);require(value['declared_closure_complete'] or allow_incomplete,'incomplete archive requires explicit opt-in')
    destination=Path(destination).absolute();parents_plain(destination.parent)
    require(destination.parent.is_dir() and not destination.exists(),'restore destination must be new')
    require(shutil.disk_usage(destination.parent).free>sum(v['size'] for v in value['files'])+MANIFEST_LIMIT+2*1024**3,'insufficient restore disk reserve')
    # Use the Windows extended-length namespace for nested real project paths.
    # Portable archive names were validated above; this changes IO addressing only.
    if os.name == 'nt' and not str(destination).startswith('\\\\?\\'):
        raw = str(destination)
        destination = Path('\\\\?\\UNC\\' + raw[2:] if raw.startswith('\\\\') else '\\\\?\\' + raw)
    destination.mkdir(exist_ok=False)
    (destination/'restore.started.json').write_bytes(canonical(dict(schema='xace.continuity_restore_started.v1',archive_sha256=expected_sha256)))
    with zipfile.ZipFile(archive_path) as archive:
        for row in value['files']:
            target=destination/row['path'];target.parent.mkdir(parents=True,exist_ok=True);parents_plain(target.parent);h=hashlib.sha256();count=0
            with archive.open(row['path']) as incoming,target.open('xb') as outgoing:
                for block in iter(lambda:incoming.read(1024*1024),b''):
                    count+=len(block);require(shutil.disk_usage(destination.parent).free>2*1024**3,'restore disk reserve reached');require(count<=row['size'],'restore entry grew');h.update(block);outgoing.write(block)
                outgoing.flush();os.fsync(outgoing.fileno())
            require(count==row['size'] and h.hexdigest()==row['sha256'],'restore content mismatch')
    require(file_hash(archive_path)==expected_sha256,'archive changed during restore')
    (destination/MANIFEST).write_bytes(canonical(value))
    receipt=dict(schema='xace.continuity_restore_receipt.v1',archive_sha256=expected_sha256,manifest_sha256=value['content_sha256'],files=len(value['files']),declared_closure_complete=value['declared_closure_complete'],rebuild_verified=False,executed_payload=False)
    (destination/'restore.receipt.json').write_bytes(canonical(receipt));return receipt
