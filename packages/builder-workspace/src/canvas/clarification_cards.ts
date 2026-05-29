/**
 * clarification_cards.ts — PIL Clarification Question Cards
 *
 * Renders the 4 question types from ClarificationSession:
 *   CHOICE       — radio group of mutually exclusive options
 *   CONFIRM      — binary confirm/deny with optional detail fields
 *   FILL         — number/text input for explicit value
 *   SCOPE_SELECT — checkbox group for multi-entity scope selection
 *
 * On submit: sends pil_answer WebSocket message with the answer.
 * On completion (all questions answered): consoleSM.advanceClarification(null)
 * triggers pipeline re-run with resolved parameters.
 *
 * Design: maximum 2 cards visible at once (grid layout). Answered
 * cards are shown as collapsed with a green check. The current
 * unanswered card is highlighted.
 */

import type { BuilderClient }      from '../api/builder_client';
import type { ConsoleSM }          from '../state/console_state_machine';
import type { ClarificationQuestion, QuestionType } from '../types/pil';
import { makePilAnswer }           from '../api/message_types';

const STYLES = `
.xb-clar-wrap {
  padding:         12px;
  display:         flex;
  flex-direction:  column;
  gap:             10px;
  animation:       fade-in 200ms ease-out;
}
.xb-clar-header {
  font-size:       11.5px;
  font-weight:     600;
  color:           var(--txt);
  display:         flex;
  align-items:     center;
  gap:             7px;
}
.xb-clar-icon {
  width:           22px;
  height:          22px;
  border-radius:   50%;
  background:      var(--cynd);
  border:          1px solid rgba(0,212,255,.3);
  display:         flex;
  align-items:     center;
  justify-content: center;
  font-size:       11px;
  color:           var(--cyan);
  flex-shrink:     0;
}
.xb-clar-sub {
  font-size:       10px;
  color:           var(--txt2);
}
.xb-clar-grid {
  display:         grid;
  grid-template-columns: 1fr 1fr;
  gap:             8px;
}
.xb-cc {
  background:      var(--bgc);
  border:          1px solid var(--bd);
  border-radius:   var(--r);
  padding:         10px;
  transition:      border-color var(--tr);
}
.xb-cc:focus-within { border-color: var(--bdh); }
.xb-cc.active { border-color: rgba(0,212,255,.3); }
.xb-cc.answered {
  opacity:         .5;
  border-color:    var(--bd);
}
.xb-cc-badge {
  font-size:       8px;
  font-weight:     700;
  letter-spacing:  .1em;
  text-transform:  uppercase;
  padding:         2px 5px;
  border-radius:   3px;
  margin-bottom:   6px;
  display:         inline-block;
}
.badge-choice   { background: rgba(0,212,255,.1);   color: var(--cyan); }
.badge-confirm  { background: rgba(168,85,247,.1);  color: var(--vlt); }
.badge-fill     { background: rgba(16,185,129,.1);  color: var(--grn); }
.badge-scope    { background: rgba(255,159,67,.1);  color: var(--amb); }
.xb-cc-q {
  font-size:       11px;
  font-weight:     600;
  color:           var(--txt);
  margin-bottom:   7px;
  line-height:     1.4;
}
.xb-cc-hint {
  font-size:       9.5px;
  color:           var(--txt2);
  margin-bottom:   6px;
  font-style:      italic;
}
/* Radio group */
.xb-radio-group { display: flex; flex-direction: column; gap: 3px; }
.xb-radio-opt {
  display:         flex;
  align-items:     center;
  gap:             6px;
  padding:         4px 7px;
  border-radius:   4px;
  cursor:          pointer;
  font-size:       10.5px;
  color:           var(--txt2);
  border:          1px solid transparent;
  transition:      all var(--tr-f);
  user-select:     none;
}
.xb-radio-opt:hover { background: rgba(255,255,255,.03); color: var(--txt); }
.xb-radio-opt.selected {
  border-color:    rgba(0,212,255,.28);
  background:      var(--cynd);
  color:           var(--cyan);
}
.xb-radio-circle {
  width:           11px;
  height:          11px;
  border-radius:   50%;
  border:          1.5px solid currentColor;
  display:         flex;
  align-items:     center;
  justify-content: center;
  flex-shrink:     0;
  transition:      all var(--tr-f);
}
.xb-radio-circle::after {
  content:         '';
  width:           5px;
  height:          5px;
  border-radius:   50%;
  background:      currentColor;
  opacity:         0;
  transition:      opacity 100ms;
}
.xb-radio-opt.selected .xb-radio-circle::after { opacity: 1; }
/* Fill input */
.xb-fill-inp {
  width:           100%;
  background:      rgba(255,255,255,.03);
  border:          1px solid var(--bd);
  border-radius:   var(--rs);
  padding:         5px 8px;
  color:           var(--txt);
  font-size:       11px;
  font-family:     var(--font-mono);
  outline:         none;
  transition:      border-color var(--tr-f);
}
.xb-fill-inp:focus { border-color: var(--cyan); }
/* Scope checkboxes */
.xb-scope-grid {
  display:         grid;
  grid-template-columns: 1fr 1fr;
  gap:             4px;
}
.xb-scope-opt {
  display:         flex;
  align-items:     center;
  gap:             4px;
  font-size:       10px;
  cursor:          pointer;
  color:           var(--txt2);
  padding:         2px 0;
  user-select:     none;
}
.xb-scope-opt input { accent-color: var(--amb); }
.xb-scope-opt.checked { color: var(--amb); }
/* Submit button */
.xb-cc-submit {
  margin-top:      8px;
  width:           100%;
  padding:         5px;
  background:      rgba(0,212,255,.08);
  border:          1px solid rgba(0,212,255,.25);
  border-radius:   var(--rs);
  color:           var(--cyan);
  font-size:       10.5px;
  font-weight:     600;
  cursor:          pointer;
  font-family:     inherit;
  transition:      all var(--tr-f);
}
.xb-cc-submit:hover {
  background:      var(--cynd);
  box-shadow:      0 0 10px rgba(0,212,255,.15);
}
.xb-cc-submit:disabled { opacity: .4; cursor: not-allowed; }
.xb-clar-progress {
  display:         flex;
  align-items:     center;
  gap:             5px;
  font-size:       9.5px;
  color:           var(--txt2);
}
.xb-clar-progress-bar {
  flex:            1;
  height:          2px;
  background:      var(--bd);
  border-radius:   2px;
  overflow:        hidden;
}
.xb-clar-progress-fill {
  height:          100%;
  background:      var(--cyan);
  border-radius:   2px;
  transition:      width 300ms ease-out;
}
`;

const BADGE_CLASS: Record<QuestionType, string> = {
  CHOICE:       'badge-choice',
  CONFIRM:      'badge-confirm',
  FILL:         'badge-fill',
  SCOPE_SELECT: 'badge-scope',
};

interface ClarificationCardsDeps {
  client:    BuilderClient;
  consoleSM: ConsoleSM;
}

export class ClarificationCards {
  private readonly _deps: ClarificationCardsDeps;
  private _el!:   HTMLElement;
  private _state: import('../state/console_state_machine').ClarificationFlowState | null = null;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: ClarificationCardsDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    container.appendChild(this._el);
    this._unsubs.push(
      this._deps.consoleSM.subscribe(state => {
        if (state.name === 'ClarificationFlow') {
          this._state = state;
          this._render();
        }
      }),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _render(): void {
    if (!this._state) { this._el.innerHTML = ''; return; }

    const { result, answeredCount, currentQuestion } = this._state;
    const total = result.questions.length;

    const frag = document.createDocumentFragment();
    const wrap = document.createElement('div');
    wrap.className = 'xb-clar-wrap';

    // Header
    const hdr = document.createElement('div');
    hdr.innerHTML = `
      <div class="xb-clar-header">
        <div class="xb-clar-icon">?</div>
        <div>
          <div>A few questions</div>
          <div class="xb-clar-sub">${result.reason || 'Help me understand your intent'}</div>
        </div>
      </div>
    `;
    wrap.appendChild(hdr);

    // Progress bar
    if (total > 1) {
      const prog = document.createElement('div');
      prog.className = 'xb-clar-progress';
      prog.innerHTML = `
        <span>${answeredCount} of ${total}</span>
        <div class="xb-clar-progress-bar">
          <div class="xb-clar-progress-fill" style="width:${Math.round(answeredCount / total * 100)}%"></div>
        </div>
      `;
      wrap.appendChild(prog);
    }

    // Question grid (show current + next if available)
    const grid = document.createElement('div');
    grid.className = 'xb-clar-grid';

    if (currentQuestion) {
      grid.appendChild(this._makeCard(currentQuestion, true));
    }

    // Show a second card preview if more questions exist
    const nextIdx = answeredCount + 1;
    if (nextIdx < total) {
      const nextQ = result.questions[nextIdx];
      if (nextQ) grid.appendChild(this._makeCard(nextQ, false));
    }

    wrap.appendChild(grid);
    frag.appendChild(wrap);
    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }

  private _makeCard(q: ClarificationQuestion, isActive: boolean): HTMLElement {
    const card = document.createElement('div');
    card.className = `xb-cc${isActive ? ' active' : ''}`;

    const badge = document.createElement('div');
    badge.className = `xb-cc-badge ${BADGE_CLASS[q.question_type]}`;
    badge.textContent = q.question_type.replace('_', ' ');
    card.appendChild(badge);

    const question = document.createElement('div');
    question.className   = 'xb-cc-q';
    question.textContent = q.prompt;
    card.appendChild(question);

    if (q.hint) {
      const hint = document.createElement('div');
      hint.className   = 'xb-cc-hint';
      hint.textContent = q.hint;
      card.appendChild(hint);
    }

    // Options / input
    let getAnswer: () => string = () => '';

    if (q.question_type === 'CHOICE') {
      let selected = q.options[0] ?? '';
      const group  = document.createElement('div');
      group.className = 'xb-radio-group';
      for (const opt of q.options) {
        const row  = document.createElement('div');
        row.className = `xb-radio-opt${opt === selected ? ' selected' : ''}`;
        row.innerHTML = `<div class="xb-radio-circle"></div><span>${opt}</span>`;
        row.addEventListener('click', () => {
          selected = opt;
          group.querySelectorAll<HTMLElement>('.xb-radio-opt').forEach(r => {
            r.classList.toggle('selected', r.querySelector('span')?.textContent === opt);
          });
        });
        group.appendChild(row);
      }
      card.appendChild(group);
      getAnswer = () => selected;

    } else if (q.question_type === 'CONFIRM') {
      let confirmed = true;
      const group   = document.createElement('div');
      group.className = 'xb-radio-group';
      for (const opt of (q.options.length ? q.options : ['Yes', 'No'])) {
        const row = document.createElement('div');
        row.className = `xb-radio-opt${opt === 'Yes' ? ' selected' : ''}`;
        row.innerHTML = `<div class="xb-radio-circle"></div><span>${opt}</span>`;
        row.addEventListener('click', () => {
          confirmed = opt !== 'No';
          group.querySelectorAll<HTMLElement>('.xb-radio-opt').forEach(r => {
            r.classList.toggle('selected', r.querySelector('span')?.textContent === opt);
          });
        });
        group.appendChild(row);
      }
      card.appendChild(group);
      getAnswer = () => confirmed ? 'yes' : 'no';

    } else if (q.question_type === 'FILL') {
      const inp = document.createElement('input');
      inp.className   = 'xb-fill-inp';
      inp.type        = 'text';
      inp.placeholder = 'Enter value…';
      card.appendChild(inp);
      getAnswer = () => inp.value.trim();

    } else if (q.question_type === 'SCOPE_SELECT') {
      const selectedOpts = new Set<string>(q.options.slice(0, 1));
      const scopeGrid    = document.createElement('div');
      scopeGrid.className = 'xb-scope-grid';
      for (const opt of q.options) {
        const lbl = document.createElement('label');
        lbl.className = `xb-scope-opt${selectedOpts.has(opt) ? ' checked' : ''}`;
        const cb = document.createElement('input');
        cb.type    = 'checkbox';
        cb.checked = selectedOpts.has(opt);
        cb.addEventListener('change', () => {
          if (cb.checked) selectedOpts.add(opt);
          else selectedOpts.delete(opt);
          lbl.classList.toggle('checked', cb.checked);
        });
        lbl.appendChild(cb);
        lbl.appendChild(document.createTextNode(opt));
        scopeGrid.appendChild(lbl);
      }
      card.appendChild(scopeGrid);
      getAnswer = () => [...selectedOpts].join(',');
    }

    // Submit button (only on active card)
    if (isActive) {
      const btn = document.createElement('button');
      btn.className   = 'xb-cc-submit';
      btn.textContent = 'Confirm →';
      btn.addEventListener('click', () => {
        const answer = getAnswer();
        if (!answer) return;
        this._deps.client.send(makePilAnswer(
          this._state!.result.clarification_session_id,
          answer,
          this._deps.client.sessionId,
        ));
      });
      card.appendChild(btn);
    }

    return card;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-clar-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-clar-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}