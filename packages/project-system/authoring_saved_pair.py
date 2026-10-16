"""NEC-009 verified saved-pair baseline for the admitted transform profile.

The host supplies a fresh trusted editor capture, never a cached preview. Baseline
files are a third recoverable participant and are published only after both stores
verify. This is authoring evidence, not an execution-plan admission receipt.
"""
import copy
from pathlib import Path

from authoring_identity import IdentityMap,Baseline,require
from native_adoption import bridge,digest,encode,factory
from native_reconciliation_plan import _project
from tools.cgs_schema_validate import compute_cgs_hash
from authoring_transaction_files import FileParticipant,load_json,confined
from authoring_apply import file_change

MAP='.xace/authoring-identity.json'
CGS='.xace/authoring-baseline.cgs.json'
NATIVE='.xace/authoring-baseline.native.json'


class SavedPair:
    def __init__(self,root,*,mapping,expected_cgs,expected_normalized,recapture,accepted_loss_digest=None):
        self.root=Path(root);self.mapping=copy.deepcopy(mapping);self.mapping.validate()
        self.expected_cgs=copy.deepcopy(expected_cgs);self.rows=copy.deepcopy(expected_normalized)
        require(callable(recapture),'fresh trusted editor recapture required')
        self.recapture=recapture;self.accepted_loss_digest=accepted_loss_digest
        self.participant=FileParticipant(root,name='verified-baseline',allowed_paths=[MAP,CGS,NATIVE])

    def capture_pair(self):
        current=load_json(confined(self.root,'game.cgs.json'))
        require(digest(current)==digest(self.expected_cgs),'saved canonical revision differs from decision')
        require(current['metadata']['cgs_hash']==compute_cgs_hash(current),'saved CGS hash invalid')
        factory.compile_portable_cgs(current)
        reader=bridge(self.mapping.engine)
        snapshot=reader.capture(self.recapture(),self.mapping,enable_writes=True).admit(self.accepted_loss_digest)
        rows=snapshot.to_dict()['inspection']['normalized']
        require(rows==self.rows,'saved native revision differs from decision')
        require(_project(current,rows,self.mapping)==rows,'saved CGS/native projection disagrees')
        require(any(r.world_binding for r in self.mapping.objects.values()),'verified bound authoring slice required')
        return current,snapshot

    def verify(self,manifest,tokens):
        expected=dict(mapping=self.mapping.to_dict(),cgs_digest=digest(self.expected_cgs),normalized_digest=digest(self.rows))
        require(manifest['request'].get('verification_record')==expected,'saved-pair verifier differs from durable decision')
        self.capture_pair()
        return True

    def baseline_request(self,manifest,receipts):
        require(set(receipts)=={'canonical','native'} and all(r['state']=='after' for r in receipts.values()),'verified pair receipts required')
        self.verify(manifest,{})
        cgs,snapshot=self.capture_pair()
        mapping=copy.deepcopy(self.mapping)
        mapping.baseline=Baseline(digest(cgs),snapshot.sha256,mapping.mapping_digest(),
            '.xace/authoring-transactions/'+manifest['transaction_id'],digest(receipts['canonical']),digest(receipts['native']))
        mapping.validate()
        data={MAP:encode(mapping.to_dict()),CGS:encode(cgs),NATIVE:snapshot.payload}
        return dict(files=[file_change(p,manifest['baseline_before'][p],data[p]) for p in sorted(data)])


def verify_baseline_receipts(root,baseline):
    """NEC-008 host callback: historical decision/receipts, plus saved snapshots.

    Does not require the current working CGS/native files still equal the baseline:
    that would prevent three-way editing. Full fresh pair validation happens when
    the coordinator publishes; journal hashes alone do not authorize a new write.
    """
    root=Path(root);baseline.validate()
    require(baseline.journal_ref.startswith('.xace/authoring-transactions/'),'foreign baseline journal')
    folder=confined(root,baseline.journal_ref)
    state=load_json(folder/'state.json');manifest=load_json(folder/'manifest.json')
    require(state['state']=='committed' and state['manifest_digest']==digest(manifest),'baseline decision not committed')
    require(digest(state['receipts']['canonical'])==baseline.canonical_receipt and digest(state['receipts']['native'])==baseline.native_receipt,'baseline receipts differ')
    mapping=IdentityMap.from_dict(load_json(confined(root,MAP)))
    require(mapping.baseline==baseline and mapping.mapping_digest()==baseline.mapping_digest,'baseline mapping differs')
    require(digest(load_json(confined(root,CGS)))==baseline.cgs_digest,'baseline CGS differs')
    from native_authoring_contract import load_snapshot
    snapshot=load_snapshot(confined(root,NATIVE).read_bytes(),mapping,bridge(mapping.engine).policy(enable_writes=True))
    require(snapshot.sha256==baseline.native_snapshot_digest,'baseline native snapshot differs')
    decision=manifest['request']['verification_record'];without_baseline=copy.deepcopy(mapping);without_baseline.baseline=None
    cgs=load_json(confined(root,CGS));rows=snapshot.to_dict()['inspection']['normalized']
    require(decision==dict(mapping=without_baseline.to_dict(),cgs_digest=digest(cgs),normalized_digest=digest(rows)),'baseline differs from approved saved-pair contract')
    require(cgs['metadata']['cgs_hash']==compute_cgs_hash(cgs),'baseline CGS hash invalid')
    factory.compile_portable_cgs(cgs)
    require(_project(cgs,rows,mapping)==rows,'baseline canonical/native projection disagrees')
    return True
