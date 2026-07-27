/**
 * Live runtime statistics panel.
 *
 * This view is read-only: it derives metrics from CGS and builder protocol
 * messages, then renders bounded history for deterministic inspection.
 */

import type { BuilderClient, ConnectionState } from '../api/builder_client';
import type { EngineTickMessage } from '../api/message_types';
import type { CGSStore } from '../state/cgs_store';
import type { UIStore } from '../state/ui_store';
import { allSystems } from '../types/cgs';

const MAX_SAMPLES = 180;
const MAX_SYSTEM_ROWS = 12;
const STATUS_POLL_MS = 1000;

const STYLES = `
.xb-rts { flex: 1; overflow-y: auto; padding: 8px 9px; display: flex; flex-direction: column; gap: 7px; min-height: 0; }
.xb-rts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.xb-rts-stat { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.xb-rts-lbl { font-size: 8px; color: var(--txt2); letter-spacing: .06em; text-transform: uppercase; }
.xb-rts-val { font-family: var(--font-mono); font-size: 13px; font-weight: 500; color: var(--txt); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-rts-val.cyan { color: var(--cyan); }
.xb-rts-val.warn { color: var(--amb); }
.xb-rts-val.good { color: var(--grn); }
.xb-rts-val.bad { color: var(--red); }
.xb-rts-ekg { width: 100%; height: 30px; border: 1px solid var(--bd); border-radius: 3px; background: rgba(0,0,0,.2); display: block; }
.xb-rts-sect { font-size: 8.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--txt2); margin-top: 2px; }
.xb-rts-row { display: grid; grid-template-columns: minmax(0,1fr) 66px 46px; align-items: center; gap: 6px; font-size: 9.5px; min-width: 0; }
.xb-rts-name { color: var(--txt2); font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-rts-bar-wrap { width: 66px; height: 3px; background: rgba(255,255,255,.04); border-radius: 2px; overflow: hidden; }
.xb-rts-bar { height: 100%; border-radius: 2px; transition: width 180ms ease; background: var(--cyan); display: block; }
.xb-rts-num { font-family: var(--font-mono); font-size: 9px; color: var(--amb); text-align: right; }
.xb-rts-note { font-size: 9.5px; color: var(--txt3); line-height: 1.5; overflow-wrap: anywhere; }
`;

interface StatsDeps {
  cgsStore: CGSStore;
  uiStore: UIStore;
  client: BuilderClient;
}

interface RuntimeSample {
  readonly tick: number;
  readonly fps: number;
  readonly msPerTick: number;
  readonly entityCount: number;
  readonly worldHash: string;
  readonly deterministic: boolean;
  readonly adapterType: string;
  readonly systemTimings: ReadonlyMap<string, number>;
}

export class RuntimeStats {
  private readonly deps: StatsDeps;
  private readonly samples: RuntimeSample[] = [];
  private readonly unsubs: Array<() => void> = [];

  private root: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private connectionState: ConnectionState = 'disconnected';
  private runtimeError = '';
  private statusTimer: ReturnType<typeof setInterval> | null = null;

  constructor(deps: StatsDeps) {
    this.deps = deps;
    injectStyles();
  }

  mount(container: HTMLElement): void {
    this.root = document.createElement('div');
    this.root.className = 'xb-rts';
    container.appendChild(this.root);

    this.unsubs.push(this.deps.cgsStore.subscribe(() => this.render()));
    this.unsubs.push(this.deps.client.onConnectionState((state) => {
      this.connectionState = state;
      this.render();
    }));
    this.unsubs.push(this.deps.client.onRuntimeStatus((status) => {
      this.runtimeError = status.lastError;
      this.render();
    }));
    this.unsubs.push(this.deps.client.onEngineTick((_tick, _fps, _hash, _ms, message) => {
      this.acceptTick(message);
    }));
    this.statusTimer = setInterval(() => {
      if (this.deps.client.isConnected) {
        this.deps.client.requestRuntimeStatus();
      }
    }, STATUS_POLL_MS);
    if (this.deps.client.isConnected) {
      this.deps.client.requestRuntimeStatus();
    }
    this.render();
  }

  unmount(): void {
    this.unsubs.splice(0).forEach((unsub) => unsub());
    if (this.statusTimer) {
      clearInterval(this.statusTimer);
      this.statusTimer = null;
    }
    this.root?.remove();
    this.root = null;
    this.canvas = null;
  }

  private acceptTick(message: EngineTickMessage): void {
    const sample: RuntimeSample = {
      tick: safeNumber(message.tick, 0),
      fps: safeNumber(message.fps, 0),
      msPerTick: safeNumber(message.ms_per_tick, 0),
      entityCount: Math.max(0, Math.floor(safeNumber(message.entity_count, 0))),
      worldHash: message.world_hash || '',
      deterministic: message.is_deterministic,
      adapterType: message.adapter_type ?? this.deps.client.runtimeStatus.adapterType,
      systemTimings: normalizeTimings(message.system_timings),
    };
    this.samples.push(sample);
    if (this.samples.length > MAX_SAMPLES) {
      this.samples.splice(0, this.samples.length - MAX_SAMPLES);
    }
    this.render();
  }

  private render(): void {
    if (!this.root) {
      return;
    }

    const latest = this.samples[this.samples.length - 1] ?? null;
    const actors = latest?.entityCount ?? this.deps.cgsStore.actorCount;
    const systems = this.deps.cgsStore.systemCount;
    const fps = latest?.fps ?? 0;
    const msPerTick = latest?.msPerTick ?? 0;
    const hash = latest?.worldHash || this.deps.cgsStore.hash || '';
    const deterministic = latest?.deterministic ?? true;
    const runtime = this.deps.client.runtimeStatus;
    const connected = runtime.connected;
    const adapter = latest?.adapterType || runtime.adapterType || 'headless';
    const controlTick = runtime.controlTick || latest?.tick || 0;
    const feedbackBad = runtime.lastEngineFeedbackInvalid + runtime.lastEngineFeedbackErrors;

    this.root.innerHTML = `
      <div class="xb-rts-grid">
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Connection</div><div class="xb-rts-val ${connected ? 'good' : 'warn'}">${escapeHtml(this.connectionState)}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Adapter</div><div class="xb-rts-val">${escapeHtml(adapter)}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Tick</div><div class="xb-rts-val cyan">${controlTick ? controlTick.toLocaleString() : '-'}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">FPS</div><div class="xb-rts-val ${fps >= 55 ? 'good' : fps > 0 ? 'warn' : ''}">${latest ? fps.toFixed(0) : '-'}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">ms / tick</div><div class="xb-rts-val ${msPerTick > 20 ? 'warn' : ''}">${latest ? msPerTick.toFixed(2) : '-'}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Entities</div><div class="xb-rts-val">${actors.toLocaleString()}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Systems</div><div class="xb-rts-val">${systems.toLocaleString()}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Determinism</div><div class="xb-rts-val ${deterministic ? 'good' : 'bad'}">${deterministic ? 'locked' : 'breach'}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Run state</div><div class="xb-rts-val ${runtime.paused ? 'warn' : 'good'}">${runtime.paused ? 'paused' : 'running'}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Step budget</div><div class="xb-rts-val">${runtime.stepBudget.toLocaleString()}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Pending input</div><div class="xb-rts-val">${runtime.pendingEngineInputs.toLocaleString()}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Pending feedback</div><div class="xb-rts-val">${runtime.pendingEngineFeedback.toLocaleString()}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Feedback handled</div><div class="xb-rts-val ${runtime.lastEngineFeedbackProcessed > 0 ? 'good' : ''}">${runtime.lastEngineFeedbackProcessed.toLocaleString()}</div></div>
        <div class="xb-rts-stat"><div class="xb-rts-lbl">Feedback issues</div><div class="xb-rts-val ${feedbackBad > 0 ? 'bad' : 'good'}">${feedbackBad.toLocaleString()}</div></div>
      </div>
      <canvas class="xb-rts-ekg" width="280" height="30"></canvas>
      <div class="xb-rts-sect">System timings</div>
      <div data-role="systems"></div>
      <div class="xb-rts-sect">World hash</div>
      <div class="xb-rts-note">${hash ? escapeHtml(hash) : 'No runtime hash yet.'}</div>
      ${this.runtimeError ? `<div class="xb-rts-sect">Last error</div><div class="xb-rts-note">${escapeHtml(this.runtimeError)}</div>` : ''}
    `;

    this.canvas = this.root.querySelector<HTMLCanvasElement>('.xb-rts-ekg');
    this.renderChart();
    this.renderSystems(latest);
  }

  private renderSystems(latest: RuntimeSample | null): void {
    const host = this.root?.querySelector<HTMLElement>('[data-role="systems"]');
    if (!host) {
      return;
    }

    const rows = latest && latest.systemTimings.size > 0
      ? Array.from(latest.systemTimings.entries()).sort(([a], [b]) => a.localeCompare(b))
      : allSystems(this.deps.cgsStore.cgs).map(({ system }) => [system.id, 0] as [string, number]);

    if (rows.length === 0) {
      host.innerHTML = '<div class="xb-rts-note">No systems defined.</div>';
      return;
    }

    const max = Math.max(1, ...rows.map(([, value]) => value));
    host.innerHTML = '';
    for (const [name, ms] of rows.slice(0, MAX_SYSTEM_ROWS)) {
      const row = document.createElement('div');
      row.className = 'xb-rts-row';
      const pct = Math.max(2, Math.min(100, (ms / max) * 100));
      row.innerHTML = `
        <span class="xb-rts-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
        <span class="xb-rts-bar-wrap"><span class="xb-rts-bar" style="width:${pct.toFixed(2)}%"></span></span>
        <span class="xb-rts-num">${ms.toFixed(2)}ms</span>
      `;
      host.appendChild(row);
    }
  }

  private renderChart(): void {
    const ctx = this.canvas?.getContext('2d');
    const canvas = this.canvas;
    if (!ctx || !canvas) {
      return;
    }

    const width = canvas.width;
    const height = canvas.height;
    const values = this.samples.map((sample) => sample.msPerTick);
    ctx.clearRect(0, 0, width, height);

    ctx.strokeStyle = 'rgba(255,255,255,.08)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, height - 8);
    ctx.lineTo(width, height - 8);
    ctx.stroke();

    if (values.length === 0) {
      return;
    }

    const max = Math.max(16.667, ...values);
    ctx.strokeStyle = 'rgba(0,212,255,.78)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    values.forEach((value, index) => {
      const x = values.length === 1 ? width : (index / (values.length - 1)) * width;
      const y = height - Math.min(height - 2, (value / max) * (height - 3)) - 1;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
}

function normalizeTimings(input: Record<string, number>): ReadonlyMap<string, number> {
  const timings = new Map<string, number>();
  for (const [name, value] of Object.entries(input ?? {})) {
    const ms = safeNumber(value, 0);
    timings.set(name, Math.max(0, ms));
  }
  return timings;
}

function safeNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function injectStyles(): void {
  if (document.getElementById('xb-rts-styles')) return;
  const style = document.createElement('style');
  style.id = 'xb-rts-styles';
  style.textContent = STYLES;
  document.head.appendChild(style);
}

function escapeHtml(value: string): string {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
}
