"""NEC-009 GDE commit preparation; durable publication belongs to coordinator."""
from dataclasses import asdict
from .native_adoption_operations import NativeAdoptionExecutor,require
from .native_reconciliation_operations import preview
from ...cgs.cgs_manager import CGSManager
from ..mutation_metadata.mutation_metadata_model import MutationMetadata


def prepare_commit(current,batch,*,transaction_id,validate,gameplay_catalog=None):
    if batch['schema']=='xace.native_adoption_operations.v1':
        result=NativeAdoptionExecutor(validate=validate,gameplay_catalog=gameplay_catalog).execute(batch,current)
    else:
        result=preview(batch,current,validate=validate)
    require(result.changed,'no CGS mutation to publish')
    manager=CGSManager.initialise(current,session_id='native-authoring')
    metadata=MutationMetadata(transaction_id=transaction_id,source='migration',parent_cgs_hash=manager.current_hash,schema_version_target=current['metadata']['schema_version'],description='Reviewed native authoring transaction')
    committed=manager.commit(result.proposed_cgs,metadata,bump='patch')
    candidate=manager.current_cgs;validate(candidate)
    return dict(cgs=candidate,commit=committed,metadata=asdict(metadata))
