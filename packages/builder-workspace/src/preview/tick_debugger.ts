/**
 * Deterministic tick debugger for the live builder preview.
 */

import type { BuilderClient, RuntimeStatus } from '../api/builder_client';
import type { RuntimeControlAction, ServerMessage } from '../api/message_types';
import { makeRuntimeControl } from '../api/message_types';
import type { CGSStore } from '../state/cgs_store';
import type { UIStore } from '../state/ui_store';

const MAX_HISTORY = 96;
const MAX_EVENTS = 20;

const STYLES = `
.xb-dbg { flex: 1; overflow-y: auto; padding: 8px 9px; display: flex; flex-direction: column; gap: 7px; min-height: 0; }
.xb-dbg-tick { font-family: var(--font-mono); font-size: 16px; color: var(--cyan); letter-spacing: .04em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-dbg-ctrls { display: flex; gap: 4px; flex-wrap: wrap; }
.xb-dbg-btn {
  font-size: 9.5px; padding: 3px 8px; border: 1px solid var(--bd); background: transparent;
  color: var(--txt2); border-radius: 3px; cursor: pointer; font-family: inherit; transition: all 100ms;
}
.xb-dbg-btn:hover { border-color: var(--bdh); color: var(--txt); }
.xb-dbg-btn.active { border-color: rgba(0,212,255,.35); color: var(--cyan); background: var(--cynd); }
.xb-dbg-scrubber { height: 8px; background: rgba(255,255,255,.03); border: 1px solid var(--bd); border-radius: 3px; overflow: hidden; position: relative; }
.xb-dbg-scrub-fill { height: 100%; background: linear-gradient(90deg, rgba(0,212,255,.18), rgba(168,85,247,.18)); border-radius: 3px; }
.xb-dbg-sect { font-size: 8.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--txt2); }
.xb-dbg-box {
  font-family: var(--font-mono); font-size: 9px; color: var(--txt2);
  background: rgba(0,0,0,.2); border: 1px solid rgba(255,255,255,.05);
  padding: 6px; border-radius: 4px; line-height: 1.7; max-height: 118px; overflow-y: auto;
}
.xb-dbg-hash { color: var(--grn); word-break: break-all; }
.xb-dbg-warn { color: var(--amb); }
.xb-dbg-bad { color: var(--red); }
`;

interface DebuggerDeps {
  cgsStore: CGSStore;
  uiStore: UIStore;
  client: BuilderClient;
}

interface TickRecord {
  readonly tick: number;
  readonly worldHash: string;
  readonly msPerTick: number;
  readonly deterministic: boolean;
}

interface DebugEvent {
  readonly tick: number;
  readonly level: 'info' | 'warn' | 'error';
  readonly text: string;
}

export class TickDebugger {
  private readonly deps: DebuggerDeps;
  private readonly history: TickRecord[] = [];
  private readonly events: DebugEvent[] = [];
  private readonly unsubs: Array<() => void> = [];

  private root: HTMLElement | null = null;
  private tick = 0;
  private requestedMode: 'play' | 'pause' = 'play';
  private lastHash = '';
  private runtimeStatus: RuntimeStatus | null = null;

  constructor(deps: DebuggerDeps) {
    this.deps = deps;
    injectStyles();
  }

  mount(container: HTMLElement): void {
    this.root = document.createElement('div');
    this.root.className = 'xb-dbg';
    container.appendChild(this.root);

    this.unsubs.push(this.deps.cgsStore.select((state) => state.hash, (hash) => {
      this.lastHash = hash || this.lastHash;
      this.render();
    }));
    this.unsubs.push(this.deps.client.onEngineTick((tick, _fps, worldHash, msPerTick, message) => {
      this.acceptTick({
        tick,
        worldHash,
        msPerTick,
        deterministic: message.is_deterministic,
      });
    }));
    this.unsubs.push(this.deps.client.onRawMessage((message) => this.acceptServerMessage(message)));
    this.unsubs.push(this.deps.client.onRuntimeStatus((status) => {
      this.runtimeStatus = status;
      if (status.controlTick > this.tick) {
        this.tick = status.controlTick;
      }
      this.render();
    }));
    this.render();
  }

  unmount(): void {
    this.unsubs.splice(0).forEach((unsub) => unsub());
    this.root?.remove();
    this.root = null;
  }

  private acceptTick(record: TickRecord): void {
    this.tick = record.tick;
    this.lastHash = record.worldHash || this.lastHash;
    this.history.push(record);
    if (this.history.length > MAX_HISTORY) {
      this.history.splice(0, this.history.length - MAX_HISTORY);
    }
    if (!record.deterministic) {
      this.pushEvent('error', `determinism breach at tick ${record.tick}`);
    }
    this.render();
  }

  private acceptServerMessage(message: ServerMessage): void {
    if (message.type === 'runtime_control_ack') {
      this.pushEvent(
        message.accepted ? 'info' : 'warn',
        `${message.action} ${message.accepted ? 'accepted' : message.reason ?? 'rejected'}`,
      );
      return;
    }
    if (message.type === 'server_error') {
      this.pushEvent('error', `${message.code}: ${message.message}`);
      return;
    }
    if (message.type === 'engine_disconnected') {
      this.pushEvent('warn', `engine disconnected: ${message.reason}`);
    }
  }

  private render(): void {
    if (!this.root) {
      return;
    }

    const latest = this.history[this.history.length - 1] ?? null;
    const hash = latest?.worldHash || this.lastHash || '0'.repeat(64);
    const pct = this.history.length <= 1 ? 0 : (this.history.length / MAX_HISTORY) * 100;
    const deterministic = latest?.deterministic ?? true;
    const status = this.runtimeStatus ?? this.deps.client.runtimeStatus;
    const feedbackIssues = status.lastEngineFeedbackInvalid + status.lastEngineFeedbackErrors;

    this.root.innerHTML = `
      <div class="xb-dbg-sect">Tick debugger</div>
      <div class="xb-dbg-tick">${this.tick.toLocaleString()}</div>
      <div class="xb-dbg-ctrls">
        <button class="xb-dbg-btn ${this.requestedMode === 'play' ? 'active' : ''}" data-action="play">Play</button>
        <button class="xb-dbg-btn ${this.requestedMode === 'pause' ? 'active' : ''}" data-action="pause">Pause</button>
        <button class="xb-dbg-btn" data-action="step">Step</button>
        <button class="xb-dbg-btn" data-action="reset">Reset</button>
        <button class="xb-dbg-btn" data-action="reload_cgs">Reload CGS</button>
      </div>
      <div class="xb-dbg-scrubber"><div class="xb-dbg-scrub-fill" style="width:${Math.min(100, pct).toFixed(2)}%"></div></div>
      <div class="xb-dbg-sect">Determinism</div>
      <div class="xb-dbg-box ${deterministic ? '' : 'xb-dbg-bad'}">${deterministic ? 'locked' : 'breach detected'}</div>
      <div class="xb-dbg-sect">World hash</div>
      <div class="xb-dbg-box xb-dbg-hash">${escapeHtml(hash)}</div>
      <div class="xb-dbg-sect">Runtime bridge</div>
      <div class="xb-dbg-box">
        state: <span class="${status.paused ? 'xb-dbg-warn' : ''}">${status.paused ? 'paused' : 'running'}</span><br>
        alive: ${status.aliveCount.toLocaleString()} | phases: ${status.phaseCount.toLocaleString()} | systems: ${status.registeredSystems.toLocaleString()}<br>
        pending input: ${status.pendingEngineInputs.toLocaleString()} | pending feedback: ${status.pendingEngineFeedback.toLocaleString()}<br>
        feedback handled: ${status.lastEngineFeedbackProcessed.toLocaleString()} | issues: <span class="${feedbackIssues > 0 ? 'xb-dbg-bad' : ''}">${feedbackIssues.toLocaleString()}</span>
      </div>
      <div class="xb-dbg-sect">Recent ticks</div>
      <div class="xb-dbg-box">${this.renderHistory()}</div>
      <div class="xb-dbg-sect">Events</div>
      <div class="xb-dbg-box">${this.renderEvents()}</div>
    `;

    this.root.querySelectorAll<HTMLButtonElement>('[data-action]').forEach((button) => {
      button.addEventListener('click', () => {
        const action = button.dataset['action'] as RuntimeControlAction;
        this.sendControl(action);
      });
    });
  }

  private renderHistory(): string {
    if (this.history.length === 0) {
      return 'No engine ticks received.';
    }
    return this.history
      .slice(-10)
      .map((item) => {
        const status = item.deterministic ? 'ok' : 'breach';
        const cls = item.deterministic ? '' : ' class="xb-dbg-bad"';
        return `<span${cls}>#${item.tick} ${item.msPerTick.toFixed(2)}ms ${status} ${escapeHtml(item.worldHash.slice(0, 14))}</span>`;
      })
      .join('<br>');
  }

  private renderEvents(): string {
    if (this.events.length === 0) {
      return 'No control events yet.';
    }
    return this.events
      .slice(-8)
      .map((event) => {
        const cls = event.level === 'error' ? 'xb-dbg-bad' : event.level === 'warn' ? 'xb-dbg-warn' : '';
        return `<span class="${cls}">#${event.tick} ${escapeHtml(event.text)}</span>`;
      })
      .join('<br>');
  }

  private sendControl(action: RuntimeControlAction): void {
    if (action === 'play' || action === 'pause') {
      this.requestedMode = action;
    }
    this.deps.client.send(makeRuntimeControl(action, this.deps.client.sessionId, this.tick));
    this.pushEvent('info', `sent ${action}`);
    this.render();
  }

  private pushEvent(level: DebugEvent['level'], text: string): void {
    this.events.push({ tick: this.tick, level, text });
    if (this.events.length > MAX_EVENTS) {
      this.events.splice(0, this.events.length - MAX_EVENTS);
    }
  }
}

function injectStyles(): void {
  if (document.getElementById('xb-dbg-styles')) return;
  const style = document.createElement('style');
  style.id = 'xb-dbg-styles';
  style.textContent = STYLES;
  document.head.appendChild(style);
}

function escapeHtml(value: string): string {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
}
