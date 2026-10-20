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

    def poll_saved_changes(self):
        """Optional saved-change notification; existing approval flow stays mandatory."""
        import json, time
        from native_saved_changes import SavedChangeBatcher, SavedRevision
        from native_adoption import digest
        with self._lock:
            if not hasattr(self, '_saved_changes'):
                self._saved_changes = SavedChangeBatcher()
            try:
                self._coordinator().require_ready()
                context = self.review.context_provider()
                raw = context['native_inventory']
                source = json.loads(raw)['source']
                require(source.get('play_mode') is False, 'Stop Play before saved-change review')
                require(bool(source.get('documents')) and all(d.get('dirty') is False for d in source['documents']), 'Save native documents before review')
                require(digest(context['current_cgs']) == context['expected_current_cgs_digest'], 'Canonical observation changed')
                from authoring_transaction_files import sha
                require(sha(raw) == context['expected_source_digest'], 'Native observation changed')
                revision = SavedRevision(context['expected_current_cgs_digest'], context['expected_source_digest'], digest(context['current_mapping'].to_dict()))
                state = self._saved_changes.observe(revision, time.monotonic())
            except Exception:
                self._saved_changes.invalidate()
                raise
            return dict(schema='xace.native_saved_changes.v1', state=state,
                        requires_explicit_review=True, can_commit=False)

    def _coordinator(self,pair=None,native=None):
        baseline=FileParticipant(self.root,name='verified-baseline',allowed_paths=[MAP,CGS,NATIVE])
        return AuthoringCoordinator(self.root,
            dict(canonical=FileParticipant(self.root,name='canonical',allowed_paths=['game.cgs.json']),native=native or NativeParticipant(self.gateway)),
            verify_pair=pair.verify if pair else lambda *_:False,
            baseline_participant=pair.participant if pair else baseline,
            baseline_request=pair.baseline_request if pair else lambda *_:None,historical_participants=self._historical_participants)

    def _historical_participants(self,identities):
        from native_setup_bundle import registered_setup_bundle
        canonical=FileParticipant(self.root,name='canonical',allowed_paths=['game.cgs.json'])
        native=NativeParticipant(self.gateway)
        if identities.get('native')!=native.identity:
            native=registered_setup_bundle(self.root,self.gateway.identity['engine'],identities.get('native'))
        return dict(canonical=canonical,native=native)

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

    def recover(self,transaction_id,*,action='resume'):
        """Explicit host recovery; no lost browser approval or new plan required.

        Resume uses only the already durable decision, bound to the registered
        gateway and stored payload digests. It cannot authorize another proposal.
        """
        from native_adoption import digest
        with self._lock:
            from authoring_transaction_files import load_json,confined
            manifest=load_json(confined(self.root,'.xace/authoring-transactions/'+transaction_id+'/manifest.json'))
            participants=self._historical_participants(manifest['participants'])
            coordinator=self._coordinator(native=participants['native'])
            def configure(state,manifest):
                if (action=='rollback' and state['state']!='committed') or state['state'] in {'preparing','aborted','rolled_back'}:
                    return
                request=manifest['request'];payload=request.get('recovery_payload')
                require(type(payload) is dict,'saved recovery payload unavailable; explicit rollback required')
                decision=request['verification_record']
                require(digest(payload['cgs'])==decision['cgs_digest'] and
                        digest(payload['normalized'])==decision['normalized_digest'],
                        'recovery payload differs from durable decision')
                pair=SavedPair(self.root,mapping=IdentityMap.from_dict(decision['mapping']),
                    expected_cgs=payload['cgs'],expected_normalized=payload['normalized'],
                    recapture=self.gateway.capture,accepted_loss_digest=payload.get('accepted_loss_digest'))
                coordinator.verify_pair=pair.verify
                coordinator.baseline_participant=pair.participant
                coordinator.baseline_request=pair.baseline_request
            return coordinator.recover(transaction_id,action=action,configure_verification=configure)
