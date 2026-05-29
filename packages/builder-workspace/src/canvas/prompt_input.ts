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

import type { BuilderClient }  from '../api/builder_client';
import type { ConsoleSM }      from '../state/console_state_machine';
import type { CGSStore }       from '../state/cgs_store';
import type { UIStore }        from '../state/ui_store';
import { makePilProcess }      from '../api/message_types';
import { formatCost, formatTokens } from '../types/pil';
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
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: PromptInputDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = this._build();
    container.appendChild(this._el);
    this._wireReactive();

    // Listen for pre-fill events from graph context menus, inspector buttons, etc.
    window.addEventListener('xace:prefill-prompt', this._onPrefill.bind(this) as EventListener);
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    window.removeEventListener('xace:prefill-prompt', this._onPrefill.bind(this) as EventListener);
    this._el?.remove();
  }

  private _build(): HTMLElement {
    const root = document.createElement('div');
    root.className = 'xb-prompt-area';

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

    this._unsubs.push(
      consoleSM.subscribe(state => {
        const processing = state.name === 'Processing';
        this._aiIcon.classList.toggle('spinning', processing);
        const box = this._el.querySelector<HTMLElement>('.xb-prompt-box');
        box?.classList.toggle('disabled', processing);
        this._sendBtn.disabled = processing;
        this._textarea.disabled = processing;
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