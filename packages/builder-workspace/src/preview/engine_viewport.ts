/**
 * Embedded engine viewport surface.
 *
 * Native Unity/Godot/Unreal views can be embedded later. For now this canvas
 * is a deterministic CGS mirror with live runtime status, explicit runtime
 * controls, and entity selection routed through the builder protocol.
 */

import type { BuilderClient } from '../api/builder_client';
import { makeEngineEdit, makeRuntimeControl } from '../api/message_types';
import type { EngineTickMessage, RuntimeEntityState } from '../api/message_types';
import type { CGSStore } from '../state/cgs_store';
import type { UIStore } from '../state/ui_store';
import { allActors } from '../types/cgs';

const STYLES = `
.xb-vp { position: relative; flex: 1; overflow: hidden; display: flex; flex-direction: column; min-height: 0; border-bottom: 1px solid var(--bd); background: #060912; }
.xb-vp-head { position: absolute; top: 0; left: 0; right: 0; z-index: 10; background: rgba(8,12,24,.88); backdrop-filter: blur(8px); padding: 5px 9px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--bd); gap: 8px; }
.xb-vp-title { font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--txt2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-vp-ctrls { display: flex; gap: 3px; align-items: center; flex-shrink: 0; }
.xb-vp-btn { height: 22px; min-width: 34px; padding: 0 7px; background: rgba(8,12,24,.7); border: 1px solid var(--bd); border-radius: 3px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 8.5px; color: var(--txt2); transition: all var(--tr-f); font-family: var(--font-mono); }
.xb-vp-btn:hover { border-color: var(--cyan); color: var(--cyan); }
.xb-vp-btn.on { background: var(--cynd); border-color: var(--cyan); color: var(--cyan); }
.xb-vp-canvas-wrap { flex: 1; overflow: hidden; padding-top: 32px; position: relative; min-height: 0; }
.xb-vp-canvas { display: block; width: 100%; height: 100%; cursor: crosshair; }
.xb-vp-overlay { position: absolute; bottom: 7px; left: 7px; display: flex; flex-direction: column; gap: 3px; pointer-events: none; z-index: 5; max-width: calc(100% - 14px); }
.xb-vp-stat { font-family: var(--font-mono); font-size: 9px; background: rgba(8,12,24,.75); border: 1px solid var(--bd); border-radius: 3px; padding: 2px 6px; color: var(--txt2); display: flex; align-items: center; gap: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-vp-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--amb); flex-shrink: 0; }
.xb-vp-dot.live { background: var(--grn); animation: pulse-dot 1.1s ease-in-out infinite; }
.xb-vp-badge { position: absolute; top: 36px; right: 7px; font-size: 8.5px; padding: 2px 6px; border-radius: 3px; background: rgba(0,212,255,.08); border: 1px solid rgba(0,212,255,.15); color: var(--txt3); z-index: 5; pointer-events: none; }
`;

interface ViewportDeps {
  cgsStore: CGSStore;
  uiStore: UIStore;
  client: BuilderClient;
}

interface PreviewActor {
  readonly id: string;
  readonly modeId: string;
  readonly label: string;
  readonly kind: 'player' | 'enemy' | 'actor';
  x: number;
  z: number;
  readonly health: number;
  readonly maxHealth: number;
  readonly speed: number;
}

export class EngineViewport {
  private readonly deps: ViewportDeps;
  private readonly unsubs: Array<() => void> = [];

  private root: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private actors: PreviewActor[] = [];
  private running = true;
  private liveEngine = false;
  private tick = 0;
  private fps = 60;
  private worldHash = '';
  private lastFrame = 0;
  private raf = 0;

  constructor(deps: ViewportDeps) {
    this.deps = deps;
    injectStyles();
  }

  mount(container: HTMLElement): void {
    this.root = this.build();
    container.appendChild(this.root);
    this.canvas = this.root.querySelector<HTMLCanvasElement>('.xb-vp-canvas');
    this.ctx = this.canvas?.getContext('2d') ?? null;
    this.actors = this.extractActors();
    this.wire();
    this.resize();
    this.loop(0);
  }

  unmount(): void {
    this.unsubs.splice(0).forEach((unsub) => unsub());
    this.resizeObserver?.disconnect();
    cancelAnimationFrame(this.raf);
    this.root?.remove();
    this.root = null;
    this.canvas = null;
    this.ctx = null;
  }

  private build(): HTMLElement {
    const root = document.createElement('div');
    root.className = 'xb-vp';
    root.innerHTML = `
      <div class="xb-vp-head">
        <span class="xb-vp-title">Engine Viewport</span>
        <div class="xb-vp-ctrls">
          <button class="xb-vp-btn on" data-action="play">PLAY</button>
          <button class="xb-vp-btn" data-action="pause">PAUSE</button>
          <button class="xb-vp-btn" data-action="step">STEP</button>
          <button class="xb-vp-btn" data-action="reset">RESET</button>
        </div>
      </div>
      <div class="xb-vp-badge">CGS PREVIEW</div>
      <div class="xb-vp-canvas-wrap"><canvas class="xb-vp-canvas"></canvas></div>
      <div class="xb-vp-overlay">
        <div class="xb-vp-stat"><span class="xb-vp-dot"></span><span data-role="tick">Tick 0</span></div>
        <div class="xb-vp-stat" data-role="fps">FPS 60</div>
        <div class="xb-vp-stat" data-role="hash">Hash -</div>
      </div>
    `;
    return root;
  }

  private wire(): void {
    this.root?.querySelectorAll<HTMLButtonElement>('[data-action]').forEach((button) => {
      button.addEventListener('click', () => {
        const action = button.dataset['action'] as 'play' | 'pause' | 'step' | 'reset';
        this.handleControl(action);
      });
    });

    this.canvas?.addEventListener('click', (event) => this.selectActorAt(event, false));
    this.canvas?.addEventListener('dblclick', (event) => this.selectActorAt(event, true));

    this.unsubs.push(this.deps.cgsStore.subscribe((state) => {
      this.worldHash = state.hash || this.worldHash;
      this.actors = this.extractActors();
      this.draw();
      this.renderOverlay();
    }));
    this.unsubs.push(this.deps.uiStore.select((state) => state.selectedEntity?.id ?? '', () => this.draw()));
    this.unsubs.push(this.deps.client.onRuntimeStatus((status) => {
      this.liveEngine = status.connected;
      const badge = this.root?.querySelector<HTMLElement>('.xb-vp-badge');
      if (badge) {
        badge.textContent = status.connected ? `${status.adapterType || 'ENGINE'} LIVE` : 'CGS PREVIEW';
      }
      this.root?.querySelector('.xb-vp-dot')?.classList.toggle('live', status.connected);
    }));
    this.unsubs.push(this.deps.client.onEngineTick((tick, fps, worldHash, _msPerTick, message) => {
      this.tick = tick;
      this.fps = fps;
      this.worldHash = worldHash;
      if (message.entities && message.entities.length > 0) {
        this.liveEngine = true;
        this.actors = this.extractRuntimeActors(message);
      }
      this.renderOverlay();
      this.draw();
    }));

    if (typeof ResizeObserver !== 'undefined' && this.canvas) {
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.canvas);
    } else {
      const onResize = () => this.resize();
      window.addEventListener('resize', onResize);
      this.unsubs.push(() => window.removeEventListener('resize', onResize));
    }
  }

  private handleControl(action: 'play' | 'pause' | 'step' | 'reset'): void {
    if (action === 'play') this.running = true;
    if (action === 'pause') this.running = false;
    if (action === 'reset') {
      this.tick = 0;
      this.actors = this.extractActors();
    }
    if (action === 'step' && !this.liveEngine) {
      this.stepPreview(1 / 60);
      this.tick += 1;
    }
    this.deps.client.send(makeRuntimeControl(action, this.deps.client.sessionId, this.tick));
    this.root?.querySelectorAll('.xb-vp-btn').forEach((item) => item.classList.remove('on'));
    const active = action === 'step' ? (this.running ? 'play' : 'pause') : action;
    this.root?.querySelector(`[data-action="${active}"]`)?.classList.add('on');
    this.renderOverlay();
    this.draw();
  }

  private loop(now: number): void {
    const dt = this.lastFrame ? Math.min((now - this.lastFrame) / 1000, 0.05) : 1 / 60;
    this.lastFrame = now;
    if (this.running && !this.liveEngine) {
      this.tick += 1;
      this.stepPreview(dt);
      this.renderOverlay();
    }
    this.draw();
    this.raf = requestAnimationFrame((time) => this.loop(time));
  }

  private stepPreview(dt: number): void {
    const player = this.actors.find((actor) => actor.kind === 'player') ?? this.actors[0];
    if (!player) {
      return;
    }
    for (const actor of this.actors) {
      if (actor.kind !== 'enemy') continue;
      const dx = player.x - actor.x;
      const dz = player.z - actor.z;
      const dist = Math.hypot(dx, dz) || 1;
      const step = Math.min(actor.speed * dt, dist);
      actor.x += (dx / dist) * step;
      actor.z += (dz / dist) * step;
    }
  }

  private resize(): void {
    if (!this.canvas) {
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    this.canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    this.draw();
  }

  private draw(): void {
    if (!this.ctx || !this.canvas) {
      return;
    }
    const ctx = this.ctx;
    const width = this.canvas.width;
    const height = this.canvas.height;
    ctx.clearRect(0, 0, width, height);

    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, '#07111e');
    gradient.addColorStop(1, '#03050b');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);

    this.drawGrid(ctx, width, height);
    this.drawActors(ctx, width, height);
    if (this.actors.length === 0) {
      this.drawEmpty(ctx, width, height);
    }
  }

  private drawGrid(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    ctx.strokeStyle = 'rgba(0,212,255,.08)';
    ctx.lineWidth = 1;
    const step = Math.max(24, Math.floor(Math.min(width, height) / 10));
    for (let x = 0; x < width; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y < height; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
  }

  private drawActors(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    const selectedId = this.deps.uiStore.selectedEntity?.id ?? '';
    for (const actor of this.actors) {
      const pos = this.toCanvas(actor, width, height);
      const radius = actor.kind === 'player' ? 9 : 7;
      const selected = selectedId === actorNodeId(actor) || selectedId === actor.id;

      if (selected) {
        ctx.strokeStyle = 'rgba(245,158,11,.72)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, radius + 5, 0, Math.PI * 2);
        ctx.stroke();
      }

      ctx.fillStyle = actor.kind === 'player' ? '#00d4ff' : actor.kind === 'enemy' ? '#ef4444' : '#a8b3cf';
      ctx.strokeStyle = 'rgba(255,255,255,.55)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      this.drawHealth(ctx, pos.x, pos.y, actor);
      this.drawLabel(ctx, pos.x, pos.y, actor.label);
    }
  }

  private drawHealth(ctx: CanvasRenderingContext2D, x: number, y: number, actor: PreviewActor): void {
    const hp = actor.maxHealth > 0 ? Math.max(0, Math.min(1, actor.health / actor.maxHealth)) : 1;
    ctx.fillStyle = 'rgba(0,0,0,.55)';
    ctx.fillRect(x - 15, y - 20, 30, 3);
    ctx.fillStyle = hp > 0.35 ? '#22c55e' : '#f59e0b';
    ctx.fillRect(x - 15, y - 20, 30 * hp, 3);
  }

  private drawLabel(ctx: CanvasRenderingContext2D, x: number, y: number, label: string): void {
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(220,230,245,.82)';
    ctx.fillText(label.slice(0, 18), x, y + 22);
  }

  private drawEmpty(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    ctx.font = '12px monospace';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(168,179,207,.72)';
    ctx.fillText('No actors in current CGS', width / 2, height / 2);
  }

  private selectActorAt(event: MouseEvent, focus: boolean): void {
    if (!this.canvas) {
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const x = (event.clientX - rect.left) * dpr;
    const y = (event.clientY - rect.top) * dpr;
    const picked = this.actors.find((actor) => {
      const pos = this.toCanvas(actor, this.canvas!.width, this.canvas!.height);
      return Math.hypot(pos.x - x, pos.y - y) <= 16;
    });
    if (!picked) {
      return;
    }
    const runtime = this.deps.client.runtimeStatus;
    this.deps.client.send(makeEngineEdit(focus ? 'focus_entity' : 'select_entity', this.deps.client.sessionId, {
      entity_id: picked.id,
      cgs_hash: this.deps.cgsStore.hash,
      schema_version: this.deps.cgsStore.state.version,
      runtime_world_hash: runtime.latestWorldHash || runtime.lastTick?.world_hash || '',
      engine_adapter_sequence: runtime.engineAdapterSequence,
    }));
    this.deps.uiStore.selectEntity({
      id: actorNodeId(picked),
      kind: 'actor',
      label: picked.id,
      modeId: picked.modeId,
    });
  }

  private renderOverlay(): void {
    const tickEl = this.root?.querySelector<HTMLElement>('[data-role="tick"]');
    const fpsEl = this.root?.querySelector<HTMLElement>('[data-role="fps"]');
    const hashEl = this.root?.querySelector<HTMLElement>('[data-role="hash"]');
    if (tickEl) tickEl.textContent = `Tick ${this.tick.toLocaleString()}`;
    if (fpsEl) fpsEl.textContent = `FPS ${this.fps.toFixed(0)}`;
    if (hashEl) hashEl.textContent = `Hash ${this.worldHash ? `${this.worldHash.slice(0, 12)}...` : '-'}`;
  }

  private extractActors(): PreviewActor[] {
    const actors: PreviewActor[] = [];
    for (const { actor, modeId } of allActors(this.deps.cgsStore.cgs)) {
      const transform = componentDefaults(actor, 'COMP_TRANSFORM_V1');
      const health = componentDefaults(actor, 'COMP_HEALTH_V1');
      const velocity = componentDefaults(actor, 'COMP_VELOCITY_V1');
      const position = objectValue(transform['position']);
      actors.push({
        id: actor.id,
        modeId,
        label: actor.id,
        kind: actor.control_type === 'Human' ? 'player' : actor.actor_type === 'Enemy' ? 'enemy' : 'actor',
        x: numberValue(position?.['x'] ?? transform['position_x'] ?? transform['x'], actors.length * 2 - 2),
        z: numberValue(position?.['z'] ?? transform['position_z'] ?? transform['z'], actors.length % 2 === 0 ? -2 : 2),
        health: numberValue(health['current'] ?? health['hp'], 1),
        maxHealth: numberValue(health['max'] ?? health['max_hp'], numberValue(health['current'] ?? health['hp'], 1)),
        speed: Math.max(0.1, numberValue(velocity['max_linear_speed'] ?? velocity['speed'], 1)),
      });
    }
    return actors;
  }

  private extractRuntimeActors(message: EngineTickMessage): PreviewActor[] {
    const entities = message.entities ?? [];
    return entities.map((entity, index) => {
      const transform = componentJson(entity, 1);
      const identity = componentJson(entity, 2);
      const velocity = componentJson(entity, 5);
      const health = componentJson(entity, 100);
      const position = objectValue(transform['position']);
      const label = stringValue(identity['name'] ?? entity.actor_id, `Entity ${entity.id}`);
      const lowerLabel = label.toLowerCase();
      const vx = numberValue(velocity['linear_x'] ?? velocity['vx'] ?? velocity['x'], 0);
      const vz = numberValue(velocity['linear_z'] ?? velocity['vz'] ?? velocity['z'], 0);
      return {
        id: String(entity.id),
        modeId: 'runtime',
        label,
        kind: lowerLabel.includes('player')
          ? 'player'
          : lowerLabel.includes('enemy') || lowerLabel.includes('zombie')
            ? 'enemy'
            : 'actor',
        x: numberValue(position?.['x'] ?? transform['position_x'] ?? transform['x'], index * 2 - 2),
        z: numberValue(position?.['z'] ?? transform['position_z'] ?? transform['z'], index % 2 === 0 ? -2 : 2),
        health: numberValue(health['current'] ?? health['hp'], 1),
        maxHealth: numberValue(health['max'] ?? health['max_hp'], numberValue(health['current'] ?? health['hp'], 1)),
        speed: Math.max(0.1, Math.hypot(vx, vz)),
      };
    });
  }

  private toCanvas(actor: PreviewActor, width: number, height: number): { x: number; y: number } {
    const cx = width / 2;
    const cy = height / 2 + 12;
    const scale = Math.min(width, height) / 28;
    return {
      x: cx + actor.x * scale,
      y: cy + actor.z * scale,
    };
  }
}

function actorNodeId(actor: PreviewActor): string {
  if (actor.modeId === 'runtime') {
    return `runtime:${actor.id}`;
  }
  return `actor:${actor.modeId}:${actor.id}`;
}

function componentJson(entity: RuntimeEntityState, typeId: number): Record<string, unknown> {
  const raw = entity.components[String(typeId)] ?? entity.components[typeId as unknown as string];
  if (!raw) {
    return {};
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return objectValue(parsed) ?? {};
  } catch {
    return {};
  }
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function componentDefaults(
  actor: { components: readonly { name: string; defaults: Record<string, unknown> }[] },
  name: string,
): Record<string, unknown> {
  return actor.components.find((component) => component.name === name)?.defaults ?? {};
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function numberValue(value: unknown, fallback: number): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function injectStyles(): void {
  if (document.getElementById('xb-vp-styles')) return;
  const style = document.createElement('style');
  style.id = 'xb-vp-styles';
  style.textContent = STYLES;
  document.head.appendChild(style);
}
