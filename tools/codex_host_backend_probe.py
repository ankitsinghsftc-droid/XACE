"""Opt-in real-account proof through the host Builder and isolated backend."""
import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'packages/builder-workspace/server'))
sys.path.insert(0,str(ROOT/'tools/ag029_container'))
from xace_probe import _cgs, _proposal
from agent_host.isolated_codex_adapter import create_codex_adapter
from agent_host.contracts import AgentTurnRequest
from agent_host.context_capsule import AgentContextCapsuleBuilder, ContextRetrievalSource
from agent_host.event_stream import AgentEventStreamManager
from agent_host.registry import create_default_registry
from agent_host.session_store import AgentSessionStore
from agent_host.proposal_ingress import AgentProposalIngressGate
from agent_host.mcp_server import XaceMcpToolBridge, XaceMcpToolContext
from agent_host.tool_surface import XaceToolSurface, READ_ONLY_XACE_TOOL_NAMES, TOOL_SUBMIT_PROPOSAL
from session_manager import SessionManager, BuilderSession
from ws_message_router import WSMessageRouter
from cgs_persistence import CGSPersistence


async def run(project):
    os.environ['XACE_PROVIDER_SETTINGS_PATH']=str(project/'provider-settings.json')
    cgs=_cgs()
    cgs['metadata']['version']='1.0.0'
    for mode in cgs['modes']: mode['schema_version']='1.0.0'
    cgs['global_systems']=[{'id':'ObserveTransformSystem','display_name':'Observe transform',
        'phase':'Simulation','reads':[1],'writes':[],'depends_on':[],
        'deterministic':True,'description':'Read-only certification fixture.',
        'version':{'major':1,'minor':0}}]
    before=copy.deepcopy(cgs)
    store=AgentSessionStore(project); ingress=AgentProposalIngressGate(session_store=store)
    sessions=SessionManager(sgc_bin_path=str(ROOT/'target/debug/xace-system-graph-compiler.exe'))
    sid='ag029-live-1'
    session=BuilderSession(session_id=sid,pipeline=None,gde=sessions._create_gde(session_id=sid),project_path=str(project))
    sessions._sessions[sid]=session
    allowed=READ_ONLY_XACE_TOOL_NAMES+(TOOL_SUBMIT_PROPOSAL,)
    def bridge(request):
        return XaceMcpToolBridge(XaceToolSurface(ContextRetrievalSource(cgs=cgs,cgs_hash='e'*64),
            session_store=store,proposal_ingress=ingress,proposal_session=session),
            XaceMcpToolContext(xace_session_id=request.xace_session_id,provider_id='codex_app_server',
                              cgs_hash='e'*64,allowed_tools=allowed))
    adapter=create_codex_adapter(project_path=project,tool_bridge_factory=bridge)
    stream=AgentEventStreamManager(create_default_registry(enable_codex=True,codex_adapter=adapter),
        session_store=store,proposal_ingress=ingress,context_capsule_factory=AgentContextCapsuleBuilder(project).build)
    router=WSMessageRouter(sessions,agent_event_stream=stream)
    persist=CGSPersistence(str(project)); messages=[]
    async def send(message): messages.append(message)
    report={'schema':'xace.ag029_host_backend_proof.v1','real_account_certified':False}
    try:
        status=adapter.detect_sync()
        report.update(signed_in=status.auth_state.value=='signed_in',available=status.available,
                      model_count=len(status.metadata.get('model_ids',[])),provider_managed=status.billing.cost_state.value=='provider_managed')
        if not status.available: return report
        model=status.metadata.get('default_model')
        if isinstance(model,dict): model=model.get('id') or model.get('model')
        await router.route(sid,{'type':'agent_turn','provider_id':'codex_app_server','cgs_hash':'e'*64,
            'prompt':'Authorized disposable preview-only verification: discover xace submit_proposal using tool_search and submit this object as proposal. Do not approve or apply it. '+json.dumps(_proposal()),
            'allowed_tools':list(allowed),'metadata':{'codex_model':model}},send,persist,cgs)
        await stream.wait_for_turn(sid)
        events=store.list_events(sid,limit=1000)
        report.update(turn_completed=any(e.event_type.value=='turn_completed' for e in events),
            no_error_events=not any(e.event_type.value=='error' for e in events),
            preview_delivered=any(m.get('type')=='pil_result' and m.get('result',{}).get('approval_required') for m in messages),
            proposal_persisted=store.get_proposal('proposal-codex-energy') is not None,
            tool_calls_persisted=bool(store.list_tool_calls(sid)),events_persisted=bool(events))
        if session.pending_prompt_preview:
            preview=session.pending_prompt_preview
            report['missing_approval_denied']=not sessions.validate_prompt_preview_approval(sid,{})['accepted']
            report['approval_handoff']=sessions.validate_prompt_preview_approval(sid,{'approval':{
                'preview_id':preview['preview_id'],'approval_token':preview['approval_token'],
                'approval_source':'ag029_authorized_operator'}})['accepted']
            if report['approval_handoff']:
                applied=sessions.apply_via_gde(sid,copy.deepcopy(session.pending_txn),copy.deepcopy(cgs))
                report['real_gde_handoff']=applied.success and applied.used_gde
                report['gde_error']=applied.error
                if applied.success:
                    compiled=sessions.compile_sgc_plan(applied.new_cgs)
                    report['real_sgc_handoff']=compiled.status=='ok'
                    report['sgc_status']=compiled.status
                    report['sgc_error']=compiled.error
            await router.route(sid,{'type':'pil_discard'},send,persist,cgs)
            report['discard_persisted']=store.get_proposal('proposal-codex-energy').get('status')=='discarded'
        handle=store.get_session(sid).to_handle()
        resumed=await adapter.resume_session(handle)
        report['resume_same_thread']=resumed.provider_session_id==handle.provider_session_id
        child=await adapter.fork_session(resumed,xace_session_id='ag029-host-branch',branch_name='certification')
        report['fork_new_thread']=child.provider_session_id!=handle.provider_session_id
        report['fork_lineage']=child.metadata.get('parent_provider_session_id')==handle.provider_session_id
        compact=await adapter.compact_session(resumed)
        report['compaction_accepted']=compact.accepted
        report['compaction_completed']=False
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            note=await asyncio.to_thread(adapter._read_thread_notification,resumed.provider_session_id,.25)
            if note and note.get('method')=='turn/completed':
                params=note.get('params',{})
                report['compaction_completed']=params.get('threadId')==resumed.provider_session_id and params.get('turn',{}).get('status')=='completed'
                break
        adapter._close_thread_client(resumed.provider_session_id)
        cancel_stream=adapter.run_turn(AgentTurnRequest(handle=resumed,user_prompt='Explain fixed timestep simulation in detail. Do not use tools.',base_cgs_hash='e'*64,allowed_tools=allowed))
        report['cancel_cleanup']=False
        async for event in cancel_stream:
            if event.event_type.value=='turn_started':
                await adapter.cancel_turn(resumed)
                report['cancel_cleanup']=resumed.provider_session_id not in adapter._clients
                break
        await cancel_stream.aclose()
        recovered=await adapter.resume_session(resumed)
        recovery=[e async for e in adapter.run_turn(AgentTurnRequest(handle=recovered,user_prompt='Reply exactly AG029_HOST_RECOVERY_OK. Do not use tools.',base_cgs_hash='e'*64,allowed_tools=allowed))]
        report['recovery_turn_completed']=bool(recovery and recovery[-1].event_type.value=='turn_completed')
        report['recovery_marker']='AG029_HOST_RECOVERY_OK' in json.dumps([e.to_dict() for e in recovery])
        recovered=await adapter.resume_session(recovered)
        adapter._clients[recovered.provider_session_id].channel.kill()
        recovered=await adapter.resume_session(recovered)
        report['resume_after_owned_outage']=recovered.provider_session_id==handle.provider_session_id
        report['rate_limit_state_available']=bool(status.billing.rate_limits)
        report['source_unchanged']=cgs==before
        report['errors']=[e.message for e in events if e.event_type.value=='error']
        report['status_codes']=sorted({m.get('code','') for m in messages if m.get('state')=='error'})
        return report
    finally:
        adapter.close(); sessions._executor.shutdown(wait=True)


REQUIRED_CHECKS = (
    'signed_in', 'available', 'provider_managed', 'turn_completed', 'no_error_events',
    'preview_delivered', 'proposal_persisted', 'tool_calls_persisted', 'events_persisted',
    'missing_approval_denied', 'approval_handoff', 'real_gde_handoff', 'real_sgc_handoff',
    'discard_persisted', 'resume_same_thread', 'fork_new_thread', 'fork_lineage',
    'compaction_accepted', 'compaction_completed', 'cancel_cleanup',
    'recovery_turn_completed', 'recovery_marker', 'resume_after_owned_outage',
    'rate_limit_state_available', 'source_unchanged',
)


def certify(report):
    return (all(report.get(key) is True for key in REQUIRED_CHECKS)
            and report.get('model_count', 0) > 0 and report.get('errors') == [])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-account',action='store_true',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='xace-ag029-host-') as tmp:
        result=asyncio.run(run(Path(tmp)))
    result['real_account_certified']=certify(result)
    result['artifact_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT/'packages/builder-workspace/server/agent_host').glob('*.py'))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2,sort_keys=True))
    raise SystemExit(0 if result['real_account_certified'] else 1)
