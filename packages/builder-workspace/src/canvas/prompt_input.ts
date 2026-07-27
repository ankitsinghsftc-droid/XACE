/**
 * prompt_input.ts — Natural Language Prompt Input Bar
 *
 * The primary interaction point. Designer types here, PIL processes it.
 *
 * Features:
 *   - Multiline textarea that grows up to 4 lines
 *   - 4-mode pills (reflect and control uiStore.mode)
 *   - Submit button + Enter to submit (Shift+Enter = newline)
 *   - Streaming indicator (spinner during Processing state)
 *   - Tool buttons: Explain, Quick, Context: [actor]
 *   - Running cost pill (live)
 *   - Pre-fill from xace:prefill-prompt events (graph context menu, etc.)
 *   - Disabled state during Processing
 *
 * On submit: fires consoleSM.submitPrompt() and sends pil_process over WS.
 */

import type { BuilderClient, PromptProviderStatus } from '../api/builder_client';
import type { ConsoleSM, ConsoleState } from '../state/console_state_machine';
import type { CGSStore }       from '../state/cgs_store';
import type { UIStore }        from '../state/ui_store';
import { makePilProcess }      from '../api/message_types';
import { ModelSelector }       from './model_selector';

const STYLES = `
.xb-prompt-area {
  border-top:      1px solid var(--bd);
  padding:         8px 10px;
  background:      rgba(8,12,24,.95);
  flex-shrink:     0;
  position:        relative;
  z-index:         10;
}
.xb-p-status {
  display:         flex;
  align-items:     center;
  gap:             5px;
  margin-bottom:   6px;
  min-width:       0;
  flex-wrap:       wrap;
}
.xb-p-status-chip {
  border:          1px solid var(--bd);
  border-radius:   999px;
  color:           var(--txt3);
  background:      rgba(255,255,255,.025);
  font-size:       8.5px;
  font-weight:     700;
  letter-spacing:  .06em;
  line-height:     1;
  padding:         3px 6px;
  text-transform:  uppercase;
}
.xb-p-status-chip.active {
  border-color:    rgba(0,212,255,.32);
  color:           var(--cyan);
  background:      var(--cynd);
}
.xb-p-status-chip.failed.active {
  border-color:    rgba(239,68,68,.32);
  color:           var(--red);
  background:      rgba(239,68,68,.08);
}
.xb-p-status-chip.applied.active {
  border-color:    rgba(16,185,129,.34);
  color:           var(--grn);
  background:      rgba(16,185,129,.08);
}
.xb-p-status-text {
  min-width:       120px;
  flex:            1;
  color:           var(--txt3);
  font-size:       9.5px;
  overflow:        hidden;
  text-overflow:   ellipsis;
  white-space:     nowrap;
}
.xb-p-provider-btn {
  border:          1px solid rgba(255,159,67,.34);
  background:      rgba(255,159,67,.08);
  color:           var(--amb);
  border-radius:   999px;
  cursor:          pointer;
  font-family:     inherit;
  font-size:       9px;
  font-weight:     700;
  padding:         3px 7px;
  white-space:     nowrap;
}
.xb-p-provider-btn:hover {
  border-color:    rgba(255,159,67,.62);
  color:           #ffd7a6;
}
.xb-prompt-box {
  background:      var(--bgc);
  border:          1px solid var(--bdh);
  border-radius:   var(--r);
  padding:         7px 9px;
  display:         flex;
  align-items:     flex-end;
  gap:             7px;
  transition:      border-color var(--tr), box-shadow var(--tr);
}
.xb-prompt-box:focus-within {
  border-color:    var(--cyan);
  box-shadow:      0 0 0 2px rgba(0,212,255,.08);
}
.xb-prompt-box.disabled {
  border-color:    var(--bd);
  opacity:         .6;
  pointer-events:  none;
}
.xb-prompt-box.provider-blocked {
  border-color:    rgba(255,159,67,.34);
}
.xb-p-ai-icon {
  color:           var(--cyan);
  font-size:       14px;
  flex-shrink:     0;
  padding-bottom:  1px;
  transition:      all var(--tr);
}
.xb-p-ai-icon.spinning {
  animation:       spin 600ms linear infinite;
  color:           var(--vlt);
}
.xb-p-textarea {
  flex:            1;
  font-size:       11.5px;
  color:           var(--txt);
  background:      transparent;
  border:          none;
  outline:         none;
  font-family:     inherit;
  line-height:     1.5;
  resize:          none;
  caret-color:     var(--cyan);
  min-height:      20px;
  max-height:      80px;
  overflow-y:      auto;
  padding:         1px 0;
}
.xb-p-textarea::placeholder { color: var(--txt3); }
.xb-p-send {
  background:      var(--cyan);
  color:           #000;
  width:           26px;
  height:          26px;
  border-radius:   var(--rs);
  display:         flex;
  align-items:     center;
  justify-content: center;
  font-size:       13px;
  cursor:          pointer;
  flex-shrink:     0;
  font-weight:     700;
  border:          none;
  transition:      all var(--tr);
  font-family:     inherit;
  line-height:     1;
}
.xb-p-send:hover {
  background:      #fff;
  box-shadow:      0 0 14px rgba(0,212,255,.4);
}
.xb-p-send:disabled {
  background:      var(--txt3);
  cursor:          not-allowed;
}
/* Tools row */
.xb-p-tools {
  display:         flex;
  align-items:     center;
  gap:             5px;
  margin-top:      5px;
  flex-wrap:       wrap;
}
.xb-p-tool-btn {
  font-size:       9.5px;
  color:           var(--txt2);
  padding:         2px 7px;
  border-radius:   3px;
  border:          1px solid var(--bd);
  background:      transparent;
  cursor:          pointer;
  display:         flex;
  align-items:     center;
  gap:             3px;
  transition:      all var(--tr-f);
  font-family:     inherit;
  white-space:     nowrap;
}
.xb-p-tool-btn:hover { border-color: var(--bdh); color: var(--txt); }
.xb-cost-pill {
  margin-left:     auto;
  display:         flex;
  align-items:     center;
  gap:             4px;
  font-size:       9.5px;
  color:           var(--txt2);
  font-family:     var(--font-mono);
}
.xb-cost-dot {
  width:           5px;
  height:          5px;
  border-radius:   50%;
  background:      var(--vlt);
  flex-shrink:     0;
}
/* Context button shows selected entity */
.xb-p-ctx-btn {
  background:      rgba(0,212,255,.07);
  border-color:    rgba(0,212,255,.2);
  color:           var(--cyan);
  max-width:       120px;
  overflow:        hidden;
  text-overflow:   ellipsis;
}
.xb-p-ctx-btn:hover { background: var(--cynd); border-color: var(--cyan); }
`;

interface PromptInputDeps {
  client:    BuilderClient;
  consoleSM: ConsoleSM;
  cgsStore:  CGSStore;
  uiStore:   UIStore;
}

export class PromptInput {
  private readonly _deps: PromptInputDeps;
  private _el!:       HTMLElement;
  private _textarea!: HTMLTextAreaElement;
  private _sendBtn!:  HTMLButtonElement;
  private _aiIcon!:   HTMLElement;
  private _costEl!:   HTMLElement;
  private _ctxBtn!:   HTMLButtonElement;
  private _statusEl!: HTMLElement;
  private _consoleState!: ConsoleState;
  private _providerNotice = '';
  private _providerStatus: PromptProviderStatus = {
    checked: false,
    ready: false,
    provider: '',
    model: '',
    message: 'Checking provider setup...',
    action: '',
  };
  private readonly _unsubs: Array<() => void> = [];
  private readonly _onPrefillBound = (event: Event) => this._onPrefill(event as CustomEvent);
  private readonly _onFocusPrompt = () => {
    this._textarea?.focus();
    this._textarea?.setSelectionRange(this._textarea.value.length, this._textarea.value.length);
  };

  constructor(deps: PromptInputDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = this._build();
    container.appendChild(this._el);
    this._wireReactive();

    // Listen for pre-fill events from graph context menus, inspector buttons, etc.
    window.addEventListener('xace:prefill-prompt', this._onPrefillBound);
    window.addEventListener('xace:focus-prompt', this._onFocusPrompt);
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    window.removeEventListener('xace:prefill-prompt', this._onPrefillBound);
    window.removeEventListener('xace:focus-prompt', this._onFocusPrompt);
    this._el?.remove();
  }

  private _build(): HTMLElement {
    const root = document.createElement('div');
    root.className = 'xb-prompt-area';

    this._statusEl = document.createElement('div');
    this._statusEl.className = 'xb-p-status';
    root.appendChild(this._statusEl);

    // ── Prompt box ────────────────────────────────────────────────────────
    const box = document.createElement('div');
    box.className = 'xb-prompt-box';

    this._aiIcon = document.createElement('span');
    this._aiIcon.className   = 'xb-p-ai-icon';
    this._aiIcon.textContent = '✦';
    box.appendChild(this._aiIcon);

    this._textarea = document.createElement('textarea');
    this._textarea.className   = 'xb-p-textarea';
    this._textarea.placeholder = 'Make the zombie faster and add a stamina system…';
    this._textarea.rows        = 1;
    this._textarea.setAttribute('spellcheck', 'false');

    // Auto-grow
    this._textarea.addEventListener('input', () => {
      this._textarea.style.height = 'auto';
      this._textarea.style.height = `${Math.min(this._textarea.scrollHeight, 80)}px`;
    });

    // Enter to submit (Shift+Enter = newline)
    this._textarea.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._submit();
      }
    });

    box.appendChild(this._textarea);

    this._sendBtn = document.createElement('button');
    this._sendBtn.className   = 'xb-p-send';
    this._sendBtn.textContent = '↑';
    this._sendBtn.title       = 'Submit (Enter)';
    this._sendBtn.addEventListener('click', () => this._submit());
    box.appendChild(this._sendBtn);

    root.appendChild(box);

    // ── Tools row ─────────────────────────────────────────────────────────
    const tools = document.createElement('div');
    tools.className = 'xb-p-tools';

    // Explain button
    const explainBtn = this._toolBtn('🔍 Explain', () => {
      const prompt = this._textarea.value.trim();
      if (!prompt) return;
      const wrapped = `Explain: ${prompt}`;
      this._textarea.value = wrapped;
      this._submit();
    });
    tools.appendChild(explainBtn);

    // Quick button (TIER_S hint)
    const quickBtn = this._toolBtn('⚡ Quick', () => {
      window.dispatchEvent(new CustomEvent('xace:set-quick-mode', {}));
    });
    tools.appendChild(quickBtn);

    // Context button — shows selected actor
    this._ctxBtn = this._toolBtn('📎 Context: —', () => {
      const sel = this._deps.uiStore.state.selectedEntity;
      if (!sel) {
        this._deps.uiStore.setCommandPaletteOpen(true);
        return;
      }
      // Inject selected entity name into prompt
      const t = this._textarea;
      t.value += ` [${sel.label}]`;
      t.focus();
    }) as HTMLButtonElement;
    this._ctxBtn.className = 'xb-p-tool-btn xb-p-ctx-btn';
    tools.appendChild(this._ctxBtn);

    // Cost pill
    this._costEl = document.createElement('div');
    this._costEl.className   = 'xb-cost-pill';
    this._costEl.innerHTML   = `<div class="xb-cost-dot"></div><span id="xb-cost-val">$0.00</span>`;
    tools.appendChild(this._costEl);

    // Model selector (rightmost tool)
    const modelSelector = new ModelSelector(this._deps.client);
    modelSelector.mount(tools);

    root.appendChild(tools);
    return root;
  }

  private _toolBtn(label: string, onClick: () => void): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.className   = 'xb-p-tool-btn';
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    return btn;
  }

  // ── Submit ────────────────────────────────────────────────────────────

  private _submit(): void {
    const prompt = this._textarea.value.trim();
    if (!prompt) return;

    const { consoleSM, client, cgsStore, uiStore } = this._deps;
    if (!['Idle', 'DiagnosticView', 'BlockedView', 'ErrorView'].includes(consoleSM.stateName)) return;
    if (!this._providerStatus.ready) {
      this._providerNotice = this._providerSetupMessage();
      this._renderStatus(consoleSM.state);
      window.dispatchEvent(new CustomEvent('xace:open-model-settings'));
      return;
    }

    // Fire state machine
    consoleSM.submitPrompt(prompt);

    // Send WebSocket message
    client.send(makePilProcess(
      prompt,
      cgsStore.hash,
      uiStore.mode,
      client.sessionId,
    ));

    // Clear textarea
    this._textarea.value       = '';
    this._textarea.style.height = 'auto';
  }

  // ── Reactive wiring ────────────────────────────────────────────────────

  private _wireReactive(): void {
    const { consoleSM, uiStore } = this._deps;

    this._consoleState = consoleSM.state;
    this._renderStatus(consoleSM.state);
    this._unsubs.push(
      consoleSM.subscribe(state => {
        this._consoleState = state;
        this._renderStatus(state);
        const processing = state.name === 'Processing' || state.name === 'ApplyingMutation';
        this._aiIcon.classList.toggle('spinning', processing);
        const box = this._el.querySelector<HTMLElement>('.xb-prompt-box');
        box?.classList.toggle('disabled', processing);
        box?.classList.toggle('provider-blocked', !this._providerStatus.ready && !processing);
        this._sendBtn.disabled = processing || !this._providerStatus.ready;
        this._textarea.disabled = processing;
        this._sendBtn.title = this._providerStatus.ready ? 'Submit (Enter)' : this._providerSetupMessage();
        if (state.name === 'Idle' && state.prefillPrompt) {
          this._prefill(state.prefillPrompt, true);
        }
      }),
    );

    // Update context button label
    this._unsubs.push(
      uiStore.select(s => s.selectedEntity?.label, label => {
        this._ctxBtn.textContent = `📎 Context: ${label ?? '—'}`;
      }),
    );

    this._unsubs.push(
      this._deps.client.onProviderStatus(status => {
        this._providerStatus = status;
        if (status.ready) {
          this._providerNotice = '';
        }
        const state = this._consoleState ?? consoleSM.state;
        this._renderStatus(state);
        const processing = state.name === 'Processing' || state.name === 'ApplyingMutation';
        const box = this._el.querySelector<HTMLElement>('.xb-prompt-box');
        box?.classList.toggle('provider-blocked', !status.ready && !processing);
        this._sendBtn.disabled = processing || !status.ready;
        this._sendBtn.title = status.ready ? 'Submit (Enter)' : this._providerSetupMessage();
      }),
    );
  }

  private _renderStatus(state: ConsoleState): void {
    const active = new Set<string>();
    let message = 'Ready. Type a change, then review it before it is saved.';
    const providerBlocked = !this._providerStatus.ready;

    if (state.name === 'Processing') {
      active.add('validating');
      message = 'Validating your request through the XACE pipeline.';
    } else if (state.name === 'ApplyingMutation') {
      active.add('validating');
      message = 'Applying and validating the reviewed change.';
    } else if (state.name === 'PreviewPending') {
      active.add('proposed');
      active.add('safe');
      message = 'Safe proposal ready. Apply saves it; Revise or Discard leaves the project unchanged.';
    } else if (state.name === 'ClarificationFlow') {
      active.add('proposed');
      message = 'XACE needs one answer before it can validate the change.';
    } else if (state.name === 'BlockedView') {
      active.add('failed');
      message = 'XACE blocked this change before saving anything.';
    } else if (state.name === 'ErrorView') {
      active.add('failed');
      message = 'XACE could not finish that request. You can retry or rephrase it.';
    } else if (state.name === 'Idle' && state.lastSummary) {
      active.add('applied');
      message = `Applied: ${state.lastSummary}`;
    }
    if (providerBlocked && state.name !== 'Processing' && state.name !== 'ApplyingMutation') {
      active.add('failed');
      message = this._providerNotice || this._providerSetupMessage();
    }

    this._statusEl.innerHTML = '';
    for (const id of ['proposed', 'validating', 'safe', 'applied', 'failed']) {
      const chip = document.createElement('span');
      chip.className = `xb-p-status-chip ${id}${active.has(id) ? ' active' : ''}`;
      chip.textContent = id;
      this._statusEl.appendChild(chip);
    }
    const text = document.createElement('span');
    text.className = 'xb-p-status-text';
    text.title = message;
    text.textContent = message;
    this._statusEl.appendChild(text);
    if (providerBlocked && state.name !== 'Processing' && state.name !== 'ApplyingMutation') {
      const button = document.createElement('button');
      button.className = 'xb-p-provider-btn';
      button.type = 'button';
      button.textContent = 'Provider Settings';
      button.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('xace:open-model-settings'));
      });
      this._statusEl.appendChild(button);
    }
  }

  private _providerSetupMessage(): string {
    const status = this._providerStatus;
    if (!status.checked) return 'Checking provider setup...';
    const stateMessages: Record<string, string> = {
      no_key: 'Add a provider API key, save it, then run Test before prompting.',
      invalid_key: 'The saved provider key was rejected. Replace it, save, then run Test.',
      stale_health_proof: 'Provider settings changed. Run Test again before prompting.',
      quota_failure: 'Provider quota or billing blocked the last Test. Add quota or choose another provider.',
      rate_limit: 'Provider rate limit blocked the last Test. Wait, lower traffic, or choose another provider.',
      provider_outage: 'Provider is unreachable or returned a service error. Try again or choose another provider.',
    };
    const uxState = status.ux_state?.state || '';
    if (uxState && stateMessages[uxState]) return stateMessages[uxState];
    if (status.ux_state?.message) return status.ux_state.message;
    if (status.message) return status.message;
    if (status.action === 'save_key_and_test') return 'Save a provider key, then run Test before prompting.';
    if (status.action === 'test_provider') return 'Choose provider and run Test before prompting.';
    return 'Choose provider and run Test before prompting.';
  }

  private _onPrefill(e: CustomEvent): void {
    const text  = e.detail?.text  as string | undefined;
    const label = e.detail?.nodeLabel as string | undefined;
    if (text) {
      this._prefill(text, true);
    } else if (label) {
      this._prefill(`Edit ${label}: `, true);
    }
  }

  private _prefill(text: string, focus: boolean): void {
    this._textarea.value = text;
    this._textarea.style.height = 'auto';
    this._textarea.style.height = `${Math.min(this._textarea.scrollHeight, 80)}px`;
    if (focus) {
      this._textarea.focus();
      this._textarea.setSelectionRange(text.length, text.length);
    }
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-prompt-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-prompt-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}
