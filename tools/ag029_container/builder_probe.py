"""Real-account Builder router/SQLite proof on a disposable project only."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,'/xace/packages/builder-workspace/server')
from xace_probe import _cgs, _proposal
from agent_host.codex_linux_profile import CodexLinuxProfileAdapter
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


async def main():
    project = Path('/tmp/ag029-builder-project')
    root = project / '.xace/agent_capsules'
    root.mkdir(parents=True)
    os.environ['XACE_PROVIDER_SETTINGS_PATH'] = str(project / 'provider-settings.json')
    cgs = _cgs()
    before = copy.deepcopy(cgs)
    session_id = 'ag029-live-1'
    store = AgentSessionStore(project)
    ingress = AgentProposalIngressGate(session_store=store)
    sessions = SessionManager()
    session = BuilderSession(session_id=session_id,pipeline=None,gde=None,project_path=str(project))
    sessions._sessions[session_id] = session
    persist = CGSPersistence(str(project))
    allowed = READ_ONLY_XACE_TOOL_NAMES + (TOOL_SUBMIT_PROPOSAL,)

    def bridge(request):
        return XaceMcpToolBridge(XaceToolSurface(ContextRetrievalSource(cgs=cgs,cgs_hash='e'*64),
            session_store=store,proposal_ingress=ingress,proposal_session=session),
            XaceMcpToolContext(xace_session_id=request.xace_session_id,provider_id='codex_app_server',
                               cgs_hash='e'*64,allowed_tools=allowed))

    adapter = CodexLinuxProfileAdapter(executable='/usr/local/bin/codex',provider_home=Path('/provider'),
                                       capsule_root=root,tool_bridge_factory=bridge,turn_idle_timeout_seconds=60)
    stream = AgentEventStreamManager(create_default_registry(enable_codex=True,codex_adapter=adapter),
        session_store=store,proposal_ingress=ingress,context_capsule_factory=AgentContextCapsuleBuilder(project).build)
    router = WSMessageRouter(sessions,agent_event_stream=stream)
    messages = []
    async def send(message): messages.append(message)
    report = {'schema':'xace.ag029_builder_probe.v1','real_account_certified':False,
              'account_calls_performed':True,'model_turns_performed':1}
    try:
        status = adapter.detect_sync()
        model = status.metadata.get('default_model')
        if isinstance(model,dict): model = model.get('id') or model.get('model')
        await router.route(session_id,{'type':'agent_turn','provider_id':'codex_app_server',
            'prompt':'For this authorized disposable preview-only certification, discover xace submit_proposal with tool_search and submit this object as the proposal argument. Do not approve or apply it. '+json.dumps(_proposal()),
            'cgs_hash':'e'*64,'allowed_tools':list(allowed),'metadata':{'codex_model':model}},
            send,persist,cgs)
        await stream.wait_for_turn(session_id)
        events = store.list_events(session_id,limit=1000)
        report['events_persisted'] = bool(events)
        report['turn_completed'] = any(e.event_type.value == 'turn_completed' for e in events)
        report['no_error_events'] = not any(e.event_type.value == 'error' for e in events)
        report['preview_delivered'] = any(m.get('type')=='pil_result' and m.get('result',{}).get('approval_required') for m in messages)
        report['pending_preview'] = bool(session.pending_prompt_preview and session.pending_txn)
        report['source_unchanged_before_approval'] = cgs == before
        report['proposal_persisted'] = store.get_proposal('proposal-codex-energy') is not None
        report['tool_calls_persisted'] = bool(store.list_tool_calls(session_id))
        if session.pending_prompt_preview:
            await router.route(session_id,{'type':'pil_discard'},send,persist,cgs)
            report['discard_acknowledged'] = any(m.get('type')=='pil_discard_ack' for m in messages)
            report['discard_cleared_pending'] = session.pending_txn is None and session.pending_prompt_preview is None
            report['discard_persisted'] = store.get_proposal('proposal-codex-energy').get('status') == 'discarded'
        report['source_unchanged_after_discard'] = cgs == before
        report['error_codes'] = sorted({str(m.get('code')) for m in messages if m.get('state')=='error'})
        print(json.dumps(report,sort_keys=True))
    finally:
        adapter.close()
        sessions._executor.shutdown(wait=True)


if __name__ == '__main__':
    asyncio.run(main())
