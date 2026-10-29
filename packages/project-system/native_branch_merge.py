"""Explicit approved sibling-transform merge through GDE and native coordinator."""
import copy,json,os
from authoring_identity import IdentityMap,canonical,digest,require,token
from authoring_transaction_files import confined,load_json,sha
from authoring_apply import gde,file_change,ACTIVATION,apply_prepared
from authoring_saved_pair import SavedPair,MAP
from native_adoption import factory,bridge
from native_reconciliation_plan import TRANSFORMS,_native_transform
from native_branch_contribution import _plan_contribution_unlocked

def _review(host,payload,principal,resolutions):
    token(principal,'principal')
    review=_plan_contribution_unlocked(host,payload,sha(payload),resolutions=resolutions)
    review.update(principal=principal,resolutions=copy.deepcopy(resolutions))
    review['review_digest']=digest(review);return review

def review_branch_merge(host,payload,principal,*,resolutions=None):
    with host.publication_gate():return _review(host,payload,principal,resolutions)

def _prepare(host,payload,review,transaction_id):
    current=load_json(host.root/'game.cgs.json');mapping=IdentityMap.from_dict(load_json(host.root/MAP));raw=host.gateway.capture()
    require(digest(current)==review['receiver_cgs_digest'] and sha(raw)==review['receiver_native_digest'] and mapping.to_dict()==review['receiver_mapping'],'receiver changed during merge preparation')
    report=review['report'];require(report['reviewable'],'unresolved or unsupported branch merge')
    operations=report['typed_operations']
    committed=gde.prepare_commit(current,operations,transaction_id=transaction_id,validate=factory.compile_portable_cgs) if operations['operations'] else dict(cgs=copy.deepcopy(current),commit=None,metadata=None)
    reader=bridge(mapping.engine);base=reader.capture(raw,mapping,enable_writes=True).admit();rows=report['merge']['merged'];target=json.loads(raw)
    for key,row in rows.items():
        for field in TRANSFORMS:
            if field in row['fields']:target['objects'][key]['fields'][field]=_native_transform(mapping.engine,field,row['fields'][field])
    desired=reader.capture(canonical(target),mapping,enable_writes=True).admit();require(desired.to_dict()['inspection']['normalized']==rows,'merge cannot be materialized exactly')
    native=None if base.to_dict()['inspection']['normalized']==rows else json.loads(reader.write_request(raw,base,desired,mapping))
    actual=(host.root/'game.cgs.json').read_bytes();require(digest(json.loads(actual))==digest(current),'canonical source changed')
    mapping.baseline=None
    return dict(schema='xace.authoring_apply_preparation.v1',proposal_digest=review['review_digest'],cgs=committed,canonical_request=dict(files=[file_change('game.cgs.json',sha(actual),canonical(committed['cgs']))]),target_mapping=mapping.to_dict(),expected_normalized=rows,native_request=native,source_digest=sha(raw),mapping_digest=mapping.mapping_digest(),activation_record=copy.deepcopy(ACTIVATION),accepted_loss_digest=None)

def _retain(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():require(path.read_bytes()==data,'retained merge artifact changed');return
    with path.open('xb') as output:output.write(data);output.flush();os.fsync(output.fileno())

def apply_branch_merge(host,payload,review,principal,approved_digest):
    token(principal,'principal');unsigned=copy.deepcopy(review);claimed=unsigned.pop('review_digest',None)
    require(claimed==approved_digest==digest(unsigned) and review['principal']==principal,'explicit principal-bound merge approval required')
    require(review['contribution_sha256']==sha(payload),'different branch contribution')
    fresh=review_branch_merge(host,payload,principal,resolutions=review['resolutions']);require(fresh==review,'branch merge review stale')
    require(review['report']['reviewable'],'branch merge has unresolved conflicts')
    if review['report']['noop']:return dict(state='noop',files_written=False,runtime_activation=False)
    transaction_id='merge-'+approved_digest[:32]
    prepared=_prepare(host,payload,review,transaction_id)
    history=confined(host.root,'.xace/branch-merges/'+approved_digest)
    _retain(history/'contribution.json',payload);_retain(history/'review.json',canonical(review))
    pair=SavedPair(host.root,mapping=IdentityMap.from_dict(prepared['target_mapping']),expected_cgs=prepared['cgs']['cgs'],expected_normalized=prepared['expected_normalized'],recapture=host.gateway.capture)
    def refreshed():
        # The coordinator already holds the receiver lock at this boundary.
        current=_review(host,payload,principal,review['resolutions']);require(current==review,'receiver changed since approved branch merge')
        return _prepare(host,payload,current,transaction_id)
    state=apply_prepared(host._coordinator(pair),prepared,transaction_id=transaction_id,native_participant_request=dict(write_request=prepared['native_request']),authorize=lambda _:True,refresh_preparation=refreshed)
    return dict(state=state['state'],transaction_id=transaction_id,files_written=True,runtime_activation=False,contribution_sha256=sha(payload))
