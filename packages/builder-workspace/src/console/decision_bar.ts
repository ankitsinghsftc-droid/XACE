/**
 * Review decision bar for previewed PIL mutations.
 *
 * This component owns the small but important apply/revise/discard control
 * strip. It updates local console state and sends the matching server command
 * through the typed builder client.
 */

import type { BuilderClient } from '../api/builder_client';
import { makePilApply, makePilDiscard } from '../api/message_types';
import type { ConsoleSM, ConsoleState } from '../state/console_state_machine';

const STYLES = `
.xb-decision { border-top: 1px solid var(--bd); padding: 7px 12px; display: flex; align-items: center; gap: 7px; background: var(--bgp); flex-shrink: 0; min-width: 0; }
.xb-decision-summary { min-width: 0; flex: 1; font-size: 9.5px; color: var(--txt3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-decision-btn { font-size: 10.5px; cursor: pointer; padding: 4px 8px; border-radius: 4px; background: transparent; border: 1px solid transparent; color: var(--txt2); font-family: inherit; transition: all 120ms; white-space: nowrap; }
.xb-decision-btn:hover { color: var(--txt); background: rgba(255,255,255,.04); border-color: var(--bd); }
.xb-decision-btn.discard:hover { color: var(--red); background: rgba(239,68,68,.07); border-color: rgba(239,68,68,.22); }
.xb-decision-btn.apply { background: linear-gradient(135deg, rgba(0,212,255,.20), rgba(168,85,247,.18)); border: 1px solid rgba(0,212,255,.36); border-radius: var(--r); color: var(--cyan); font-weight: 700; padding: 5px 18px; }
.xb-decision-btn.apply:hover { box-shadow: 0 0 20px rgba(0,212,255,.22); transform: translateY(-1px); }
.xb-decision-btn:disabled { opacity: .45; cursor: default; transform: none; box-shadow: none; }
`;

interface DecisionBarDeps {
  readonly consoleSM: ConsoleSM;
  readonly client: BuilderClient;
}

export class DecisionBar {
  private readonly deps: DecisionBarDeps;
  private readonly unsubs: Array<() => void> = [];
  private root: HTMLElement | null = null;
  private busy = false;

  constructor(deps: DecisionBarDeps) {
    this.deps = deps;
    injectStyles();
  }

  mount(container: HTMLElement): void {
    this.root = document.createElement('div');
    this.root.className = 'xb-decision';
    container.appendChild(this.root);
    this.unsubs.push(this.deps.consoleSM.subscribe((state) => this.render(state)));
    this.render(this.deps.consoleSM.state);
  }

  unmount(): void {
    this.unsubs.splice(0).forEach((unsub) => unsub());
    this.root?.remove();
    this.root = null;
  }

  private render(state: ConsoleState): void {
    if (!this.root) {
      return;
    }
    if (state.name !== 'PreviewPending') {
      this.root.style.display = 'none';
      this.root.innerHTML = '';
      return;
    }

    this.root.style.display = 'flex';
    const summary = state.result.transaction.mutation_summary || 'Pending mutation';
    this.root.innerHTML = `
      <button class="xb-decision-btn discard" data-action="discard" ${this.busy ? 'disabled' : ''}>Discard</button>
      <button class="xb-decision-btn" data-action="revise" ${this.busy ? 'disabled' : ''}>Revise Prompt</button>
      <div class="xb-decision-summary" title="${escapeHtml(summary)}">${escapeHtml(summary)}</div>
      <button class="xb-decision-btn apply" data-action="apply" ${this.busy ? 'disabled' : ''}>Apply to Project</button>
    `;
    this.root.querySelector<HTMLButtonElement>('[data-action="discard"]')?.addEventListener('click', () => this.discard());
    this.root.querySelector<HTMLButtonElement>('[data-action="revise"]')?.addEventListener('click', () => this.revise());
    this.root.querySelector<HTMLButtonElement>('[data-action="apply"]')?.addEventListener('click', () => this.apply());
  }

  private apply(): void {
    if (this.deps.consoleSM.state.name !== 'PreviewPending') {
      return;
    }
    this.busy = true;
    const preview = this.deps.consoleSM.state.result.preview;
    const approval = preview
      ? {
          schema: 'xace.prompt_preview_approval.v1' as const,
          preview_id: preview.preview_id,
          approval_token: preview.approval_token,
          approval_source: 'builder_decision_bar',
          approved_by: this.deps.client.sessionId,
        }
      : undefined;
    this.deps.consoleSM.applyMutation();
    this.deps.client.send(makePilApply(this.deps.client.sessionId, approval));
    this.busy = false;
    this.render(this.deps.consoleSM.state);
  }

  private discard(): void {
    if (this.deps.consoleSM.state.name !== 'PreviewPending') {
      return;
    }
    this.busy = true;
    this.deps.consoleSM.discardMutation();
    this.deps.client.send(makePilDiscard(this.deps.client.sessionId));
    this.busy = false;
    this.render(this.deps.consoleSM.state);
  }

  private revise(): void {
    if (this.deps.consoleSM.state.name !== 'PreviewPending') {
      return;
    }
    this.deps.consoleSM.reviseMutation();
    this.render(this.deps.consoleSM.state);
  }
}

function injectStyles(): void {
  if (document.getElementById('xb-decision-styles')) return;
  const style = document.createElement('style');
  style.id = 'xb-decision-styles';
  style.textContent = STYLES;
  document.head.appendChild(style);
}

function escapeHtml(value: string): string {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
}
