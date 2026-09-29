"""Bounded real-account AG-029 adapter/MCP probe; emits no credentials."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0,'/xace/packages/builder-workspace/server')
from agent_host.codex_linux_profile import CodexLinuxProfileAdapter
from agent_host.context_capsule import ContextRetrievalSource
from agent_host.contracts import AgentStartRequest, AgentTurnRequest
from agent_host.mcp_server import XaceMcpToolBridge, XaceMcpToolContext
from agent_host.tool_surface import XaceToolSurface, READ_ONLY_XACE_TOOL_NAMES, TOOL_SUBMIT_PROPOSAL
from agent_host.proposal_ingress import AgentProposalIngressGate
from agent_host.session_store import AgentSessionStore
from session_manager import BuilderSession, SessionManager
from types import SimpleNamespace
import copy
import time
from dataclasses import replace

def _cgs() -> dict:
    return {
        "metadata": {"name": "Codex Proposal Fixture", "cgs_hash": 'e'*64},
        "component_schemas": [
            {
                "type_id": 1,
                "name": "COMP_TRANSFORM_V1",
                "defaults": {"x": 0, "y": 0},
                "source": "ucl",
            }
        ],
        "global_systems": [],
        "semantic_events": [],
        "assets": [],
        "modes": [
            {
                "id": "mode_gameplay",
                "is_default": True,
                "actors": [
                    {
                        "id": "actor_player",
                        "actor_type": "PlayerCharacter",
                        "control_type": "Human",
                        "components": [
                            {
                                "type_id": 1,
                                "name": "COMP_TRANSFORM_V1",
                                "defaults": {"x": 0, "y": 0},
                            }
                        ],
                    }
                ],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _proposal(*, base_cgs_hash: str = 'e'*64) -> dict:
    return {
        "proposal_id": "proposal-codex-energy",
        "session_id": "ag029-live-1",
        "provider_id": 'codex_app_server',
        "base_cgs_hash": base_cgs_hash,
        "intent": "Add a deterministic energy resource.",
        "summary": "Declare and attach deterministic typed energy state.",
        "proposal_kind": "mutation",
        "risk_level": "medium",
        "operations": [
            {
                "operation_id": "declare.energy",
                "kind": "declare_component",
                "explanation": "Declare deterministic fixed-point energy state.",
                "component_type_id": 10000,
                "component_name": "COMP_ENERGY_V1",
                "version": "1.0.0",
                "fields": [
                    {"name": "current", "field_type": "fixed", "default": 1000000},
                    {"name": "maximum", "field_type": "fixed", "default": 1000000},
                ],
            },
            {
                "operation_id": "attach.energy",
                "kind": "add_component",
                "explanation": "Attach energy state to the player.",
                "mode_id": "mode_gameplay",
                "actor_id": "actor_player",
                "component_type_id": 10000,
                "component_name": "COMP_ENERGY_V1",
                "defaults": [
                    {"field_name": "current", "field_type": "fixed", "value": 750000}
                ],
                "use_schema_defaults": True,
            },
        ],
    }





async def main():
    root = Path('/tmp/ag029-project/.xace/agent_capsules')
    capsule = root / 'session-1'
    capsule.mkdir(parents=True)
    capsule_file = capsule / 'context.json'
    capsule_file.write_text(json.dumps({'purpose':'AG-029 disposable certification'}))
    cgs_hash = 'e'*64
    cgs = _cgs()
    original_cgs = copy.deepcopy(cgs)
    store = AgentSessionStore(root.parent.parent)
    pending = BuilderSession(session_id='ag029-live-1',pipeline=None,gde=None)
    approval_owner = SimpleNamespace(_sessions={'ag029-live-1':pending})
    bridge = XaceMcpToolBridge(XaceToolSurface(ContextRetrievalSource(
        cgs=cgs,
        cgs_hash=cgs_hash,diagnostics=({'code':'AG029_NATIVE_MCP_OK','severity':'info'},)),
        session_store=store,proposal_ingress=AgentProposalIngressGate(session_store=store),proposal_session=pending),
        XaceMcpToolContext(xace_session_id='ag029-live-1',provider_id='codex_app_server',cgs_hash=cgs_hash,
            allowed_tools=READ_ONLY_XACE_TOOL_NAMES+(TOOL_SUBMIT_PROPOSAL,)))
    adapter = CodexLinuxProfileAdapter(executable='/usr/local/bin/codex',provider_home=Path('/provider'),
                                       capsule_root=root,tool_bridge_factory=lambda request:XaceMcpToolBridge(bridge.surface,replace(bridge.context,xace_session_id=request.xace_session_id)),
                                       timeout_seconds=30,turn_idle_timeout_seconds=60)
    report = {'schema':'xace.ag029_live_probe.v1','profile':adapter.profile_evidence,
              'real_account_certified':False,'account_calls_performed':True,'model_turns_performed':0}
    try:
        status = adapter.detect_sync()
        report['available'] = status.available
        report['auth_state'] = status.auth_state.value
        report['model_count'] = len(status.metadata.get('model_ids',[]))
        model = status.metadata.get('default_model')
        if isinstance(model,dict): model = model.get('id') or model.get('model')
        if not model: model = status.metadata.get('model_ids',[None])[0]
        report['selected_model'] = model
        report['provider_managed_accounting'] = status.billing.cost_state.value
        report['rate_limit_state_available'] = bool(status.billing.rate_limits)
        report['provider_managed_billing'] = status.billing.cost_state.value == 'provider_managed' and status.billing.estimated_cost_cents is None
        if not status.available: raise RuntimeError('Signed-in model availability check failed')
        handle = await adapter.start_session(AgentStartRequest(user_prompt='Read the synthetic XACE diagnostics.',xace_session_id='ag029-live-1',project_id='ag029-disposable',
            base_cgs_hash=cgs_hash,context_capsule_path=str(capsule_file),allowed_tools=bridge.tool_names,
            metadata={'codex_model':model}))
        store.upsert_session(handle)
        report['native_mcp'] = handle.metadata['native_mcp'].get('status_verified',False)
        report['model_turns_performed'] = 1
        events = [event async for event in adapter.run_turn(AgentTurnRequest(handle=handle,
            user_prompt='Use provider-native tool_search discovery to find xace get_diagnostics if needed. Call that XACE tool once and report the returned diagnostic code. Do not access files or run shell commands.',
            base_cgs_hash=cgs_hash,allowed_tools=bridge.tool_names))]
        report['events'] = [event.event_type.value for event in events]
        report['diagnostic_marker_observed'] = 'AG029_NATIVE_MCP_OK' in json.dumps([event.to_dict() for event in events])
        report['diagnostics_turn_completed'] = bool(events and events[-1].event_type.value == 'turn_completed')
        report['streamed_deltas_observed'] = any(e.data.get('codex_method') == 'item/agentMessage/delta' for e in events)
        report['provider_methods'] = sorted({str(e.data.get('codex_method','')) for e in events})
        report['errors'] = [event.to_dict() for event in events if event.event_type.value=='error']
        resumed = await adapter.resume_session(handle)
        report['resume_same_thread'] = resumed.provider_session_id == handle.provider_session_id
        child = await adapter.fork_session(resumed,xace_session_id='ag029-live-branch',branch_name='certification')
        report['fork_new_thread'] = child.provider_session_id != handle.provider_session_id
        report['fork_parent_recorded'] = child.metadata.get('parent_provider_session_id') == handle.provider_session_id
        cancelled = []
        report['model_turns_performed'] += 1
        cancel_stream = adapter.run_turn(AgentTurnRequest(handle=resumed,
                user_prompt='Explain deterministic game simulation in detail. Do not call tools.',
                base_cgs_hash=cgs_hash,allowed_tools=bridge.tool_names))
        async for event in cancel_stream:
            cancelled.append(event)
            if event.event_type.value == 'turn_started':
                await adapter.cancel_turn(resumed)
                report['cancel_cleanup'] = resumed.provider_session_id not in adapter._clients
                break
        await cancel_stream.aclose()
        report['cancellation_events'] = [event.event_type.value for event in cancelled]
        report['cancel_requested_after_start'] = bool(cancelled and cancelled[-1].event_type.value == 'turn_started')
        recovered = await adapter.resume_session(resumed)
        report['resume_after_cancel'] = recovered.provider_session_id == resumed.provider_session_id
        report['model_turns_performed'] += 1
        recovery = [event async for event in adapter.run_turn(AgentTurnRequest(handle=recovered,
            user_prompt='Reply exactly AG029_RECOVERY_OK. Do not use tools.',base_cgs_hash=cgs_hash,
            allowed_tools=bridge.tool_names))]
        report['recovery_marker_observed'] = 'AG029_RECOVERY_OK' in json.dumps([e.to_dict() for e in recovery])
        report['recovery_terminal'] = recovery[-1].event_type.value if recovery else None
        compact = await adapter.compact_session(recovered)
        report['compaction_accepted'] = compact.accepted
        deadline = time.monotonic() + 60
        report['compaction_completed'] = False
        while time.monotonic() < deadline:
            note = await asyncio.to_thread(adapter._read_thread_notification,recovered.provider_session_id,.25)
            if not note: continue
            params = note.get('params',{})
            if note.get('method') == 'turn/completed':
                report['compaction_completed'] = (params.get('threadId') == recovered.provider_session_id
                                                  and params.get('turn',{}).get('status') == 'completed')
                break
        adapter._close_thread_client(recovered.provider_session_id)
        report['model_turns_performed'] += 1
        proposal_events = [event async for event in adapter.run_turn(AgentTurnRequest(handle=recovered,
            user_prompt='This is an authorized disposable preview-only certification. Discover xace submit_proposal with tool_search, then call it with {"proposal": the following object}. Do not approve or apply it. '+json.dumps(_proposal()),
            base_cgs_hash=cgs_hash,allowed_tools=bridge.tool_names))]
        report['proposal_preview_created'] = bool(pending.pending_prompt_preview and pending.pending_txn)
        report['proposal_source_unchanged'] = cgs == original_cgs
        report['proposal_persisted'] = store.get_proposal('proposal-codex-energy') is not None
        if pending.pending_prompt_preview:
            preview = pending.pending_prompt_preview
            missing = SessionManager.validate_prompt_preview_approval(approval_owner,'ag029-live-1',{})
            report['approval_missing_denied'] = not missing['accepted']
            wrong = SessionManager.validate_prompt_preview_approval(approval_owner,'ag029-live-1',
                {'approval':{'preview_id':preview['preview_id'],'approval_token':'wrong'}})
            report['approval_wrong_denied'] = not wrong['accepted']
            accepted = SessionManager.validate_prompt_preview_approval(approval_owner,'ag029-live-1',
                {'approval':{'preview_id':preview['preview_id'],'approval_token':preview['approval_token'],
                             'approval_source':'ag029_operator_certification','approved_by':'authorized_operator'}})
            report['approval_gate_accepted'] = accepted['accepted'] and not accepted['approval']['test_mode_override']
            # Exercise rejection/clear without committing the synthetic preview.
            SessionManager.clear_pending(approval_owner,'ag029-live-1')
            report['rejection_clears_preview'] = pending.pending_txn is None and pending.pending_prompt_preview is None
        # Simulate failure of this owned transport only, never the user's IDE.
        outage_handle = await adapter.resume_session(recovered)
        adapter._clients[outage_handle.provider_session_id]._proc.kill()
        adapter._clients[outage_handle.provider_session_id]._proc.wait(timeout=5)
        report['owned_transport_outage'] = adapter._clients[outage_handle.provider_session_id].closed
        restored = await adapter.resume_session(outage_handle)
        report['resume_after_outage'] = restored.provider_session_id == recovered.provider_session_id
        report['proposal_errors'] = [e.event_type.value for e in proposal_events if e.event_type.value=='error']
        print(json.dumps(report,sort_keys=True))
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
        report['failure_code'] = getattr(exc,'code','probe_failed')
        print(json.dumps(report,sort_keys=True))
        raise
    finally:
        adapter.close()


if __name__ == '__main__':
    asyncio.run(main())
