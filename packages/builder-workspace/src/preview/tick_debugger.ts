/**
 * tick_debugger.ts — Tick Debugger Panel
 *
 * Step-through tick debugger. In Phase 14 runs against CGS snapshots.
 * Phase 15: connects to engine pause/step over the engine_tick WebSocket.
 *
 * Shows:
 *   - Current tick counter (large mono)
 *   - ◀◀ ◀ ⏸ ▶ ▶▶ controls
 *   - Scrubber timeline bar
 *   - World hash (SHA256 of CGS state)
 *   - Events this tick (from CGS or engine)
 *   - Mutation queue log
 */

import { cgsStore }          from '../state/cgs_store';
import { uiStore }           from '../state/ui_store';
import type { BuilderClient } from '../api/builder_client';

type CGSStore = typeof cgsStore;
type UIStore = typeof uiStore;

const STYLES = `
.xb-dbg { flex: 1; overflow-y: auto; padding: 8px 9px; display: flex; flex-direction: column; gap: 6px; }
.xb-dbg-tick { font-family: var(--font-mono); font-size: 15px; color: var(--cyan); letter-spacing: .04em; }
.xb-dbg-ctrls { display: flex; gap: 4px; }
.xb-dbg-btn {
  font-size: 9.5px; padding: 2px 7px; border: 1px solid var(--bd); background: transparent;
  color: var(--txt2); border-radius: 3px; cursor: pointer; font-family: inherit; transition: all 100ms;
}
.xb-dbg-btn:hover { border-color: var(--bdh); color: var(--txt); }
.xb-dbg-btn.paused { border-color: rgba(0,212,255,.3); color: var(--cyan); background: var(--cynd); }
.xb-dbg-scrubber {
  height: 8px; background: rgba(255,255,255,.03); border: 1px solid var(--bd);
  border-radius: 3px; overflow: hidden; position: relative; cursor: pointer;
}
.xb-dbg-scrub-fill {
  height: 100%; background: linear-gradient(90deg, rgba(0,212,255,.15), rgba(168,85,247,.15));
  border-radius: 3px;
}
.xb-dbg-scrub-head {
  position: absolute; top: 0; bottom: 0; width: 2px; background: var(--cyan); border-radius: 2px;
  transition: left 200ms ease;
}
.xb-dbg-sect { font-size: 8.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--txt2); }
.xb-dbg-hash {
  font-family: var(--font-mono); font-size: 9px; color: var(--grn);
  background: rgba(16,185,129,.06); border: 1px solid rgba(16,185,129,.15);
  border-radius: 3px; padding: 4px 7px; word-break: break-all;
}
.xb-dbg-log {
  font-family: var(--font-mono); font-size: 9px; color: var(--txt2);
  background: rgba(0,0,0,.2); padding: 6px; border-radius: 4px; line-height: 1.8;
  max-height: 90px; overflow-y: auto;
}
.xb-dbg-log .ev-hit  { color: var(--red); }
.xb-dbg-log .ev-chg  { color: var(--amb); }
.xb-dbg-log .ev-mut  { color: var(--cyan); }
.xb-dbg-log .ev-chk  { color: var(--grn); }
`;

interface DebuggerDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
  client:   BuilderClient;
}

export class TickDebugger {
  private readonly _deps:    DebuggerDeps;
  private _el!:              HTMLElement;
  private _tick:             number  = 0;
  private _paused:           boolean = false;
  private _scrubPct:         number  = 85;
  private _tickInterval!:    ReturnType<typeof setInterval>;
  private readonly _unsubs:  Array<() => void>  = [];

  constructor(deps: DebuggerDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-dbg';
    container.appendChild(this._el);
    this._render();

    // Tick counter (simulated in Phase 14)
    this._tickInterval = setInterval(() => {
      if (!this._paused) {
        this._tick++;
        this._updateTick();
      }
    }, 16);
    this._unsubs.push(() => clearInterval(this._tickInterval));

    // Phase 15: use engine ticks
    this._unsubs.push(
      this._deps.client.onEngineTick((tick) => {
        this._tick = tick;
        this._updateTick();
      }),
    );

    // CGS hash changes
    this._unsubs.push(
      this._deps.cgsStore.select(s => s.hash, () => this._updateHash()),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    clearInterval(this._tickInterval);
    this._el?.remove();
  }

  private _render(): void {
    this._el.innerHTML = `
      <div class="xb-dbg-sect">Tick Debugger</div>

      <div class="xb-dbg-tick" id="xb-dbg-tick-val">0</div>

      <div class="xb-dbg-ctrls">
        <button class="xb-dbg-btn" id="xb-dbg-rew2" title="Jump back 100 ticks">◀◀</button>
        <button class="xb-dbg-btn" id="xb-dbg-rew1" title="Step back">◀</button>
        <button class="xb-dbg-btn" id="xb-dbg-pause" title="Pause / Resume">⏸</button>
        <button class="xb-dbg-btn" id="xb-dbg-fwd1" title="Step forward">▶</button>
        <button class="xb-dbg-btn" id="xb-dbg-fwd2" title="Jump forward 100 ticks">▶▶</button>
      </div>

      <div class="xb-dbg-scrubber" id="xb-dbg-scrub">
        <div class="xb-dbg-scrub-fill" style="width:${this._scrubPct}%"></div>
        <div class="xb-dbg-scrub-head" id="xb-dbg-scrub-head" style="left:${this._scrubPct}%"></div>
      </div>

      <div class="xb-dbg-sect">World Hash</div>
      <div class="xb-dbg-hash" id="xb-dbg-hash">${this._deps.cgsStore.hash || '0000000000000000'}</div>

      <div class="xb-dbg-sect">Events this tick</div>
      <div class="xb-dbg-log" id="xb-dbg-events">
        <span class="ev-hit">ENTITY_HIT Player→Zombie 15dmg</span><br>
        <span class="ev-chg">HEALTH_CHANGED Zombie 87→72</span><br>
        <span class="ev-chk">DEATH_CHECK Zombie alive:true</span>
      </div>

      <div class="xb-dbg-sect">Mutation Queue</div>
      <div class="xb-dbg-log" id="xb-dbg-mutations">
        <span class="ev-mut">MODIFY Zombie.COMP_HEALTH_V1.current→72</span><br>
        <span class="ev-mut">MODIFY Player.COMP_GAMESTATE.score+10</span>
      </div>
    `;

    // Bind controls
    document.getElementById('xb-dbg-rew2')?.addEventListener('click', () => {
      this._tick = Math.max(0, this._tick - 100); this._updateTick();
    });
    document.getElementById('xb-dbg-rew1')?.addEventListener('click', () => {
      this._tick = Math.max(0, this._tick - 1); this._updateTick();
    });
    document.getElementById('xb-dbg-pause')?.addEventListener('click', () => {
      this._paused = !this._paused;
      const btn = document.getElementById('xb-dbg-pause');
      btn?.classList.toggle('paused', this._paused);
      if (btn) btn.textContent = this._paused ? '▶' : '⏸';
    });
    document.getElementById('xb-dbg-fwd1')?.addEventListener('click', () => {
      this._tick++; this._updateTick();
    });
    document.getElementById('xb-dbg-fwd2')?.addEventListener('click', () => {
      this._tick += 100; this._updateTick();
    });

    // Scrubber click
    const scrub = document.getElementById('xb-dbg-scrub');
    scrub?.addEventListener('click', (e: MouseEvent) => {
      const rect = scrub.getBoundingClientRect();
      this._scrubPct = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
      const fill = scrub.querySelector<HTMLElement>('.xb-dbg-scrub-fill');
      const head = document.getElementById('xb-dbg-scrub-head');
      if (fill) fill.style.width   = `${this._scrubPct}%`;
      if (head) head.style.left    = `${this._scrubPct}%`;
    });
  }

  private _updateTick(): void {
    const el = document.getElementById('xb-dbg-tick-val');
    if (el) el.textContent = this._tick.toLocaleString();
  }

  private _updateHash(): void {
    const el = document.getElementById('xb-dbg-hash');
    if (el) el.textContent = this._deps.cgsStore.hash || '0000000000000000';
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-dbg-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-dbg-styles'; s.textContent = STYLES;
    document.head.appendChild(s);
  }
}
