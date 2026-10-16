"""NEC-009 explicit migration/reconciliation apply preparation through GDE.

Publication requires a separately authorized coordinator call. A NEC-008 review
signature by itself does not grant write permission. No runtime activation occurs.
"""
import base64
import copy
import importlib
from pathlib import Path

from authoring_identity import require,WorldBinding
from native_adoption import verify_plan,digest,encode,factory,bridge,actor_id
from native_reconciliation_plan import plan_reconciliation
from authoring_transaction_files import sha,load_json,confined
from authoring_transaction_contract import TransactionRequest

gde=importlib.import_module('gde.src.domain_dsl.typed_operations.native_authoring_commit')
ACTIVATION={'performed':False,'policy':'preserve_existing_session_require_explicit_restart'}


def file_change(path,before,data):
    return dict(path=path,before=before,after_base64=base64.b64encode(data).decode('ascii'))


def prepare_apply(plan,*,context:dict,transaction_id:str,project_root:Path):
    report=plan.to_dict()
    if report['schema']=='xace.native_adoption_plan.v1':
        verify_plan(plan,**context);require(report['candidate_valid'],'adoption is blocked')
        native=report['native_write_preview'];require(len(native)<=1,'multiple native write requests require separate participant profile')
        native=native[0] if native else None
    elif report['schema']=='xace.native_reconciliation_plan.v1':
        require(plan_reconciliation(**context).payload==plan.payload,'stale/tampered reconciliation')
        require(report['reviewable'],'reconciliation is blocked');native=report['native_write_preview']
    else:raise ValueError('unsupported authoring proposal')
    current=context['current_cgs'];root=Path(project_root)
    mapping_path=confined(root,'.xace/authoring-identity.json')
    if mapping_path.exists():require(load_json(mapping_path)==context['mapping'].to_dict(),'saved identity mapping differs from review')
    disk=(root/'game.cgs.json').read_bytes()
    import json
    require(digest(json.loads(disk))==digest(current),'saved CGS differs from reviewed CGS')
    if report['typed_operations']['operations']:
        committed=gde.prepare_commit(current,report['typed_operations'],transaction_id=transaction_id,validate=factory.compile_portable_cgs,gameplay_catalog=context.get('gameplay_catalog'))
    else:
        committed=dict(cgs=copy.deepcopy(current),commit=None,metadata=None)
    cgs=committed['cgs'];compiled=factory.compile_portable_cgs(cgs)
    mapping=copy.deepcopy(context['mapping'])
    if report['schema']=='xace.native_adoption_plan.v1':
        for key in report['selected']:
            aid=actor_id(mapping,key);binding=WorldBinding(aid,aid,0)
            require(mapping.objects[key].world_binding in (None,binding),'adoption binding conflicts')
            mapping.objects[key].world_binding=binding
        snapshot=context.get('native_target') or bridge(mapping.engine).capture(context['native_inventory'],mapping,enable_writes=True).admit(context.get('accepted_loss_digest'))
        expected_normalized=snapshot.to_dict()['inspection']['normalized']
    else:expected_normalized=report['merge']['merged']
    mapping.baseline=None;mapping.validate()
    return dict(schema='xace.authoring_apply_preparation.v1',proposal_digest=plan.sha256,
                cgs=committed,canonical_request=dict(files=[file_change('game.cgs.json',sha(disk),encode(cgs))]),
                target_mapping=mapping.to_dict(),expected_normalized=expected_normalized,
                native_request=native,source_digest=context['expected_source_digest'],
                mapping_digest=context['mapping'].mapping_digest(),sgc_input=compiled.to_sgc_input(),
                world=compiled.world_contract.content() if compiled.world_contract else None,
                activation_record=copy.deepcopy(ACTIVATION),accepted_loss_digest=context.get('accepted_loss_digest'))


def apply_prepared(coordinator,prepared,*,transaction_id,native_participant_request,authorize,refresh_preparation):
    """Host wires the pinned native gateway and saved-pair verifier explicitly.

    authorize must recheck the reviewed proposal, native source, map and receipts
    and separately establish publication permission while the coordinator holds
    the shared CGS write lock. No browser/path-derived participant is accepted.
    """
    require(set(coordinator.participants)=={'canonical','native'},'canonical/native participants required')
    require(native_participant_request.get('write_request')==prepared['native_request'],'native participant request differs from reviewed write')
    verification=dict(mapping=prepared['target_mapping'],cgs_digest=digest(prepared['cgs']['cgs']),normalized_digest=digest(prepared['expected_normalized']))
    recovery=dict(cgs=prepared['cgs']['cgs'],normalized=prepared['expected_normalized'],accepted_loss_digest=prepared.get('accepted_loss_digest'))
    request=TransactionRequest(transaction_id,prepared['proposal_digest'],dict(canonical=prepared['canonical_request'],native=native_participant_request),prepared['activation_record'],verification,recovery)
    keys=['proposal_digest','canonical_request','native_request','source_digest','mapping_digest','activation_record','target_mapping','expected_normalized','accepted_loss_digest']
    expected=digest({k:prepared[k] for k in keys})
    def fresh_approval(request):
        fresh=refresh_preparation()
        require(digest({k:fresh[k] for k in keys})==expected,'prepared publication changed; regenerate review')
        return authorize(request) is True
    return coordinator.commit(request,authorize=fresh_approval)
