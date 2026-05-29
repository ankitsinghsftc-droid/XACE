/**
 * diff_viewer.ts — Schema Delta + Generated Code Diff Viewer
 *
 * 3-tab layout: Schema delta | Impact | Generated code
 * Schema delta is mode-adaptive:
 *   Guided/Collab  → plain-English summary + colored field rows
 *   Advanced       → path + op + value rows (technical)
 *   Architect      → raw JSON delta lines (unified diff)
 */

import type { ConsoleSM }         from '../state/console_state_machine';
import type { UIStore }           from '../state/ui_store';
import type { MutationTransaction, MutationOp } from '../types/pil';
import type { AssistanceMode }    from '../types/pil';

const DIFF_STYLES = `
.xb-dv { background: var(--bgc); border: 1px solid var(--bd); border-radius: var(--r); overflow: hidden; }
.xb-dv-tabs { display: flex; align-items: center; padding: 0 8px; border-bottom: 1px solid var(--bd); gap: 2px; }
.xb-dv-tab {
  padding: 6px 10px; border-radius: 4px 4px 0 0; font-size: 10px; font-weight: 600;
  cursor: pointer; color: var(--txt2); background: transparent; border: none; font-family: inherit;
  transition: all var(--tr-f);
}
.xb-dv-tab.on { color: var(--txt); background: rgba(255,255,255,.04); }
.xb-dv-tab:hover:not(.on) { color: var(--txt); }
.xb-dv-apply { margin-left: auto; padding: 4px 12px; background: linear-gradient(135deg, rgba(0,212,255,.18), rgba(168,85,247,.18));
  border: 1px solid rgba(0,212,255,.28); border-radius: var(--r); color: var(--cyan); font-family: inherit;
  font-size: 10.5px; font-weight: 600; cursor: pointer; transition: all var(--tr); }
.xb-dv-apply:hover { box-shadow: 0 0 16px rgba(0,212,255,.2); }
.xb-dv-body { max-height: 220px; overflow-y: auto; }
.xb-dv-panel { display: none; padding: 8px; }
.xb-dv-panel.on { display: block; }
/* Op rows */
.xb-op-row { display: flex; align-items: flex-start; gap: 6px; padding: 3px 6px; border-radius: 3px; margin-bottom: 2px; font-family: var(--font-mono); font-size: 10px; }
.xb-op-row.add { background: rgba(16,185,129,.07); border-left: 2px solid var(--grn); }
.xb-op-row.mod { background: rgba(0,212,255,.06); border-left: 2px solid var(--cyan); }
.xb-op-row.rem { background: rgba(239,68,68,.07); border-left: 2px solid var(--red); }
.xb-op-pre { width: 10px; flex-shrink: 0; }
.xb-op-row.add .xb-op-pre { color: var(--grn); }
.xb-op-row.mod .xb-op-pre { color: var(--cyan); }
.xb-op-row.rem .xb-op-pre { color: var(--red); }
.xb-op-path { color: var(--txt2); flex: 1; word-break: break-all; }
.xb-op-val { color: var(--txt); margin-left: auto; }
.xb-op-old { color: var(--red); text-decoration: line-through; margin-right: 5px; opacity: .7; }
/* Plain-English summary */
.xb-op-plain { font-size: 11px; color: var(--txt); padding: 3px 6px; line-height: 1.6; }
.xb-op-plain span { color: var(--cyan); font-weight: 500; }
/* Rust diff */
.xb-rust-diff { font-family: var(--font-mono); font-size: 9.5px; color: var(--txt2); white-space: pre-wrap; word-break: break-all; padding: 4px; }
.xb-rust-diff .add { color: rgba(167,255,210,.88); }
.xb-rust-diff .rem { color: rgba(255,100,100,.75); }
.xb-rust-diff .meta { color: var(--txt3); }
`;

export class DiffViewer {
  private readonly _consoleSM: ConsoleSM;
  private readonly _uiStore:   UIStore;
  private _el!: HTMLElement;
  private _activeTab = 'schema';
  private readonly _unsubs: Array<() => void> = [];

  constructor(consoleSM: ConsoleSM, uiStore: UIStore) {
    this._consoleSM = consoleSM;
    this._uiStore   = uiStore;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-dv';
    container.appendChild(this._el);
    this._unsubs.push(
      this._consoleSM.subscribe(() => this._render()),
      this._uiStore.select(s => s.mode, () => this._render()),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn()); this._el?.remove();
  }

  private _render(): void {
    const state = this._consoleSM.state;
    if (state.name !== 'PreviewPending') { this._el.innerHTML = ''; return; }
    const txn  = state.result.transaction;
    const mode = this._uiStore.mode;
    const frag = document.createDocumentFragment();

    // Tabs
    const tabBar = document.createElement('div');
    tabBar.className = 'xb-dv-tabs';
    const tabs = [
      { id: 'schema', label: 'Schema Changes ●' },
      { id: 'impact', label: 'Impact' },
      { id: 'code',   label: 'Generated Code' },
    ];
    for (const t of tabs) {
      const btn = document.createElement('button');
      btn.className = `xb-dv-tab${t.id === this._activeTab ? ' on' : ''}`;
      btn.textContent = t.label;
      btn.addEventListener('click', () => {
        this._activeTab = t.id;
        this._el.querySelectorAll<HTMLElement>('.xb-dv-tab').forEach(b => b.classList.toggle('on', b.textContent === t.label));
        this._el.querySelectorAll<HTMLElement>('.xb-dv-panel').forEach(p => p.classList.toggle('on', p.dataset['panel'] === t.id));
      });
      tabBar.appendChild(btn);
    }
    frag.appendChild(tabBar);

    const body = document.createElement('div');
    body.className = 'xb-dv-body';

    // Schema panel
    const schemaPan = this._makePanel('schema');
    schemaPan.appendChild(this._renderSchema(txn, mode));
    body.appendChild(schemaPan);

    // Impact panel
    const impactPan = this._makePanel('impact');
    impactPan.innerHTML = `
      <div style="font-size:10px;color:var(--txt2);padding:2px 0">Affected systems:
        <span style="color:var(--vlt)">${txn.affected_systems.join(', ') || 'none'}</span>
      </div>
      <div style="font-size:10px;color:var(--txt2);margin-top:4px">Risk: <span style="color:${txn.risk_level === 'high' ? 'var(--red)' : txn.risk_level === 'medium' ? 'var(--amb)' : 'var(--grn)'}">${txn.risk_level}</span></div>
      <div style="font-size:10px;color:var(--txt2);margin-top:4px">Recompile needed: <span style="color:var(--txt)">${txn.required_recompile ? 'Yes' : 'No'}</span></div>
    `;
    body.appendChild(impactPan);

    // Code panel
    const codePan = this._makePanel('code');
    if (state.result.diff_text) {
      codePan.appendChild(this._renderRustDiff(state.result.diff_text));
    } else {
      codePan.innerHTML = `<div style="font-size:10px;color:var(--txt3);font-style:italic;padding:4px">No Rust code generated — value mutation only.</div>`;
    }
    body.appendChild(codePan);

    frag.appendChild(body);
    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }

  private _makePanel(id: string): HTMLElement {
    const p = document.createElement('div');
    p.className      = `xb-dv-panel${id === this._activeTab ? ' on' : ''}`;
    p.dataset['panel'] = id;
    return p;
  }

  private _renderSchema(txn: MutationTransaction, mode: AssistanceMode): HTMLElement {
    const container = document.createElement('div');

    if (mode === 'FULLY_ASSISTED' || mode === 'COLLABORATIVE') {
      // Plain English
      const plain = document.createElement('div');
      plain.className = 'xb-op-plain';
      plain.innerHTML = this._toPlainEnglish(txn.operations, txn.mutation_summary);
      container.appendChild(plain);
    } else {
      // Technical / raw
      for (const op of txn.operations) {
        container.appendChild(this._opRow(op, mode));
      }
    }
    return container;
  }

  private _opRow(op: MutationOp, mode: AssistanceMode): HTMLElement {
    const cls = op.op.startsWith('ADD_') ? 'add' : op.op.startsWith('REMOVE_') ? 'rem' : 'mod';
    const pre = cls === 'add' ? '+' : cls === 'rem' ? '-' : '~';
    const row = document.createElement('div');
    row.className = `xb-op-row ${cls}`;
    if (mode === 'ARCHITECT_MODE') {
      row.innerHTML = `
        <span class="xb-op-pre">${pre}</span>
        <span class="xb-op-path">${op.path}</span>
        <span class="xb-op-val">${op.op} → ${JSON.stringify(op.value)}</span>
      `;
    } else {
      const pathShort = op.path.split('.').slice(-2).join('.');
      row.innerHTML = `
        <span class="xb-op-pre">${pre}</span>
        <span class="xb-op-path">${pathShort}</span>
        <span class="xb-op-val">${op.op === 'SCALE' ? `×${op.value}` : JSON.stringify(op.value)}</span>
      `;
    }
    return row;
  }

  private _toPlainEnglish(ops: MutationOp[], summary: string): string {
    if (summary) return `<span>${summary}</span>`;
    return ops.slice(0, 3).map(op => {
      const field  = op.field_name || op.path.split('.').pop() || '?';
      const actor  = op.actor_id || 'entity';
      const val    = JSON.stringify(op.value);
      if (op.op === 'SET')   return `Sets <span>${actor}</span> ${field} to <span>${val}</span>`;
      if (op.op === 'SCALE') return `Scales <span>${actor}</span> ${field} by <span>${op.value}</span>`;
      if (op.op.startsWith('ADD_')) return `Adds new ${op.op.replace('ADD_', '').toLowerCase()}`;
      return `Removes ${op.op.replace('REMOVE_', '').toLowerCase()} from <span>${actor}</span>`;
    }).join('. ');
  }

  private _renderRustDiff(diffText: string): HTMLElement {
    const pre = document.createElement('div');
    pre.className = 'xb-rust-diff';
    pre.innerHTML = diffText.split('\n').map(line => {
      if (line.startsWith('+') && !line.startsWith('+++')) return `<span class="add">${escHtml(line)}</span>`;
      if (line.startsWith('-') && !line.startsWith('---')) return `<span class="rem">${escHtml(line)}</span>`;
      if (line.startsWith('@@') || line.startsWith('---') || line.startsWith('+++')) return `<span class="meta">${escHtml(line)}</span>`;
      return escHtml(line);
    }).join('\n');
    return pre;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-dv-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-dv-styles';
    s.textContent = DIFF_STYLES;
    document.head.appendChild(s);
  }
}

function escHtml(s: string): string {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}


/**
 * impact_preview.ts — Mutation Impact Preview
 */
export class ImpactPreview {
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'padding:8px 10px;font-size:10.5px';
    container.appendChild(this._el);
  }

  update(txn: MutationTransaction | null): void {
    if (!txn) { this._el.innerHTML = ''; return; }
    const riskColor = { low: 'var(--grn)', medium: 'var(--amb)', high: 'var(--red)' }[txn.risk_level] ?? 'var(--txt)';
    this._el.innerHTML = `
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <div><span style="color:var(--txt2)">Risk</span> <span style="color:${riskColor};font-weight:600">${txn.risk_level}</span></div>
        <div><span style="color:var(--txt2)">Confidence</span> <span style="color:var(--txt)">${Math.round(txn.confidence_score * 100)}%</span></div>
        <div><span style="color:var(--txt2)">Systems</span> <span style="color:var(--vlt)">${txn.affected_systems.length}</span></div>
        ${txn.required_recompile ? `<div style="color:var(--amb)">⚠ recompile needed</div>` : ''}
      </div>
    `;
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn()); this._el?.remove();
  }
}


/**
 * inference_cost_indicator.ts — Running cost + token display
 */
export class InferenceCostIndicator {
  private _el!: HTMLElement;

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'display:flex;align-items:center;gap:5px;font-size:9.5px;color:var(--txt2);font-family:var(--font-mono);padding:3px 0';
    this._el.innerHTML = `<div style="width:5px;height:5px;border-radius:50%;background:var(--vlt)"></div><span id="xb-cost-tok">0 tok</span> · <span id="xb-cost-$">$0.00</span>`;
    container.appendChild(this._el);
  }

  update(tokens: number, costCents: number): void {
    const tokEl  = document.getElementById('xb-cost-tok');
    const costEl = document.getElementById('xb-cost-$');
    if (tokEl)  tokEl.textContent  = formatTokens(tokens) + ' tok';
    if (costEl) costEl.textContent = formatCost(costCents);
  }

  unmount(): void { this._el?.remove(); }
}


/**
 * technical_detail_toggle.ts — Mode-adaptive content wrapper
 * Renders plain-English in Guided/Collab, raw data in Advanced/Architect.
 */
export class TechnicalDetailToggle {
  private _el!: HTMLElement;

  mount(container: HTMLElement, plainContent: string, rawContent: string, mode: AssistanceMode): void {
    this._el = document.createElement('div');
    this._render(plainContent, rawContent, mode);
    container.appendChild(this._el);
  }

  update(plainContent: string, rawContent: string, mode: AssistanceMode): void {
    this._render(plainContent, rawContent, mode);
  }

  private _render(plain: string, raw: string, mode: AssistanceMode): void {
    const showPlain = mode === 'FULLY_ASSISTED' || mode === 'COLLABORATIVE';
    this._el.innerHTML = showPlain ? plain : raw;
  }

  unmount(): void { this._el?.remove(); }
}

import { formatCost, formatTokens } from '../types/pil';