"""Reviewed create-only native authoring fork; ancestor receipts remain inert data.

The registered source host owns executable/plugin trust. Neither archive contents
nor browser input select executable code. Incomplete destinations are retained.
"""
from pathlib import Path
import copy,shutil,os
from authoring_identity import IdentityMap,IdentityDraft,canonical,digest,require,token
from authoring_transaction_files import confined,load_json,durable,sha
from authoring_saved_pair import SavedPair,MAP,CGS,NATIVE,verify_baseline_receipts
from authoring_transaction_contract import TransactionRequest
from authoring_apply import file_change,ACTIVATION
from native_editor_gateway import NativeEditorGateway
from native_materialization import NativeMaterializationHost
from native_authoring_contract import Snapshot
from native_adoption import bridge
from continuity_archive import parents_plain,file_hash

DISPOSABLE={'target','build','dist','tmp','temp','.cache','cache'}

def io_path(path):
    path=Path(path).absolute();raw=str(path)
    if os.name=='nt' and not raw.startswith('\\\\?\\'):
        return Path('\\\\?\\UNC\\'+raw[2:] if raw.startswith('\\\\') else '\\\\?\\'+raw)
    return path

def destination_path(value,source):
    destination=Path(value).absolute();parents_plain(destination.parent);destination=destination.resolve()
    require(not destination.exists(),'fork destination must be new')
    require(not any(p.casefold() in DISPOSABLE for p in destination.parts),'persistent fork destination required')
    require(not destination.is_relative_to(source) and not source.is_relative_to(destination),'fork roots must be independent')
    return destination

def _source(host):
    require(type(host) is NativeMaterializationHost and type(host.gateway) is NativeEditorGateway,'registered native materialization host required')
    root=host.root;mapping=IdentityMap.from_dict(load_json(root/MAP));verify_baseline_receipts(root,mapping.baseline)
    cgs=load_json(root/CGS);snapshot=Snapshot((root/NATIVE).read_bytes());rows=snapshot.to_dict()['inspection']['normalized']
    pair=SavedPair(root,mapping=mapping,expected_cgs=cgs,expected_normalized=rows,recapture=host.gateway.capture)
    pair.capture_pair() # Dirty canonical/native edits require separate review first.
    files=host.gateway._files();files['game.cgs.json']=file_hash(root/'game.cgs.json')
    history={}
    for path in sorted((io_path(root)/'.xace').rglob('*')):
        confined(io_path(root),path.relative_to(io_path(root)).as_posix())
        relative=path.relative_to(io_path(root)/'.xace').as_posix()
        # Live OS lock byte is synchronization state, not ancestor content.
        if relative=='cgs.write.lock':continue
        if path.is_file():history[relative]=file_hash(path)
        require(len(history)<=100000,'fork history file limit')
    return mapping,cgs,rows,files,history

def _unchanged(root,files,history):
    require(all(confined(root,p).is_file() and file_hash(confined(root,p))==h for p,h in files.items()),'fork source files changed')
    require(all(confined(io_path(root),'.xace/'+p).is_file() and file_hash(confined(io_path(root),'.xace/'+p))==h for p,h in history.items()),'fork ancestor history changed')

def review_fork(host,destination,branch_id,principal):
    token(principal,'principal');destination=destination_path(destination,host.root)
    with host.publication_gate():
        mapping,cgs,rows,files,history=_source(host)
        draft=IdentityDraft(mapping);draft.fork(branch_id);target=draft.snapshot();target.baseline=None
        review=dict(schema='xace.native_workspace_fork_review.v1',principal=principal,source=str(host.root),destination=str(destination),source_host=host.gateway.identity,source_mapping=mapping.to_dict(),target_mapping=target.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows),files=files,ancestor_history=history,history_execution=False,excluded_live_state=['cgs.write.lock'])
        review['review_digest']=digest(review)
        return review

def apply_fork(host,review,approved_digest,principal):
    token(principal,'principal')
    require(type(review) is dict,'fork review required');unsigned=copy.deepcopy(review);claimed=unsigned.pop('review_digest',None)
    require(claimed==approved_digest==digest(unsigned) and review['principal']==principal,'explicit principal-bound fork approval required')
    require(review['schema']=='xace.native_workspace_fork_review.v1' and review['source']==str(host.root) and review['source_host']==host.gateway.identity,'registered fork source changed')
    destination=destination_path(review['destination'],host.root)
    with host.publication_gate():
        mapping,cgs,rows,files,_=_source(host)
        require(mapping.to_dict()==review['source_mapping'] and digest(cgs)==review['cgs_digest'] and digest(rows)==review['normalized_digest'] and files==review['files'],'fork review stale')
        draft=IdentityDraft(mapping);draft.fork(review['target_mapping']['branch_id']);target=draft.snapshot();target.baseline=None
        require(target.to_dict()==review['target_mapping'],'fork identity differs from reviewed branch')
        _unchanged(host.root,files,review['ancestor_history'])
        size=sum(confined(host.root,p).stat().st_size for p in files)+sum(confined(io_path(host.root),'.xace/'+p).stat().st_size for p in review['ancestor_history'])
        require(shutil.disk_usage(destination.parent).free>size+2*1024**3,'fork needs disk reserve; no cleanup performed')
        destination.mkdir(exist_ok=False);durable(destination/'.xace/fork-intent.json',canonical(review))
        for name,expected in files.items():
            source=confined(host.root,name);path=confined(destination,name);path.parent.mkdir(parents=True,exist_ok=True)
            with source.open('rb') as src,path.open('xb') as dst:
                shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
            require(file_hash(path)==expected,'fork copy changed')
        ancestor='.xace/ancestor-history/'+approved_digest
        for name,expected in review['ancestor_history'].items():
            source=confined(io_path(host.root),'.xace/'+name);path=confined(io_path(destination),ancestor+'/'+name);path.parent.mkdir(parents=True,exist_ok=True)
            with source.open('rb') as src,path.open('xb') as dst:
                shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
            require(file_hash(path)==expected,'ancestor history copy changed')
        _unchanged(host.root,files,review['ancestor_history']);require(host.gateway._files()==files_without_cgs(files),'fork source inventory changed')
        original=host.gateway
        gateway=NativeEditorGateway(destination,engine=original.engine,executable=str(original.exe),executable_sha256=original.identity['editor_sha256'],documents=original.documents,source_roots=original.sources,plugin_hashes=original.plugin_hashes,project_file=original.project_file,trusted_closed_project=True)
        child=NativeMaterializationHost(destination,lambda:None,gateway)
        pair=SavedPair(destination,mapping=target,expected_cgs=cgs,expected_normalized=rows,recapture=gateway.capture)
        pair.capture_pair()
        request=TransactionRequest('fork-'+approved_digest[:32],approved_digest,dict(canonical=dict(files=[file_change('game.cgs.json',files['game.cgs.json'],canonical(cgs))]),native=dict(write_request=None)),ACTIVATION,dict(mapping=target.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows)),dict(cgs=cgs,normalized=rows,accepted_loss_digest=None))
        def authorize(_):
            _unchanged(host.root,files,review['ancestor_history']);require(host.gateway._files()==files_without_cgs(files),'fork source inventory changed');return True
        state=child._coordinator(pair).commit(request,authorize=authorize)
        require(state['state']=='committed','fork baseline not committed')
        receipt=dict(schema='xace.native_workspace_fork_receipt.v1',review_digest=approved_digest,source_branch=mapping.branch_id,branch_id=target.branch_id,namespace_id=target.namespace_id,ancestor_history=ancestor,ancestor_files=len(review['ancestor_history']),state='committed',original_journals_rewritten=False)
        durable(destination/'.xace/fork-receipt.json',canonical(receipt));return receipt

def files_without_cgs(files):return {p:h for p,h in files.items() if p!='game.cgs.json'}
