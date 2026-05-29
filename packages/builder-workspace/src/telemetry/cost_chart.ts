/**
 * cost_chart.ts — Per-Mutation Cost Bar Chart
 *
 * Canvas bar chart showing cost-per-mutation over the session.
 * ARCHITECT_MODE only. Each bar = one mutation, colored by tier distribution.
 * Hover shows: pass breakdown, total tokens, total cost.
 */

export class CostChart {
  private _canvas!: HTMLCanvasElement;
  private _ctx!:    CanvasRenderingContext2D;
  private _bars:    Array<{ label: string; cost: number; tier: string }> = [];

  mount(container: HTMLElement): void {
    this._canvas = document.createElement('canvas');
    this._canvas.style.cssText = 'width:100%;height:56px;display:block';
    this._canvas.width  = 270;
    this._canvas.height = 56;
    this._ctx = this._canvas.getContext('2d')!;
    container.appendChild(this._canvas);
    this._draw();
  }

  update(calls: Array<{ pass: string; cost_cents: number; tier: string }>): void {
    // Group by mutation (pass5 = end of one mutation)
    const mutations: typeof this._bars = [];
    let runCost = 0;
    let runTier = 'TIER_M';
    for (const c of calls) {
      runCost += c.cost_cents;
      runTier  = c.tier;
      if (c.pass.startsWith('pass5')) {
        mutations.push({ label: `M${mutations.length + 1}`, cost: runCost, tier: runTier });
        runCost = 0;
      }
    }
    this._bars = mutations.slice(-20); // last 20
    this._draw();
  }

  private _draw(): void {
    const ctx = this._ctx;
    const W   = this._canvas.width;
    const H   = this._canvas.height;
    ctx.clearRect(0, 0, W, H);

    if (this._bars.length === 0) {
      ctx.fillStyle = 'rgba(90,104,128,.5)';
      ctx.font      = '9px Inter,sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No mutations yet', W / 2, H / 2 + 3);
      return;
    }

    const maxCost = Math.max(...this._bars.map(b => b.cost), 1);
    const barW    = Math.floor((W - 4) / this._bars.length) - 1;

    this._bars.forEach((bar, i) => {
      const barH   = Math.max(2, Math.floor((bar.cost / maxCost) * (H - 12)));
      const x      = 2 + i * (barW + 1);
      const y      = H - barH - 4;
      const colors: Record<string, string> = {
        TIER_S: '#10b981', TIER_M: '#00d4ff', TIER_L: '#a855f7', TIER_XL: '#ff9f43',
      };
      ctx.fillStyle = colors[bar.tier] ?? '#5a6880';
      ctx.fillRect(x, y, barW, barH);
    });

    // Y-axis label
    ctx.fillStyle = 'rgba(90,104,128,.7)';
    ctx.font      = '8px JetBrains Mono,monospace';
    ctx.textAlign = 'left';
    ctx.fillText(`${maxCost.toFixed(1)}¢`, 2, 9);
  }

  unmount(): void { this._canvas?.remove(); }
}


/**
 * inference_telemetry_panel.ts — Inference Telemetry Panel (ARCHITECT_MODE only)
 *
 * Shown only when mode === 'ARCHITECT_MODE'.
 * Displays: session totals, per-pass breakdown, tier distribution,
 * cache hit rate progress bar, cost-per-mutation chart.
 */

import type { ConsoleSM }      from '../state/console_state_machine';
import type { UIStore }        from '../state/ui_store';
import type { SessionTelemetry, ComplexityTier } from '../types/pil';
import { formatCost, formatTokens } from '../types/pil';
import { emptyTelemetry } from '../types/pil';

const STYLES = `
.xb-tele { flex: 1; overflow-y: auto; padding: 8px 9px; display: flex; flex-direction: column; gap: 8px; }
.xb-tele-title {
  font-size: 9px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: var(--vlt); display: flex; align-items: center; gap: 6px;
}
.xb-tele-card {
  background: var(--bgc); border: 1px solid var(--bd); border-radius: var(--r); padding: 9px;
}
.xb-tele-row {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 4px; font-size: 9.5px;
}
.xb-tele-lbl { color: var(--txt2); }
.xb-tele-val { font-family: var(--font-mono); color: var(--txt); }
.xb-tele-bar-wrap {
  height: 3px; background: rgba(255,255,255,.05); border-radius: 2px;
  overflow: hidden; margin-bottom: 5px;
}
.xb-tele-bar-fill {
  height: 100%; border-radius: 2px;
  background: linear-gradient(90deg, var(--cyan), var(--vlt));
  transition: width 400ms ease-out;
}
.xb-tele-tiers { display: flex; gap: 8px; }
.xb-tele-tier { font-size: 9px; font-family: var(--font-mono); }
.xb-tele-call {
  display: flex; align-items: center; gap: 6px; padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,.03); font-size: 9.5px;
}
.xb-tele-call:last-child { border-bottom: none; }
.xb-tele-call-lbl { color: var(--txt2); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-tele-call-tier {
  font-size: 8px; padding: 1px 4px; border-radius: 3px;
  font-family: var(--font-mono); flex-shrink: 0;
}
.xb-tele-call-cost { color: var(--txt2); font-family: var(--font-mono); flex-shrink: 0; }
.xb-tele-call-cache { color: var(--grn); font-size: 9px; flex-shrink: 0; }
.xb-tele-empty { font-size: 10px; color: var(--txt3); font-style: italic; }
`;

const TIER_BADGE_STYLES: Record<ComplexityTier, { bg: string; color: string }> = {
  TIER_S:  { bg: 'rgba(16,185,129,.1)',  color: '#10b981' },
  TIER_M:  { bg: 'rgba(0,212,255,.1)',   color: '#00d4ff' },
  TIER_L:  { bg: 'rgba(0,212,255,.08)',  color: '#00d4ff' },
  TIER_XL: { bg: 'rgba(168,85,247,.1)',  color: '#a855f7' },
};

interface TelemetryPanelDeps {
  consoleSM: ConsoleSM;
  uiStore:   UIStore;
}

export class InferenceTelemetryPanel {
  private readonly _deps:   TelemetryPanelDeps;
  private readonly _chart:  CostChart;
  private _el!:             HTMLElement;
  private _tele:            SessionTelemetry = emptyTelemetry();
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: TelemetryPanelDeps) {
    this._deps  = deps;
    this._chart = new CostChart();
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-tele';
    container.appendChild(this._el);

    // Update on every pass update
    this._unsubs.push(
      this._deps.consoleSM.subscribe(state => {
        if (state.name === 'Processing') {
          this._tele = state.telemetry;
          this._render();
        }
      }),
    );

    this._render();
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._chart.unmount();
    this._el?.remove();
  }

  private _render(): void {
    const t = this._tele;
    this._el.innerHTML = '';

    // Title
    const title = document.createElement('div');
    title.className = 'xb-tele-title';
    title.innerHTML = `▣ Inference Telemetry`;
    this._el.appendChild(title);

    // Session totals card
    const totals = document.createElement('div');
    totals.className = 'xb-tele-card';
    totals.innerHTML = `
      <div class="xb-tele-row">
        <span class="xb-tele-lbl">Session tokens</span>
        <span class="xb-tele-val">${formatTokens(t.total_input_tokens)}</span>
      </div>
      <div class="xb-tele-row">
        <span class="xb-tele-lbl">Est. cost</span>
        <span class="xb-tele-val" style="color:var(--grn)">${formatCost(t.total_cost_cents)}</span>
      </div>
      <div class="xb-tele-row">
        <span class="xb-tele-lbl">Cache hit</span>
        <span class="xb-tele-val" style="color:var(--cyan)">${Math.round(t.cache_hit_rate * 100)}%</span>
      </div>
      <div class="xb-tele-bar-wrap">
        <div class="xb-tele-bar-fill" style="width:${Math.round(t.cache_hit_rate * 100)}%"></div>
      </div>
      <div class="xb-tele-row">
        <span class="xb-tele-lbl">Tier dist.</span>
        <div class="xb-tele-tiers">
          <span class="xb-tele-tier" style="color:var(--grn)">S:${t.tier_counts.TIER_S}</span>
          <span class="xb-tele-tier" style="color:var(--cyan)">M:${t.tier_counts.TIER_M}</span>
          <span class="xb-tele-tier" style="color:var(--vlt)">XL:${t.tier_counts.TIER_XL}</span>
        </div>
      </div>
    `;
    this._el.appendChild(totals);

    // Cost chart
    const chartWrap = document.createElement('div');
    chartWrap.className = 'xb-tele-card';
    const chartLbl = document.createElement('div');
    chartLbl.style.cssText = 'font-size:8.5px;color:var(--txt3);margin-bottom:5px;text-transform:uppercase;letter-spacing:.08em';
    chartLbl.textContent   = 'Cost per mutation';
    chartWrap.appendChild(chartLbl);
    this._chart.mount(chartWrap);
    this._chart.update(t.calls);
    this._el.appendChild(chartWrap);

    // Per-call breakdown (last 8)
    const callCard = document.createElement('div');
    callCard.className = 'xb-tele-card';
    const callLbl = document.createElement('div');
    callLbl.style.cssText = 'font-size:8.5px;color:var(--txt3);margin-bottom:5px;text-transform:uppercase;letter-spacing:.08em';
    callLbl.textContent   = 'Recent calls';
    callCard.appendChild(callLbl);

    const recentCalls = t.calls.slice(-8).reverse();
    if (recentCalls.length === 0) {
      const empty = document.createElement('div');
      empty.className   = 'xb-tele-empty';
      empty.textContent = 'No calls yet.';
      callCard.appendChild(empty);
    } else {
      for (const call of recentCalls) {
        const tierStyle = TIER_BADGE_STYLES[call.tier as ComplexityTier] ?? TIER_BADGE_STYLES.TIER_M;
        const row = document.createElement('div');
        row.className = 'xb-tele-call';
        row.innerHTML = `
          <span class="xb-tele-call-lbl">${call.pass}</span>
          <span class="xb-tele-call-tier" style="background:${tierStyle.bg};color:${tierStyle.color}">${call.tier}</span>
          <span class="xb-tele-call-cost">${call.cost_cents.toFixed(2)}¢</span>
          ${call.cached ? '<span class="xb-tele-call-cache">hit</span>' : ''}
        `;
        callCard.appendChild(row);
      }
    }
    this._el.appendChild(callCard);
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-tele-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-tele-styles'; s.textContent = STYLES;
    document.head.appendChild(s);
  }
}