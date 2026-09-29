/**
 * Compact functional Agent Mode panel.
 *
 * This intentionally stays a narrow operational surface: provider state,
 * current session/turn, streamed tool audit, and the distinct XACE preview
 * approval. XACE 11 can relocate or redesign it without changing the agent
 * transport contract underneath.
 */

import { AgentSetupPanel } from './agent_setup_panel';
import type { BuilderClient } from '../api/builder_client';
import { makeAgentCancel, makeAgentStatusRequest, makePilApply } from '../api/message_types';
import type { ConsoleSM } from '../state/console_state_machine';
import { agentEventStore } from '../state/agent_event_store';
import { agentModeStore, type AgentModeUiStatus } from '../state/agent_mode_store';
import { billingCostLabel, billingRateLimitLabel, billingUsageLabel } from '../types/billing';

const STYLES = `
.xb-agent-panel { height:100%; overflow:auto; padding:10px; color:var(--txt2); font-size:10px; }
.xb-agent-card { border:1px solid var(--bd); border-radius:var(--rs); background:rgba(255,255,255,.025); padding:9px; margin-bottom:8px; }
.xb-agent-title { color:var(--txt); font-size:11px; font-weight:700; margin-bottom:6px; }
.xb-agent-row { display:grid; grid-template-columns:76px minmax(0,1fr); gap:7px; line-height:1.45; margin:2px 0; }
.xb-agent-key { color:var(--txt3); font-size:8px; letter-spacing:.07em; text-transform:uppercase; }
.xb-agent-value { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--txt2); font-family:var(--font-mono); }
.xb-agent-value.ok { color:var(--grn); }
.xb-agent-value.warn { color:var(--amb); }
.xb-agent-value.err { color:var(--red); }
.xb-agent-note { color:var(--txt3); line-height:1.45; margin-top:7px; }
.xb-agent-actions { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
.xb-agent-action { border:1px solid var(--bd); border-radius:4px; padding:4px 7px; background:rgba(255,255,255,.04); color:var(--txt2); font:10px var(--font-ui); cursor:pointer; }
.xb-agent-action:hover { border-color:var(--bdh); color:var(--txt); }
.xb-agent-action.primary { border-color:rgba(0,212,255,.42); color:var(--cyan); background:var(--cynd); }
.xb-agent-action.danger { border-color:rgba(239,68,68,.35); color:var(--red); }
.xb-agent-action:disabled { cursor:default; opacity:.52; }
.xb-agent-audit { display:grid; gap:4px; max-height:180px; overflow:auto; }
.xb-agent-event { border-left:2px solid var(--bdh); padding:4px 6px; background:rgba(0,0,0,.12); }
.xb-agent-event.tool_call { border-left-color:var(--vlt); }
.xb-agent-event.proposal { border-left-color:var(--amb); }
.xb-agent-event.error { border-left-color:var(--red); }
.xb-agent-event-top { display:flex; gap:6px; min-width:0; align-items:center; }
.xb-agent-event-kind { color:var(--txt3); text-transform:uppercase; font-size:8px; font-weight:700; letter-spacing:.06em; }
.xb-agent-event-message { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--txt2); }
.xb-agent-event-detail { color:var(--txt3); margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
`;

interface AgentModePanelDeps {
  readonly client: BuilderClient;
  readonly consoleSM: ConsoleSM;
}

export class AgentModePanel {
  private readonly _deps: AgentModePanelDeps;
  private _el!: HTMLElement;
  private _content!: HTMLElement;
  private readonly _setup = new AgentSetupPanel();
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: AgentModePanelDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-agent-panel';
    container.appendChild(this._el);
    this._setup.mount(this._el);
    this._content = document.createElement("div");
    this._el.appendChild(this._content);
    this._unsubs.push(agentModeStore.subscribe(() => this._render()));
    this._unsubs.push(agentEventStore.subscribe(() => this._render()));
    this._unsubs.push(this._deps.consoleSM.subscribe(() => this._render()));
    this._unsubs.push(this._deps.client.onAgentStatus(() => this._render()));
    this._unsubs.push(this._deps.client.onAgentEvent(() => this._render()));
    this._requestStatus();
    this._render();
  }

  unmount(): void {
    this._unsubs.forEach((unsubscribe) => unsubscribe());
    this._setup.unmount();
    this._el?.remove();
  }

  private _render(): void {
    const agent = agentModeStore.state.agent;
    const status = agentEventStore.state.status;
    this._content.innerHTML = '';
    this._content.appendChild(this._buildProviderCard(agent));
    this._content.appendChild(this._buildSessionCard(agent, status?.turn_id || '', status?.message || 'No active agent turn.'));
    this._content.appendChild(this._buildAuditCard());
    this._content.appendChild(this._buildApprovalCard());
  }

  private _buildProviderCard(agent: AgentModeUiStatus | null): HTMLElement {
    const card = this._card('Codex Agent Mode');
    const adapter = agent?.primary_adapter_status ?? null;
    this._row(card, 'Provider', adapter?.display_name || 'Codex App Server', adapter?.available ? 'ok' : 'warn');
    const launch = agent?.launch_status;
    const releaseLabel = launch?.runtime_ready
      ? 'Production ready'
      : launch?.release_certified
        ? 'Certified; setup required'
        : 'Unavailable';
    this._row(card, 'Release', releaseLabel, launch?.runtime_ready ? 'ok' : launch?.release_certified ? 'warn' : 'err');
    this._row(card, 'Auth', adapter?.auth_state.replace(/_/g, ' ') || 'unknown', adapter?.available ? 'ok' : 'warn');
    this._row(card, 'Account', adapter?.account_label || 'Provider-managed account', adapter?.available ? 'ok' : '');
    this._row(card, 'Billing', billingCostLabel(agent?.billing ?? agentModeStore.state.billing), '');
    this._row(card, 'Usage', billingUsageLabel(agent?.billing ?? agentModeStore.state.billing), '');
    this._row(card, 'Limits', billingRateLimitLabel(agent?.billing ?? agentModeStore.state.billing), '');
    this._row(card, 'Tools', agent?.tool_transport_preference === 'mcp' ? 'XACE MCP preferred' : 'XACE tool transport', 'ok');
    const note = document.createElement('div');
    note.className = 'xb-agent-note';
    const billing = agent?.billing ?? agentModeStore.state.billing;
    note.textContent = [
      agent?.message || 'Select Agent Mode to use the Codex App Server path.',
      billing.detail,
    ].filter(Boolean).join(' ');
    card.appendChild(note);
    const actions = document.createElement('div');
    actions.className = 'xb-agent-actions';
    const focus = this._button('Focus agent prompt', () => {
      window.dispatchEvent(new CustomEvent('xace:focus-prompt'));
    }, 'primary');
    actions.appendChild(focus);
    const refresh = this._button('Refresh status', () => this._requestStatus());
    actions.appendChild(refresh);
    card.appendChild(actions);
    return card;
  }

  private _buildSessionCard(agent: AgentModeUiStatus | null, turnId: string, message: string): HTMLElement {
    const card = this._card('Current agent session');
    const status = agentEventStore.state.status;
    this._row(card, 'XACE session', this._deps.client.sessionId, '');
    this._row(card, 'Provider', agent?.primary_adapter || status?.provider_id || 'codex_app_server', '');
    this._row(card, 'Turn', turnId || 'not started', status?.running ? 'ok' : '');
    this._row(card, 'State', status?.ui_state.label || 'Agent idle', status?.state === 'error' ? 'err' : status?.running ? 'ok' : '');
    const note = document.createElement('div');
    note.className = 'xb-agent-note';
    note.textContent = message;
    card.appendChild(note);
    if (status?.cancellable) {
      const actions = document.createElement('div');
      actions.className = 'xb-agent-actions';
      actions.appendChild(this._button('Cancel agent turn', () => {
        this._deps.client.send(makeAgentCancel(this._deps.client.sessionId, status.provider_id));
      }, 'danger'));
      card.appendChild(actions);
    }
    return card;
  }

  private _buildAuditCard(): HTMLElement {
    const card = this._card('Agent tool and proposal audit');
    const audit = document.createElement('div');
    audit.className = 'xb-agent-audit';
    const events = agentEventStore.state.events
      .filter((event) => event.session_id === this._deps.client.sessionId)
      .slice(-12)
      .reverse();
    if (!events.length) {
      const empty = document.createElement('div');
      empty.className = 'xb-agent-note';
      empty.textContent = 'No streamed agent events for this Builder session yet.';
      audit.appendChild(empty);
    }
    for (const event of events) {
      const row = document.createElement('div');
      row.className = `xb-agent-event ${event.event_type}`;
      const top = document.createElement('div');
      top.className = 'xb-agent-event-top';
      const kind = document.createElement('span');
      kind.className = 'xb-agent-event-kind';
      kind.textContent = event.ui_state.label || event.event_type;
      const message = document.createElement('span');
      message.className = 'xb-agent-event-message';
      message.textContent = event.message;
      message.title = event.message;
      top.append(kind, message);
      row.appendChild(top);
      const detail = eventDetail(event.data);
      if (detail) {
        const detailEl = document.createElement('div');
        detailEl.className = 'xb-agent-event-detail';
        detailEl.textContent = detail;
        detailEl.title = detail;
        row.appendChild(detailEl);
      }
      audit.appendChild(row);
    }
    card.appendChild(audit);
    const note = document.createElement('div');
    note.className = 'xb-agent-note';
    note.textContent = 'A completed provider tool call is audit evidence, not permission to change the project.';
    card.appendChild(note);
    return card;
  }

  private _buildApprovalCard(): HTMLElement {
    const card = this._card('XACE mutation approval');
    const pending = this._deps.consoleSM.state;
    const note = document.createElement('div');
    note.className = 'xb-agent-note';
    note.textContent = pending.name === 'PreviewPending'
      ? 'XACE has a validated preview. Only the controls below can approve or discard it; Codex cannot commit it directly.'
      : 'Agent proposals become XACE previews first. Approval remains unavailable until XACE has validated a preview.';
    card.appendChild(note);
    if (pending.name !== 'PreviewPending') return card;

    const actions = document.createElement('div');
    actions.className = 'xb-agent-actions';
    actions.appendChild(this._button('Discard preview', () => {
      this._deps.consoleSM.discardMutation();
      this._deps.client.send({ type: 'pil_discard', session_id: this._deps.client.sessionId });
    }, 'danger'));
    actions.appendChild(this._button('Approve preview', () => {
      const current = this._deps.consoleSM.state;
      const approval = current.name === 'PreviewPending' && current.result.preview
        ? {
            schema: 'xace.prompt_preview_approval.v1' as const,
            preview_id: current.result.preview.preview_id,
            approval_token: current.result.preview.approval_token,
            approval_source: 'builder_agent_panel',
            approved_by: this._deps.client.sessionId,
          }
        : undefined;
      this._deps.consoleSM.applyMutation();
      this._deps.client.send(makePilApply(this._deps.client.sessionId, approval));
    }, 'primary'));
    card.appendChild(actions);
    return card;
  }

  private _card(title: string): HTMLElement {
    const card = document.createElement('section');
    card.className = 'xb-agent-card';
    const heading = document.createElement('div');
    heading.className = 'xb-agent-title';
    heading.textContent = title;
    card.appendChild(heading);
    return card;
  }

  private _row(parent: HTMLElement, key: string, value: string, kind: '' | 'ok' | 'warn' | 'err'): void {
    const row = document.createElement('div');
    row.className = 'xb-agent-row';
    const label = document.createElement('span');
    label.className = 'xb-agent-key';
    label.textContent = key;
    const text = document.createElement('span');
    text.className = `xb-agent-value ${kind}`;
    text.textContent = value || '-';
    text.title = value || '-';
    row.append(label, text);
    parent.appendChild(row);
  }

  private _button(label: string, onClick: () => void, kind = ''): HTMLButtonElement {
    const button = document.createElement('button');
    button.className = `xb-agent-action ${kind}`;
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
  }

  private _requestStatus(): void {
    const agent = agentModeStore.state.agent;
    const providerId = agent?.primary_adapter || 'codex_app_server';
    this._deps.client.send(makeAgentStatusRequest(this._deps.client.sessionId, providerId));
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-agent-panel-styles')) return;
    const style = document.createElement('style');
    style.id = 'xb-agent-panel-styles';
    style.textContent = STYLES;
    document.head.appendChild(style);
  }
}

function eventDetail(data: Record<string, unknown>): string {
  const params = objectValue(data.params);
  const tool = String(params?.tool || objectValue(params?.item)?.name || '');
  const proposal = objectValue(data.proposal) || objectValue(params?.proposal);
  const risk = String(proposal?.risk_level || proposal?.riskLevel || '');
  if (tool) return `${tool ? `xace.${tool}` : 'tool'}${risk ? ` · risk ${risk}` : ''}`;
  if (risk) return `Proposal risk: ${risk}`;
  const response = objectValue(params?.xace_tool_response);
  const proposalIngress = proposalIngressFromResponse(response);
  if (proposalIngress) return `XACE preview ${proposalIngress}`;
  return '';
}

function proposalIngressFromResponse(response: Record<string, unknown> | null): string {
  const items = Array.isArray(response?.contentItems) ? response?.contentItems : [];
  const first = objectValue(items[0]);
  const text = typeof first?.text === 'string' ? first.text : '';
  if (!text) return '';
  try {
    const payload = JSON.parse(text) as { data?: { proposal_ingress?: { status?: unknown } } };
    return String(payload.data?.proposal_ingress?.status || 'submitted');
  } catch {
    return '';
  }
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : null;
}
