"""Explicit host-owned NEC010 review/apply bridge; no runtime activation.

The configured host supplies trusted fresh native extraction and a pinned native
writer gateway. No browser request can choose a project path or executable.
"""
import threading
from pathlib import Path
from authoring_identity import IdentityMap,require
from authoring_apply import prepare_apply,apply_prepared
from authoring_native_participant import NativeParticipant
from authoring_transaction import AuthoringCoordinator
from authoring_transaction_files import FileParticipant
from authoring_saved_pair import SavedPair,MAP,CGS,NATIVE
from native_reconciliation_review import ReconciliationReview


class NativeMaterializationHost:
    def __init__(self,root,context_provider,gateway):
        self.root=Path(root).resolve();self.gateway=gateway
        require(callable(gateway.capture),'fresh native capture required')
        self.review=ReconciliationReview(context_provider)
        self._lock=threading.RLock()

    def _coordinator(self,pair=None):
        baseline=FileParticipant(self.root,name='verified-baseline',allowed_paths=[MAP,CGS,NATIVE])
        return AuthoringCoordinator(self.root,
            dict(canonical=FileParticipant(self.root,name='canonical',allowed_paths=['game.cgs.json']),native=NativeParticipant(self.gateway)),
            verify_pair=pair.verify if pair else lambda *_:False,
            baseline_participant=pair.participant if pair else baseline,
            baseline_request=pair.baseline_request if pair else lambda *_:None)

    def status(self):
        return self._coordinator().status()

    def publication_gate(self):
        # Hosting entry points must hold this context through Play/build admission.
        return self._coordinator().publication_gate()

    def apply(self,principal,approval,expected_proposal_digest):
        """Called only by an explicit apply action after separate review approval."""
        require(type(expected_proposal_digest) is str,'reviewed proposal digest required')
        with self._lock:
            plan,context=self.review.approved_context(principal,approval)
            require(plan.sha256==expected_proposal_digest,'apply differs from reviewed proposal')
            self._coordinator().require_ready()
            if plan.to_dict()['noop']:
                return dict(schema='xace.native_materialization_result.v1',state='noop',files_written=False,runtime_activation=False)
            # Review session+proposal uniquely identifies this attempt. A durable
            # incomplete journal must be recovered explicitly, never retried blind.
            from native_adoption import digest
            transaction_id='apply-'+digest(dict(session=approval['session'],proposal=plan.sha256))[:32]
            def fresh():
                current,inputs=self.review.approved_context(principal,approval)
                return prepare_apply(current,context=inputs,transaction_id=transaction_id,project_root=self.root)
            prepared=fresh()
            pair=SavedPair(self.root,mapping=IdentityMap.from_dict(prepared['target_mapping']),
                expected_cgs=prepared['cgs']['cgs'],expected_normalized=prepared['expected_normalized'],
                recapture=self.gateway.capture,accepted_loss_digest=context.get('accepted_loss_digest'))
            coordinator=self._coordinator(pair)
            state=apply_prepared(coordinator,prepared,transaction_id=transaction_id,
                native_participant_request=dict(write_request=prepared['native_request']),
                authorize=lambda _:self.review.verify_approval(principal,approval).sha256==expected_proposal_digest,
                refresh_preparation=fresh)
            self.review.cancel(principal,approval['session'])
            return dict(schema='xace.native_materialization_result.v1',state=state['state'],transaction_id=transaction_id,
                files_written=True,runtime_activation=False)
