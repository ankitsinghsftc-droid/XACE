/**
 * Overlay console for live engine adapters.
 *
 * This console is intentionally prompt-driven. It never writes the CGS or
 * runtime state directly; accepted edits are sent through BuilderClient and
 * eventually resolved by the server/PIL/GDE path.
 */

import type { BuilderClient, RuntimeStatus } from '../api/builder_client';
import { makeEngineEdit, makePilProcess, makeRuntimeControl } from '../api/message_types';
import type { CGSStore } from '../state/cgs_store';
import type { ConsoleSM, ConsoleState } from '../state/console_state_machine';
import type { UIStore } from '../state/ui_store';

type OverlayState = 'Idle' | 'PromptSubmitted' | 'PreviewReceived' | 'UserDecision';

interface IngameConsoleDeps {
  readonly client: BuilderClient;
  readonly consoleSM: ConsoleSM;
  readonly cgsStore: CGSStore;
  readonly uiStore: UIStore;
}

const STYLES = `
.xb-ingame-console {
  position: fixed;
  left: 50%;
  bottom: 58px;
  transform: translateX(-50%);
  width: min(780px, calc(100vw - 28px));
  background: rgba(5, 8, 16, .92);
  border: 1px solid rgba(0, 212, 255, .22);
  border-radius: 8px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, .45);
  color: var(--txt);
  font-family: var(--font-sans);
  z-index: 640;
  overflow: hidden;
}
.xb-ingame-console.hidden { display: none; }
.xb-ic-head {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; border-bottom: 1px solid rgba(255,255,255,.08);
  font-size: 10px; color: var(--txt2);
}
.xb-ic-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--amb); }
.xb-ic-dot.live { background: var(--grn); }
.xb-ic-state { margin-left: auto; font-family: var(--font-mono); color: var(--cyan); }
.xb-ic-body { display: grid; grid-template-columns: 1fr auto; gap: 8px; padding: 9px; }
.xb-ic-input {
  min-width: 0; border: 1px solid rgba(255,255,255,.1); border-radius: 6px;
  background: rgba(255,255,255,.04); color: var(--txt); padding: 8px 10px;
  font-size: 12px; outline: none;
}
.xb-ic-input:focus { border-color: rgba(0,212,255,.55); }
.xb-ic-actions { display: flex; gap: 6px; }
.xb-ic-actions button {
  border: 1px solid rgba(255,255,255,.12); background: rgba(255,255,255,.06);
  color: var(--txt); border-radius: 6px; padding: 0 10px; font-size: 11px;
  cursor: pointer; min-width: 54px;
}
.xb-ic-actions button.primary { border-color: rgba(0,212,255,.45); color: var(--cyan); }
.xb-ic-foot {
  display: flex; gap: 8px; align-items: center; padding: 0 10px 9px;
  color: var(--txt3); font-size: 10px; min-height: 18px;
}
`;

export class IngameConsole {
  private readonly deps: IngameConsoleDeps;
  private root: HTMLElement | null = null;
  private input: HTMLInputElement | null = null;
  private statusEl: HTMLElement | null = null;
  private dotEl: HTMLElement | null = null;
  private stateEl: HTMLElement | null = null;
  private overlayState: OverlayState = 'Idle';
  private visible = false;
  private lastPrompt = '';
  private readonly unsubs: Array<() => void> = [];

  constructor(deps: IngameConsoleDeps) {
    this.deps = deps;
    injectStyles();
  }

  mount(parent: HTMLElement = document.body): void {
    if (this.root) {
      return;
    }
    this.root = document.createElement('section');
    this.root.className = 'xb-ingame-console hidden';
    this.root.innerHTML = `
      <div class="xb-ic-head">
        <span class="xb-ic-dot"></span>
        <span class="xb-ic-title">In-game console</span>
        <span class="xb-ic-engine">engine offline</span>
        <span class="xb-ic-state">Idle</span>
      </div>
      <div class="xb-ic-body">
        <input class="xb-ic-input" autocomplete="off" spellcheck="false" />
        <div class="xb-ic-actions">
          <button data-action="step">Step</button>
          <button data-action="pause">Pause</button>
          <button class="primary" data-action="submit">Send</button>
        </div>
      </div>
      <div class="xb-ic-foot"></div>
    `;
    parent.appendChild(this.root);
    this.input = this.root.querySelector<HTMLInputElement>('.xb-ic-input');
    this.statusEl = this.root.querySelector<HTMLElement>('.xb-ic-engine');
    this.dotEl = this.root.querySelector<HTMLElement>('.xb-ic-dot');
    this.stateEl = this.root.querySelector<HTMLElement>('.xb-ic-state');

    this.input?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        this.submitPrompt();
      } else if (event.key === 'Escape') {
        this.hide();
      }
    });
    this.root.querySelector<HTMLButtonElement>('[data-action="submit"]')?.addEventListener('click', () => this.submitPrompt());
    this.root.querySelector<HTMLButtonElement>('[data-action="step"]')?.addEventListener('click', () => {
      this.deps.client.send(makeRuntimeControl('step', this.deps.client.sessionId));
    });
    this.root.querySelector<HTMLButtonElement>('[data-action="pause"]')?.addEventListener('click', () => {
      this.deps.client.send(makeRuntimeControl('pause', this.deps.client.sessionId));
    });

    this.unsubs.push(this.deps.client.onRuntimeStatus((status) => this.renderRuntimeStatus(status)));
    this.unsubs.push(this.deps.consoleSM.subscribe((state) => this.renderConsoleState(state)));
    window.addEventListener('keydown', this.onGlobalKey);
  }

  unmount(): void {
    this.unsubs.splice(0).forEach((unsub) => unsub());
    window.removeEventListener('keydown', this.onGlobalKey);
    this.root?.remove();
    this.root = null;
  }

  show(prefill = ''): void {
    this.visible = true;
    this.root?.classList.remove('hidden');
    if (prefill && this.input) {
      this.input.value = prefill;
    }
    requestAnimationFrame(() => this.input?.focus());
  }

  hide(): void {
    this.visible = false;
    this.root?.classList.add('hidden');
  }

  toggle(): void {
    if (this.visible) {
      this.hide();
    } else {
      this.show();
    }
  }

  selectEntity(entityId: string): void {
    this.deps.client.send(makeEngineEdit('select_entity', this.deps.client.sessionId, {
      entity_id: entityId,
    }));
  }

  private submitPrompt(): void {
    const prompt = this.input?.value.trim() ?? '';
    if (!prompt) {
      return;
    }
    this.lastPrompt = prompt;
    this.overlayState = 'PromptSubmitted';
    this.renderOverlayState();
    this.deps.consoleSM.submitPrompt(prompt);
    this.deps.client.send(makePilProcess(
      prompt,
      this.deps.cgsStore.hash,
      this.deps.uiStore.mode,
      this.deps.client.sessionId,
    ));
    if (this.input) {
      this.input.value = '';
    }
  }

  private renderRuntimeStatus(status: RuntimeStatus): void {
    if (this.statusEl) {
      const mode = status.paused ? 'paused' : 'live';
      const feedbackIssues = status.lastEngineFeedbackInvalid + status.lastEngineFeedbackErrors;
      this.statusEl.textContent = status.connected
        ? `${status.adapterType || 'engine'} ${status.engineVersion || ''} ${mode} f:${status.lastEngineFeedbackProcessed}/${feedbackIssues}`.trim()
        : 'engine offline';
    }
    this.dotEl?.classList.toggle('live', status.connected);
  }

  private renderConsoleState(state: ConsoleState): void {
    if (state.name === 'PreviewPending') {
      this.overlayState = 'PreviewReceived';
    } else if (state.name === 'Processing' || state.name === 'ApplyingMutation') {
      this.overlayState = 'PromptSubmitted';
    } else if (state.name === 'Idle' && this.overlayState !== 'Idle') {
      this.overlayState = 'UserDecision';
    }
    this.renderOverlayState();
  }

  private renderOverlayState(): void {
    if (this.stateEl) {
      this.stateEl.textContent = this.overlayState;
    }
    const foot = this.root?.querySelector<HTMLElement>('.xb-ic-foot');
    if (foot) {
      foot.textContent = this.overlayState === 'Idle'
        ? ''
        : `${this.overlayState}: ${this.lastPrompt}`;
    }
  }

  private readonly onGlobalKey = (event: KeyboardEvent): void => {
    if ((event.ctrlKey || event.metaKey) && event.key === '`') {
      event.preventDefault();
      this.toggle();
    }
  };
}

function injectStyles(): void {
  if (document.getElementById('xb-ingame-console-styles')) {
    return;
  }
  const style = document.createElement('style');
  style.id = 'xb-ingame-console-styles';
  style.textContent = STYLES;
  document.head.appendChild(style);
}
