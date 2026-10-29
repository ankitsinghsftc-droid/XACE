"""Immutable sibling-branch contributions for the declared transform-only profile.

No contribution executes code or restores another workspace's receipts. Both
branch versions remain data for explicit review. Publication is a separate host
operation through GDE and the existing coordinator.
"""
import copy,json,hashlib,subprocess,os
from pathlib import Path
from authoring_identity import IdentityMap,canonical,digest,require,token
from authoring_transaction_files import confined,load_json,sha
from authoring_saved_pair import MAP,CGS,NATIVE
from native_workspace_fork import _source,io_path
from native_authoring_contract import Snapshot,parse
from native_adoption import bridge,factory
from native_reconciliation_plan import TRANSFORMS,_native_transform,plan_reconciliation,_project
from tools.cgs_schema_validate import compute_cgs_hash

SCHEMA='xace.native_branch_contribution.v1'

def ancestor(host):
    root=host.root;review=load_json(root/'.xace/fork-intent.json');receipt=load_json(root/'.xace/fork-receipt.json')
    unsigned=copy.deepcopy(review);approved=unsigned.pop('review_digest')
    require(approved==digest(unsigned)==receipt['review_digest'] and receipt['state']=='committed','unverified fork provenance')
    archive=confined(io_path(root),receipt['ancestor_history']);expected=review['ancestor_history']
    def read(name):
        require(name in expected,'ancestor file not enrolled');data=confined(archive,name).read_bytes();require(sha(data)==expected[name],'ancestor bytes changed');return data
    m=IdentityMap.from_dict(json.loads(read(MAP.removeprefix('.xace/'))));c=json.loads(read(CGS.removeprefix('.xace/')));snap=Snapshot(read(NATIVE.removeprefix('.xace/')))
    require(m.to_dict()==review['source_mapping'],'ancestor mapping changed');b=m.baseline
    require(b is not None and b.cgs_digest==digest(c) and b.native_snapshot_digest==snap.sha256 and b.mapping_digest==m.mapping_digest(),'ancestor baseline changed')
    folder=b.journal_ref.removeprefix('.xace/');state=json.loads(read(folder+'/state.json'));manifest=json.loads(read(folder+'/manifest.json'))
    require(state['state']=='committed' and state['manifest_digest']==digest(manifest),'ancestor journal not committed')
    require(digest(state['receipts']['canonical'])==b.canonical_receipt and digest(state['receipts']['native'])==b.native_receipt,'ancestor receipts changed')
    blank=copy.deepcopy(m);blank.baseline=None;rows=snap.to_dict()['inspection']['normalized']
    require(manifest['request']['verification_record']==dict(mapping=blank.to_dict(),cgs_digest=digest(c),normalized_digest=digest(rows)),'ancestor verification changed')
    return m,c,snap,review

def without_transforms(cgs):
    value=copy.deepcopy(cgs)
    for key in ['cgs_hash','version']:value['metadata'].pop(key,None)
    for mode in value['modes']:
        for actor in mode['actors']:
            for component in actor['components']:
                if component['type_id']==1:component['defaults']='<reviewed-transform>'
    return value

def without_native_transforms(rows):
    result=copy.deepcopy(rows)
    for row in result.values():
        for field in TRANSFORMS:row['fields'].pop(field,None)
    return result

def current_checkpoint(root):
    result=subprocess.run(['git','--no-optional-locks','-C',str(root),'rev-parse','HEAD'],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    require(result.returncode==0,'receiver Git checkpoint required');return result.stdout.decode().strip()

def verify_git_checkpoint(root,checkpoint,files):
    def git(*args):
        result=subprocess.run(['git','--no-optional-locks','-C',str(root),*args],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        require(result.returncode==0,'Git checkpoint inspection failed');return result.stdout
    require(git('rev-parse','HEAD').decode().strip()==checkpoint,'source Git HEAD changed')
    algorithm=git('rev-parse','--show-object-format').decode().strip();require(algorithm in {'sha1','sha256'},'unsupported Git object format')
    tree={}
    for entry in git('ls-tree','-r','-z',checkpoint).split(b'\0'):
        if not entry:continue
        info,name=entry.split(b'\t',1);mode,kind,oid=info.decode().split();tree[name.decode('utf-8')]=(mode,kind,oid)
    for name,expected in files.items():
        require(name in tree and tree[name][0] in {'100644','100755'} and tree[name][1]=='blob','native source not checkpointed')
        data=confined(root,name).read_bytes();require(sha(data)==expected,'source changed while pinning Git')
        blob=b'blob '+str(len(data)).encode()+b'\0'+data
        require(hashlib.new(algorithm,blob).hexdigest()==tree[name][2],'uncommitted native source differs from checkpoint')
    require(git('rev-parse','HEAD').decode().strip()==checkpoint,'source Git HEAD changed during capture')

def capture_contribution(host,principal,checkpoint):
    token(principal,'principal');require(type(checkpoint) is str and len(checkpoint) in {40,64} and all(c in '0123456789abcdef' for c in checkpoint),'explicit Git checkpoint required')
    with host.publication_gate():
        mapping,cgs,rows,files,_=_source(host);m,base,snapshot,origin=ancestor(host)
        require(mapping.namespace_id==m.namespace_id and mapping.mapping_digest()==m.mapping_digest(),'structural branch changes require another profile')
        require(without_transforms(cgs)==without_transforms(base),'non-transform canonical contribution is unsupported; preserve and review separately')
        base_rows=snapshot.to_dict()['inspection']['normalized']
        require(without_native_transforms(rows)==without_native_transforms(base_rows),'non-transform native contribution is unsupported')
        documents={host.gateway._path(p).relative_to(host.root).as_posix() for p in host.gateway.documents}|{'game.cgs.json'}
        require({p:h for p,h in files.items() if p not in documents}=={p:h for p,h in origin['files'].items() if p not in documents},'additional native source changes require separate review')
        verify_git_checkpoint(host.root,checkpoint,files)
        value=dict(schema=SCHEMA,principal=principal,checkpoint=checkpoint,engine=mapping.engine,project_id=mapping.project_id,namespace_id=mapping.namespace_id,branch_id=mapping.branch_id,mapping=mapping.to_dict(),cgs=cgs,rows=rows,files=files,ancestor=dict(mapping=m.to_dict(),cgs=base,snapshot=json.loads(snapshot.payload)),profile='native.sibling_transform_merge.v1')
        return canonical(value)

def decode_contribution(payload,expected_sha256):
    require(type(payload) is bytes and len(payload)<=16*1024**2 and sha(payload)==expected_sha256,'contribution identity/size mismatch')
    def pairs(items):
        value={}
        for key,item in items:require(key not in value,'duplicate contribution key');value[key]=item
        return value
    value=json.loads(payload,object_pairs_hook=pairs)
    require(value['schema']==SCHEMA and value['profile']=='native.sibling_transform_merge.v1','unsupported contribution profile')
    mapping=IdentityMap.from_dict(value['mapping']);cgs=value['cgs'];base=value['ancestor']['cgs'];old=IdentityMap.from_dict(value['ancestor']['mapping'])
    require(mapping.branch_id==value['branch_id'] and mapping.namespace_id==value['namespace_id']==old.namespace_id and mapping.engine==value['engine']==old.engine and mapping.project_id==value['project_id']==old.project_id,'contribution identity mismatch')
    require(mapping.mapping_digest()==old.mapping_digest(),'structural contribution unsupported')
    for c in [cgs,base]:require(c['metadata']['cgs_hash']==compute_cgs_hash(c),'invalid contribution CGS hash');factory.compile_portable_cgs(c)
    require(without_transforms(cgs)==without_transforms(base),'non-transform contribution unsupported')
    require(_project(cgs,value['rows'],mapping)==value['rows'],'contribution CGS/native projection differs')
    require(without_native_transforms(value['rows'])==without_native_transforms(value['ancestor']['snapshot']['inspection']['normalized']),'native contribution structure changed')
    return value

def _plan_contribution_unlocked(host,payload,expected_sha256,*,resolutions=None):
    """Fresh preview only. Does not publish or establish a new baseline."""
    contribution=decode_contribution(payload,expected_sha256)
    mapping,cgs,rows,files,_=_source(host);old,base,snapshot,_=ancestor(host)
    receiver_checkpoint=current_checkpoint(host.root);verify_git_checkpoint(host.root,receiver_checkpoint,files)
    require(contribution['branch_id']!=mapping.branch_id,'distinct contributor branch required')
    require(contribution['ancestor']==dict(mapping=old.to_dict(),cgs=base,snapshot=json.loads(snapshot.payload)),'different verified common ancestor')
    require(mapping.mapping_digest()==old.mapping_digest() and mapping.namespace_id==old.namespace_id,'receiver structural changes unsupported')
    require(without_transforms(cgs)==without_transforms(base) and without_native_transforms(rows)==without_native_transforms(snapshot.to_dict()['inspection']['normalized']),'receiver outside transform merge profile')
    raw=host.gateway.capture();reader=bridge(mapping.engine)
    require(reader.capture(raw,mapping,enable_writes=True).admit().to_dict()['inspection']['normalized']==rows,'receiver changed during branch capture')
    synthetic=json.loads(raw)
    for key,row in contribution['rows'].items():
        for field in TRANSFORMS:
            if field in row['fields']:synthetic['objects'][key]['fields'][field]=_native_transform(mapping.engine,field,row['fields'][field])
    # Compare in the verified ancestor's identity scope; this is preview data,
    # never a replacement for the receiver's active mapping or receipts.
    adjusted=copy.deepcopy(old)
    context=dict(baseline=snapshot,baseline_cgs=base,mapping=adjusted,current_mapping=copy.deepcopy(adjusted),current_cgs=cgs,native_inventory=canonical(synthetic),expected_current_cgs_digest=digest(cgs),expected_source_digest=sha(canonical(synthetic)),verify_baseline=lambda b:b==old.baseline,trusted_project=True,resolutions=resolutions)
    plan=plan_reconciliation(**context)
    return dict(schema='xace.native_branch_merge_preview.v1',profile=contribution['profile'],contribution_sha256=expected_sha256,contributor_checkpoint=contribution['checkpoint'],receiver_checkpoint=receiver_checkpoint,receiver_mapping=mapping.to_dict(),receiver_cgs_digest=digest(cgs),receiver_native_digest=sha(raw),report=plan.to_dict(),can_commit=False)

def plan_contribution(host,payload,expected_sha256,*,resolutions=None):
    with host.publication_gate():
        return _plan_contribution_unlocked(host,payload,expected_sha256,resolutions=resolutions)
