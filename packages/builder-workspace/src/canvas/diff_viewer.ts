/**
 * diff_viewer.ts - Structured prompt diff preview.
 */

import type { ConsoleSM } from '../state/console_state_machine';
import type { UIStore } from '../state/ui_store';
import type {
  AssistanceMode,
  MutationOp,
  MutationTransaction,
  PromptDiffPreview,
} from '../types/pil';
import { formatCost, formatTokens } from '../types/pil';

const DIFF_STYLES = `
.xb-dv { background: var(--bgc); border: 1px solid var(--bd); border-radius: var(--r); overflow: hidden; }
.xb-dv-tabs { display: flex; align-items: center; padding: 0 8px; border-bottom: 1px solid var(--bd); gap: 2px; overflow-x: auto; }
.xb-dv-tab { padding: 6px 10px; border-radius: 4px 4px 0 0; font-size: 10px; font-weight: 600; cursor: pointer; color: var(--txt2); background: transparent; border: none; font-family: inherit; transition: all var(--tr-f); white-space: nowrap; }
.xb-dv-tab.on { color: var(--txt); background: rgba(255,255,255,.04); }
.xb-dv-tab:hover:not(.on) { color: var(--txt); }
.xb-dv-body { max-height: 260px; overflow-y: auto; }
.xb-dv-panel { display: none; padding: 8px; }
.xb-dv-panel.on { display: block; }
.xb-dv-section { border: 1px solid rgba(255,255,255,.06); border-radius: 6px; padding: 7px; margin-bottom: 6px; background: rgba(255,255,255,.025); }
.xb-dv-section-title { color: var(--txt); font-size: 10.5px; font-weight: 700; margin-bottom: 5px; }
.xb-dv-kv { display: grid; grid-template-columns: minmax(95px, 35%) 1fr; gap: 4px 8px; font-size: 10px; color: var(--txt2); }
.xb-dv-kv span:nth-child(2n) { color: var(--txt); font-family: var(--font-mono); word-break: break-word; }
.xb-op-row { display: flex; align-items: flex-start; gap: 6px; padding: 3px 6px; border-radius: 3px; margin-bottom: 2px; font-family: var(--font-mono); font-size: 10px; }
.xb-op-row.add { background: rgba(16,185,129,.07); border-left: 2px solid var(--grn); }
.xb-op-row.mod { background: rgba(0,212,255,.06); border-left: 2px solid var(--cyan); }
.xb-op-row.rem { background: rgba(239,68,68,.07); border-left: 2px solid var(--red); }
.xb-op-pre { width: 10px; flex-shrink: 0; }
.xb-op-row.add .xb-op-pre { color: var(--grn); }
.xb-op-row.mod .xb-op-pre { color: var(--cyan); }
.xb-op-row.rem .xb-op-pre { color: var(--red); }
.xb-op-path { color: var(--txt2); flex: 1; word-break: break-all; }
.xb-op-val { color: var(--txt); margin-left: auto; text-align: right; max-width: 45%; word-break: break-word; }
.xb-op-old { color: var(--red); text-decoration: line-through; margin-right: 5px; opacity: .7; }
.xb-op-plain { font-size: 11px; color: var(--txt); padding: 3px 6px; line-height: 1.6; }
.xb-op-plain span { color: var(--cyan); font-weight: 500; }
.xb-rust-diff { font-family: var(--font-mono); font-size: 9.5px; color: var(--txt2); white-space: pre-wrap; word-break: break-all; padding: 4px; }
.xb-rust-diff .add { color: rgba(167,255,210,.88); }
.xb-rust-diff .rem { color: rgba(255,100,100,.75); }
.xb-rust-diff .meta { color: var(--txt3); }
`;

export class DiffViewer {
  private readonly consoleSM: ConsoleSM;
  private readonly uiStore: UIStore;
  private el!: HTMLElement;
  private activeTab = 'cgs';
  private readonly unsubs: Array<() => void> = [];

  constructor(consoleSM: ConsoleSM, uiStore: UIStore) {
    this.consoleSM = consoleSM;
    this.uiStore = uiStore;
    injectDiffStyles();
  }

  mount(container: HTMLElement): void {
    this.el = document.createElement('div');
    this.el.className = 'xb-dv';
    container.appendChild(this.el);
    this.unsubs.push(
      this.consoleSM.subscribe(() => this.render()),
      this.uiStore.select(s => s.mode, () => this.render()),
    );
  }

  unmount(): void {
    this.unsubs.splice(0).forEach(fn => fn());
    this.el?.remove();
  }

  private render(): void {
    const state = this.consoleSM.state;
    if (state.name !== 'PreviewPending') {
      this.el.innerHTML = '';
      return;
    }

    const txn = state.result.transaction;
    const preview = state.result.preview;
    const tabs = preview
      ? [
          { id: 'cgs', label: 'CGS' },
          { id: 'systems', label: 'Systems' },
          { id: 'assets', label: 'Assets' },
          { id: 'sgc-runtime', label: 'SGC/Runtime' },
          { id: 'cost', label: 'Cost' },
          { id: 'code', label: 'Code' },
        ]
      : [
          { id: 'cgs', label: 'Schema Changes' },
          { id: 'systems', label: 'Impact' },
          { id: 'code', label: 'Generated Code' },
        ];
    if (!tabs.some(tab => tab.id === this.activeTab)) {
      this.activeTab = tabs[0]?.id ?? 'cgs';
    }

    const frag = document.createDocumentFragment();
    const tabBar = document.createElement('div');
    tabBar.className = 'xb-dv-tabs';
    for (const tab of tabs) {
      const button = document.createElement('button');
      button.className = `xb-dv-tab${tab.id === this.activeTab ? ' on' : ''}`;
      button.textContent = tab.label;
      button.addEventListener('click', () => {
        this.activeTab = tab.id;
        this.render();
      });
      tabBar.appendChild(button);
    }
    frag.appendChild(tabBar);

    const body = document.createElement('div');
    body.className = 'xb-dv-body';
    body.appendChild(this.makePanel('cgs', this.renderCgs(txn, preview)));
    body.appendChild(this.makePanel('systems', preview ? renderObjectSection('System Diff', preview.system_diff) : renderLegacyImpact(txn)));
    if (preview) {
      body.appendChild(this.makePanel('assets', renderObjectSection('Asset Diff', preview.asset_diff)));
      const sgcRuntime = document.createElement('div');
      sgcRuntime.appendChild(renderObjectSection('SGC Diff', preview.sgc_diff));
      sgcRuntime.appendChild(renderObjectSection('Runtime Diff', preview.runtime_diff));
      body.appendChild(this.makePanel('sgc-runtime', sgcRuntime));
      body.appendChild(this.makePanel('cost', renderObjectSection('Cost Diff', preview.cost_diff)));
    }
    body.appendChild(this.makePanel('code', this.renderCode(state.result.diff_text)));
    frag.appendChild(body);

    this.el.innerHTML = '';
    this.el.appendChild(frag);
  }

  private makePanel(id: string, content: HTMLElement): HTMLElement {
    const panel = document.createElement('div');
    panel.className = `xb-dv-panel${id === this.activeTab ? ' on' : ''}`;
    panel.dataset.panel = id;
    panel.appendChild(content);
    return panel;
  }

  private renderCgs(txn: MutationTransaction, preview: PromptDiffPreview | undefined): HTMLElement {
    const container = document.createElement('div');
    if (preview) {
      for (const op of preview.cgs_diff.operations) {
        container.appendChild(renderPreviewOpRow(op, this.uiStore.mode));
      }
      return container;
    }
    if (this.uiStore.mode === 'FULLY_ASSISTED' || this.uiStore.mode === 'COLLABORATIVE') {
      const plain = document.createElement('div');
      plain.className = 'xb-op-plain';
      plain.innerHTML = toPlainEnglish(txn.operations, txn.mutation_summary);
      container.appendChild(plain);
      return container;
    }
    for (const op of txn.operations) {
      container.appendChild(renderOpRow(op, this.uiStore.mode));
    }
    return container;
  }

  private renderCode(diffText: string): HTMLElement {
    if (!diffText) {
      const empty = document.createElement('div');
      empty.style.cssText = 'font-size:10px;color:var(--txt3);font-style:italic;padding:4px';
      empty.textContent = 'No Rust code generated - value mutation only.';
      return empty;
    }
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
}

function renderPreviewOpRow(op: PromptDiffPreview['cgs_diff']['operations'][number], mode: AssistanceMode): HTMLElement {
  const cls = op.op.startsWith('ADD_') ? 'add' : op.op.startsWith('REMOVE_') ? 'rem' : 'mod';
  const pre = cls === 'add' ? '+' : cls === 'rem' ? '-' : '~';
  const oldValue = op.old_value === null || op.old_value === undefined ? 'none' : JSON.stringify(op.old_value);
  const newValue = op.preview_value === undefined ? JSON.stringify(op.new_value) : JSON.stringify(op.preview_value);
  const label = mode === 'ARCHITECT_MODE' || mode === 'ADVANCED'
    ? op.path
    : (op.field_name || op.path.split('.').slice(-2).join('.'));
  const row = document.createElement('div');
  row.className = `xb-op-row ${cls}`;
  row.innerHTML = `
    <span class="xb-op-pre">${pre}</span>
    <span class="xb-op-path">${escHtml(label)}</span>
    <span class="xb-op-val"><span class="xb-op-old">${escHtml(oldValue)}</span>${escHtml(newValue ?? 'none')}</span>
  `;
  return row;
}

function renderOpRow(op: MutationOp, mode: AssistanceMode): HTMLElement {
  const cls = op.op.startsWith('ADD_') ? 'add' : op.op.startsWith('REMOVE_') ? 'rem' : 'mod';
  const pre = cls === 'add' ? '+' : cls === 'rem' ? '-' : '~';
  const row = document.createElement('div');
  row.className = `xb-op-row ${cls}`;
  const path = mode === 'ARCHITECT_MODE' ? op.path : op.path.split('.').slice(-2).join('.');
  const value = op.op === 'SCALE' ? `x${op.value}` : JSON.stringify(op.value);
  row.innerHTML = `
    <span class="xb-op-pre">${pre}</span>
    <span class="xb-op-path">${escHtml(path)}</span>
    <span class="xb-op-val">${escHtml(`${op.op} -> ${value}`)}</span>
  `;
  return row;
}

function renderLegacyImpact(txn: MutationTransaction): HTMLElement {
  const riskColor = txn.risk_level === 'high' ? 'var(--red)' : txn.risk_level === 'medium' ? 'var(--amb)' : 'var(--grn)';
  const wrap = document.createElement('div');
  wrap.innerHTML = `
    <div style="font-size:10px;color:var(--txt2);padding:2px 0">Affected systems:
      <span style="color:var(--vlt)">${escHtml(txn.affected_systems.join(', ') || 'none')}</span>
    </div>
    <div style="font-size:10px;color:var(--txt2);margin-top:4px">Risk: <span style="color:${riskColor}">${escHtml(txn.risk_level)}</span></div>
    <div style="font-size:10px;color:var(--txt2);margin-top:4px">Recompile needed: <span style="color:var(--txt)">${txn.required_recompile ? 'Yes' : 'No'}</span></div>
  `;
  return wrap;
}

function renderObjectSection(title: string, value: Record<string, unknown>): HTMLElement {
  const section = document.createElement('div');
  section.className = 'xb-dv-section';
  const heading = document.createElement('div');
  heading.className = 'xb-dv-section-title';
  heading.textContent = title;
  section.appendChild(heading);
  const grid = document.createElement('div');
  grid.className = 'xb-dv-kv';
  for (const [key, raw] of Object.entries(value)) {
    if (key === 'schema') continue;
    const k = document.createElement('span');
    k.textContent = key;
    const v = document.createElement('span');
    v.textContent = formatPreviewValue(raw);
    grid.appendChild(k);
    grid.appendChild(v);
  }
  section.appendChild(grid);
  return section;
}

function toPlainEnglish(ops: MutationOp[], summary: string): string {
  if (summary) return `<span>${escHtml(summary)}</span>`;
  return ops.slice(0, 3).map(op => {
    const field = op.field_name || op.path.split('.').pop() || '?';
    const actor = op.actor_id || 'entity';
    const value = JSON.stringify(op.value);
    if (op.op === 'SET') return `Sets <span>${escHtml(actor)}</span> ${escHtml(field)} to <span>${escHtml(value)}</span>`;
    if (op.op === 'SCALE') return `Scales <span>${escHtml(actor)}</span> ${escHtml(field)} by <span>${escHtml(String(op.value))}</span>`;
    if (op.op.startsWith('ADD_')) return `Adds new ${escHtml(op.op.replace('ADD_', '').toLowerCase())}`;
    return `Removes ${escHtml(op.op.replace('REMOVE_', '').toLowerCase())} from <span>${escHtml(actor)}</span>`;
  }).join('. ');
}

function formatPreviewValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.map(formatPreviewValue).join(', ') : 'none';
  if (value === null || value === undefined || value === '') return 'none';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function escHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function injectDiffStyles(): void {
  if (document.getElementById('xb-dv-styles')) return;
  const style = document.createElement('style');
  style.id = 'xb-dv-styles';
  style.textContent = DIFF_STYLES;
  document.head.appendChild(style);
}

export class ImpactPreview {
  private el!: HTMLElement;
  private readonly unsubs: Array<() => void> = [];

  mount(container: HTMLElement): void {
    this.el = document.createElement('div');
    this.el.style.cssText = 'padding:8px 10px;font-size:10.5px';
    container.appendChild(this.el);
  }

  update(txn: MutationTransaction | null): void {
    if (!txn) {
      this.el.innerHTML = '';
      return;
    }
    const riskColor = { low: 'var(--grn)', medium: 'var(--amb)', high: 'var(--red)' }[txn.risk_level] ?? 'var(--txt)';
    this.el.innerHTML = `
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <div><span style="color:var(--txt2)">Risk</span> <span style="color:${riskColor};font-weight:600">${escHtml(txn.risk_level)}</span></div>
        <div><span style="color:var(--txt2)">Confidence</span> <span style="color:var(--txt)">${Math.round(txn.confidence_score * 100)}%</span></div>
        <div><span style="color:var(--txt2)">Systems</span> <span style="color:var(--vlt)">${txn.affected_systems.length}</span></div>
        ${txn.required_recompile ? '<div style="color:var(--amb)">recompile needed</div>' : ''}
      </div>
    `;
  }

  unmount(): void {
    this.unsubs.splice(0).forEach(fn => fn());
    this.el?.remove();
  }
}

export class InferenceCostIndicator {
  private el!: HTMLElement;

  mount(container: HTMLElement): void {
    this.el = document.createElement('div');
    this.el.style.cssText = 'display:flex;align-items:center;gap:5px;font-size:9.5px;color:var(--txt2);font-family:var(--font-mono);padding:3px 0';
    this.el.innerHTML = '<div style="width:5px;height:5px;border-radius:50%;background:var(--vlt)"></div><span id="xb-cost-tok">0 tok</span> - <span id="xb-cost-money">$0.00</span>';
    container.appendChild(this.el);
  }

  update(tokens: number, costCents: number): void {
    const tokenEl = document.getElementById('xb-cost-tok');
    const costEl = document.getElementById('xb-cost-money');
    if (tokenEl) tokenEl.textContent = `${formatTokens(tokens)} tok`;
    if (costEl) costEl.textContent = formatCost(costCents);
  }

  unmount(): void {
    this.el?.remove();
  }
}

export class TechnicalDetailToggle {
  private el!: HTMLElement;

  mount(container: HTMLElement, plainContent: string, rawContent: string, mode: AssistanceMode): void {
    this.el = document.createElement('div');
    this.render(plainContent, rawContent, mode);
    container.appendChild(this.el);
  }

  update(plainContent: string, rawContent: string, mode: AssistanceMode): void {
    this.render(plainContent, rawContent, mode);
  }

  private render(plain: string, raw: string, mode: AssistanceMode): void {
    const showPlain = mode === 'FULLY_ASSISTED' || mode === 'COLLABORATIVE';
    this.el.innerHTML = showPlain ? plain : raw;
  }

  unmount(): void {
    this.el?.remove();
  }
}
