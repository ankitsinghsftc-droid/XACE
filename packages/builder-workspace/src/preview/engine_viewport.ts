/**
 * engine_viewport.ts - Engine Viewport (right panel top slot)
 *
 * Phase 14.5: renders a lightweight CGS-driven game preview. This is not a
 * Unity/Unreal/Godot live viewport yet; it is the builder-side visual surface
 * that Phase 15 engine adapters can replace.
 */

import type { CGSStore } from '../state/cgs_store';
import type { UIStore } from '../state/ui_store';
import type { BuilderClient } from '../api/builder_client';

const STYLES = `
.xb-vp {
  position: relative;
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-bottom: 1px solid var(--bd);
  background: #060912;
}
.xb-vp-head {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 10;
  background: rgba(8,12,24,.88);
  backdrop-filter: blur(8px);
  padding: 5px 9px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--bd);
}
.xb-vp-title {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--txt2);
}
.xb-vp-ctrls {
  display: flex;
  gap: 3px;
  align-items: center;
}
.xb-vp-btn {
  height: 22px;
  min-width: 32px;
  padding: 0 7px;
  background: rgba(8,12,24,.7);
  border: 1px solid var(--bd);
  border-radius: 3px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 8.5px;
  color: var(--txt2);
  transition: all var(--tr-f);
  font-family: var(--font-mono);
}
.xb-vp-btn:hover { border-color: var(--cyan); color: var(--cyan); }
.xb-vp-btn.on { background: var(--cynd); border-color: var(--cyan); color: var(--cyan); }
.xb-vp-canvas-wrap {
  flex: 1;
  overflow: hidden;
  padding-top: 32px;
  position: relative;
}
.xb-vp-canvas {
  display: block;
  width: 100%;
  height: 100%;
}
.xb-vp-overlay {
  position: absolute;
  bottom: 7px;
  left: 7px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  pointer-events: none;
  z-index: 5;
}
.xb-vp-stat {
  font-family: var(--font-mono);
  font-size: 9px;
  background: rgba(8,12,24,.75);
  border: 1px solid var(--bd);
  border-radius: 3px;
  padding: 2px 6px;
  color: var(--txt2);
  display: flex;
  align-items: center;
  gap: 5px;
}
.xb-vp-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--grn);
  animation: pulse-dot 1.1s ease-in-out infinite;
  color: var(--grn);
  flex-shrink: 0;
}
.xb-vp-mode-badge {
  position: absolute;
  top: 36px;
  right: 7px;
  font-size: 8.5px;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(0,212,255,.08);
  border: 1px solid rgba(0,212,255,.15);
  color: var(--txt3);
  z-index: 5;
  pointer-events: none;
}
`;

interface ViewportDeps {
  cgsStore: CGSStore;
  uiStore: UIStore;
  client: BuilderClient;
}

interface PreviewActor {
  id: string;
  name: string;
  kind: 'player' | 'zombie' | 'actor';
  x: number;
  z: number;
  health: number;
  maxHealth: number;
  speed: number;
}

export class EngineViewport {
  private readonly _deps: ViewportDeps;
  private _el!: HTMLElement;
  private _canvas!: HTMLCanvasElement;
  private _ctx!: CanvasRenderingContext2D;
  private _running = true;
  private _engineMode = false;
  private _tickCount = 0;
  private _fps = 60;
  private _worldHash = '';
  private _lastFrame = 0;
  private _raf = 0;
  private _previewActors: PreviewActor[] = [];
  private _tickEl!: HTMLElement;
  private _fpsEl!: HTMLElement;
  private _hashEl!: HTMLElement | null;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: ViewportDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = this._build();
    container.appendChild(this._el);
    const ctx = this._canvas.getContext('2d');
    if (!ctx) return;
    this._ctx = ctx;
    this._wireReactive();
    this._resize();
    this._loop(0);
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    cancelAnimationFrame(this._raf);
    this._el?.remove();
  }

  private _switchToEngine(adapterType: string, _engineVersion: string): void {
    this._engineMode = true;
    const title = this._el.querySelector<HTMLElement>('.xb-vp-title');
    if (title) title.textContent = `${adapterType.toUpperCase()} Viewport`;

    const badge = this._el.querySelector<HTMLElement>('.xb-vp-mode-badge');
    if (badge) {
      badge.textContent = 'LIVE ENGINE';
      badge.style.color = 'var(--grn)';
      badge.style.background = 'rgba(16,185,129,.08)';
      badge.style.borderColor = 'rgba(16,185,129,.2)';
    }
  }

  private _build(): HTMLElement {
    const root = document.createElement('div');
    root.className = 'xb-vp';

    const head = document.createElement('div');
    head.className = 'xb-vp-head';

    const title = document.createElement('span');
    title.className = 'xb-vp-title';
    title.textContent = 'Engine Viewport';
    head.appendChild(title);

    const ctrls = document.createElement('div');
    ctrls.className = 'xb-vp-ctrls';
    const play = this._controlButton('PLAY', () => this._setRunning(true));
    const pause = this._controlButton('PAUSE', () => this._setRunning(false));
    const stop = this._controlButton('STOP', () => this._stopPreview());
    play.classList.add('on');
    ctrls.appendChild(play);
    ctrls.appendChild(pause);
    ctrls.appendChild(stop);
    head.appendChild(ctrls);
    root.appendChild(head);

    const badge = document.createElement('div');
    badge.className = 'xb-vp-mode-badge';
    badge.textContent = 'CGS PREVIEW';
    root.appendChild(badge);

    const wrap = document.createElement('div');
    wrap.className = 'xb-vp-canvas-wrap';
    this._canvas = document.createElement('canvas');
    this._canvas.className = 'xb-vp-canvas';
    wrap.appendChild(this._canvas);
    root.appendChild(wrap);

    const overlay = document.createElement('div');
    overlay.className = 'xb-vp-overlay';

    const liveStat = document.createElement('div');
    liveStat.className = 'xb-vp-stat';
    liveStat.innerHTML = `<div class="xb-vp-live-dot"></div>Tick <span id="xb-vp-tick" style="color:var(--cyan)">0</span>`;
    overlay.appendChild(liveStat);
    this._tickEl = liveStat.querySelector('#xb-vp-tick')!;

    const fpsStat = document.createElement('div');
    fpsStat.className = 'xb-vp-stat';
    fpsStat.innerHTML = `FPS <span id="xb-vp-fps" style="color:var(--grn)">60</span>`;
    overlay.appendChild(fpsStat);
    this._fpsEl = fpsStat.querySelector('#xb-vp-fps')!;

    const hashStat = document.createElement('div');
    hashStat.className = 'xb-vp-stat';
    hashStat.id = 'xb-vp-hash-stat';
    hashStat.style.display = 'none';
    hashStat.innerHTML = `Hash <span id="xb-vp-hash" style="font-size:8.5px;color:var(--grn)">-</span>`;
    overlay.appendChild(hashStat);
    this._hashEl = hashStat;

    root.appendChild(overlay);
    return root;
  }

  private _controlButton(label: string, onClick: () => void): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.className = 'xb-vp-btn';
    btn.textContent = label;
    btn.title = label;
    btn.addEventListener('click', () => {
      onClick();
      for (const item of this._el.querySelectorAll('.xb-vp-btn')) item.classList.remove('on');
      btn.classList.add('on');
    });
    return btn;
  }

  private _wireReactive(): void {
    const { cgsStore, uiStore, client } = this._deps;

    this._unsubs.push(
      cgsStore.subscribe(state => {
        this._worldHash = state.hash;
        this._previewActors = this._extractActors();
        const hashEl = document.getElementById('xb-vp-hash');
        if (hashEl) hashEl.textContent = state.hash ? state.hash.slice(0, 8) + '...' : '-';
        this._draw();
      }),
    );

    this._unsubs.push(
      uiStore.select(s => s.mode, mode => {
        const hashStat = document.getElementById('xb-vp-hash-stat');
        if (hashStat) hashStat.style.display = mode === 'ARCHITECT_MODE' ? 'flex' : 'none';
      }),
    );

    this._unsubs.push(
      client.onEngineTick((tick, fps, worldHash) => {
        this._tickCount = tick;
        this._fps = fps;
        this._worldHash = worldHash;
        if (this._tickEl) this._tickEl.textContent = tick.toLocaleString();
        if (this._fpsEl) {
          this._fpsEl.textContent = String(fps);
          this._fpsEl.style.color = fps < 55 ? 'var(--amb)' : 'var(--grn)';
        }
        const hashEl = document.getElementById('xb-vp-hash');
        if (hashEl) hashEl.textContent = worldHash.slice(0, 8) + '...';
        if (!this._engineMode) this._switchToEngine('engine', '');
      }),
    );

    const onResize = () => this._resize();
    window.addEventListener('resize', onResize);
    this._unsubs.push(() => window.removeEventListener('resize', onResize));
  }

  private _loop(now: number): void {
    const dt = this._lastFrame ? Math.min((now - this._lastFrame) / 1000, 0.05) : 0;
    this._lastFrame = now;
    if (this._running && !this._engineMode) {
      this._tickCount += 1;
      this._stepPreview(dt || 1 / 60);
      this._tickEl.textContent = this._tickCount.toLocaleString();
      this._fpsEl.textContent = String(this._fps);
    }
    this._draw();
    this._raf = requestAnimationFrame(t => this._loop(t));
  }

  private _setRunning(running: boolean): void {
    this._running = running;
  }

  private _stopPreview(): void {
    this._running = false;
    this._tickCount = 0;
    this._previewActors = this._extractActors();
    this._tickEl.textContent = '0';
    this._draw();
  }

  private _stepPreview(dt: number): void {
    const player = this._previewActors.find(a => a.kind === 'player') ?? this._previewActors[0];
    if (!player) return;
    for (const actor of this._previewActors) {
      if (actor.kind !== 'zombie') continue;
      const dx = player.x - actor.x;
      const dz = player.z - actor.z;
      const dist = Math.hypot(dx, dz) || 1;
      const step = Math.min(actor.speed * dt, dist);
      actor.x += (dx / dist) * step;
      actor.z += (dz / dist) * step;
    }
  }

  private _resize(): void {
    const rect = this._canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.floor(rect.width * dpr));
    const h = Math.max(1, Math.floor(rect.height * dpr));
    if (this._canvas.width !== w || this._canvas.height !== h) {
      this._canvas.width = w;
      this._canvas.height = h;
    }
    this._draw();
  }

  private _draw(): void {
    if (!this._ctx) return;
    const ctx = this._ctx;
    const w = this._canvas.width;
    const h = this._canvas.height;
    ctx.clearRect(0, 0, w, h);

    const grd = ctx.createLinearGradient(0, 0, 0, h);
    grd.addColorStop(0, '#07111e');
    grd.addColorStop(1, '#03050b');
    ctx.fillStyle = grd;
    ctx.fillRect(0, 0, w, h);

    this._drawGrid(ctx, w, h);
    this._drawActors(ctx, w, h);
    this._drawCaption(ctx, w, h);
  }

  private _drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    ctx.save();
    ctx.strokeStyle = 'rgba(0,212,255,.08)';
    ctx.lineWidth = 1;
    const step = Math.max(24, Math.floor(Math.min(w, h) / 10));
    for (let x = 0; x < w; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    ctx.restore();
  }

  private _drawActors(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const sx = w / 2;
    const sy = h / 2 + 12;
    const scale = Math.min(w, h) / 28;
    const player = this._previewActors.find(a => a.kind === 'player');

    if (player) {
      for (const actor of this._previewActors) {
        if (actor.kind !== 'zombie') continue;
        ctx.strokeStyle = 'rgba(239,68,68,.28)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(sx + actor.x * scale, sy + actor.z * scale);
        ctx.lineTo(sx + player.x * scale, sy + player.z * scale);
        ctx.stroke();
      }
    }

    for (const actor of this._previewActors) {
      const x = sx + actor.x * scale;
      const y = sy + actor.z * scale;
      const radius = actor.kind === 'player' ? 8 : 7;
      ctx.fillStyle = actor.kind === 'player' ? '#00d4ff' : '#ef4444';
      ctx.strokeStyle = actor.kind === 'player' ? 'rgba(0,212,255,.8)' : 'rgba(239,68,68,.8)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      const hpPct = actor.maxHealth > 0 ? Math.max(0, Math.min(1, actor.health / actor.maxHealth)) : 1;
      ctx.fillStyle = 'rgba(0,0,0,.55)';
      ctx.fillRect(x - 14, y - 18, 28, 3);
      ctx.fillStyle = hpPct > .35 ? '#22c55e' : '#f59e0b';
      ctx.fillRect(x - 14, y - 18, 28 * hpPct, 3);
    }
  }

  private _drawCaption(ctx: CanvasRenderingContext2D, _w: number, h: number): void {
    ctx.save();
    ctx.font = `${10 * (window.devicePixelRatio || 1)}px monospace`;
    ctx.fillStyle = 'rgba(200,211,245,.65)';
    ctx.fillText('builder CGS preview - live engine adapter pending', 10, h - 12);
    ctx.restore();
  }

  private _extractActors(): PreviewActor[] {
    const actors: PreviewActor[] = [];
    const cgs = this._deps.cgsStore.cgs as any;
    for (const mode of cgs.modes ?? []) {
      for (const actor of mode.actors ?? []) {
        const transform = _component(actor, 'COMP_TRANSFORM_V1')?.defaults ?? {};
        const health = _component(actor, 'COMP_HEALTH_V1')?.defaults ?? {};
        const velocity = _component(actor, 'COMP_VELOCITY_V1')?.defaults ?? {};
        const identity = _component(actor, 'COMP_IDENTITY_V1')?.defaults ?? {};
        const kind = actor.control_type === 'Human'
          ? 'player'
          : actor.actor_type === 'Enemy' ? 'zombie' : 'actor';
        actors.push({
          id: actor.id ?? '',
          name: identity.name ?? actor.id ?? 'Actor',
          kind,
          x: Number(transform.position_x ?? 0),
          z: Number(transform.position_z ?? 0),
          health: Number(health.current ?? 1),
          maxHealth: Number(health.max ?? health.current ?? 1),
          speed: Number(velocity.max_linear_speed ?? 1),
        });
      }
    }
    return actors;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-vp-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-vp-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}

function _component(actor: any, name: string): any | undefined {
  return (actor.components ?? []).find((comp: any) => comp.name === name);
}
