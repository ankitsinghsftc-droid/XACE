/**
 * schema_graph_view.ts — Reusable Force-Directed CGS Graph
 *
 * Renders CGS nodes (entities, components, systems, rules) as an
 * interactive force-directed graph on a Canvas element.
 *
 * Used in TWO contexts:
 *   1. Left sidebar mini-graph (compact, 230px wide, overview)
 *   2. Center "Schema Graph" tab (full width, phase lanes, detail)
 *
 * The `config` object controls which context is active.
 *
 * Physics: spring-repulsion model (Coulomb repulsion + Hooke attraction).
 * Nodes drag to pin. Pinned nodes have a square border indicator.
 * Double-click unpins. Right-click opens context menu.
 *
 * Performance: only redraws when state changes (RAF-gated dirty flag).
 * Pauses animation when canvas is off-screen (IntersectionObserver).
 */

import type { CGSGraph, CGSGraphNode, CGSGraphEdge, GraphNodeKind } from '../types/cgs';
import type { UIStore, SelectedEntity } from '../state/ui_store';

// ── Config ────────────────────────────────────────────────────────────────────

export interface GraphConfig {
  /** 'mini' = sidebar, 'full' = center tab */
  mode:              'mini' | 'full';
  /** Show phase execution lanes (full mode only) */
  showPhaseLanes?:   boolean;
  /** Show edge labels */
  showEdgeLabels?:   boolean;
  /** Filter to only show these node kinds */
  visibleKinds?:     Set<GraphNodeKind>;
  /** Highlight these node IDs (e.g. after a mutation) */
  highlightedIds?:   Set<string>;
}

const DEFAULT_CONFIG: Required<GraphConfig> = {
  mode:           'full',
  showPhaseLanes: false,
  showEdgeLabels: true,
  visibleKinds:   new Set(['mode', 'actor', 'component', 'system', 'rule']),
  highlightedIds: new Set(),
};

// ── Visual constants ──────────────────────────────────────────────────────────

const NODE_COLORS: Record<GraphNodeKind, string> = {
  mode:      '#00d4ff',
  actor:     '#3b8bd4',
  component: '#ff9f43',
  system:    '#a855f7',
  rule:      '#10b981',
};

const EDGE_COLORS: Record<string, string> = {
  contains:  'rgba(0,212,255,.25)',
  has:       'rgba(255,159,67,.28)',
  reads:     'rgba(59,139,212,.35)',
  writes:    'rgba(168,85,247,.45)',
  depends_on:'rgba(83,74,183,.40)',
  triggers:  'rgba(16,185,129,.30)',
};

const NODE_BASE_RADIUS: Record<GraphNodeKind, number> = {
  mode:      14,
  actor:     12,
  component: 7,
  system:    10,
  rule:      8,
};

// ── Internal node state ───────────────────────────────────────────────────────

interface PhysNode {
  graphNode:  CGSGraphNode;
  x:          number;
  y:          number;
  vx:         number;
  vy:         number;
  pinned:     boolean;
  radius:     number;
  highlighted: boolean;
}

// ── Context menu ──────────────────────────────────────────────────────────────

interface ContextMenuItem {
  label:   string;
  action:  () => void;
  color?:  string;
}

// ── Graph component ───────────────────────────────────────────────────────────

export class SchemaGraphView {
  private readonly _config: Required<GraphConfig>;
  private readonly _uiStore: UIStore;

  private _canvas!:  HTMLCanvasElement;
  private _ctx!:     CanvasRenderingContext2D;
  private _raf:      number | null = null;
  private _dirty:    boolean = true;
  private _paused:   boolean = false;
  private _observer: IntersectionObserver | null = null;

  private _nodes:    PhysNode[] = [];
  private _edges:    CGSGraphEdge[] = [];
  private _width:    number = 0;
  private _height:   number = 0;

  // Interaction state
  private _dragging:    PhysNode | null = null;
  private _dragOffX:    number = 0;
  private _dragOffY:    number = 0;
  private _hovering:    PhysNode | null = null;
  private _contextMenu: HTMLElement | null = null;
  private _camera:      { x: number; y: number; zoom: number } = { x: 0, y: 0, zoom: 1 };
  private _panning:     boolean = false;
  private _panStart:    { x: number; y: number } = { x: 0, y: 0 };

  constructor(config: Partial<GraphConfig>, uiStore: UIStore) {
    this._config   = { ...DEFAULT_CONFIG, ...config };
    this._uiStore  = uiStore;
  }

  // ── Mount / unmount ──────────────────────────────────────────────────────

  mount(container: HTMLElement): HTMLCanvasElement {
    this._canvas = document.createElement('canvas');
    this._canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:grab';
    this._ctx = this._canvas.getContext('2d')!;
    container.appendChild(this._canvas);

    this._resize();
    this._bindEvents();
    this._startLoop();

    // Pause when off-screen to save CPU
    this._observer = new IntersectionObserver(entries => {
      this._paused = !entries[0]?.isIntersecting;
      if (!this._paused) this._dirty = true;
    }, { threshold: 0.01 });
    this._observer.observe(this._canvas);

    // Resize observer
    const ro = new ResizeObserver(() => { this._resize(); this._dirty = true; });
    ro.observe(container);

    return this._canvas;
  }

  unmount(): void {
    if (this._raf !== null) cancelAnimationFrame(this._raf);
    this._observer?.disconnect();
    this._canvas.remove();
  }

  // ── Data update ──────────────────────────────────────────────────────────

  setGraph(graph: CGSGraph): void {
    this._edges = graph.edges.filter(e => this._edgeVisible(e, graph));
    const existing = new Map(this._nodes.map(n => [n.graphNode.id, n]));

    this._nodes = graph.nodes
      .filter(n => this._config.visibleKinds.has(n.kind))
      .map(gn => {
        const prev = existing.get(gn.id);
        return {
          graphNode:   gn,
          x:           prev?.x ?? this._width  / 2 + (Math.random() - .5) * 200,
          y:           prev?.y ?? this._height / 2 + (Math.random() - .5) * 200,
          vx:          prev?.vx ?? 0,
          vy:          prev?.vy ?? 0,
          pinned:      prev?.pinned ?? false,
          radius:      this._nodeRadius(gn),
          highlighted: this._config.highlightedIds.has(gn.id),
        };
      });

    this._dirty = true;
  }

  setHighlighted(ids: ReadonlySet<string>): void {
    this._nodes.forEach(n => {
      n.highlighted = ids.has(n.graphNode.id);
    });
    this._config.highlightedIds = new Set(ids);
    this._dirty = true;
  }

  // ── Physics loop ─────────────────────────────────────────────────────────

  private _startLoop(): void {
    const loop = () => {
      this._raf = requestAnimationFrame(loop);
      if (this._paused) return;

      const moved = this._simulate();
      if (moved || this._dirty) {
        this._draw();
        this._dirty = false;
      }
    };
    this._raf = requestAnimationFrame(loop);
  }

  private _simulate(): boolean {
    if (this._nodes.length === 0) return false;

    const repelStrength  = this._config.mode === 'mini' ? 600  : 1200;
    const springStrength = this._config.mode === 'mini' ? .015 : .012;
    const springLen      = this._config.mode === 'mini' ? 55   : 90;
    const damping        = 0.82;
    let   moved          = false;

    // Repulsion
    for (let i = 0; i < this._nodes.length; i++) {
      for (let j = i + 1; j < this._nodes.length; j++) {
        const a = this._nodes[i]!;
        const b = this._nodes[j]!;
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d  = Math.sqrt(dx * dx + dy * dy) || 1;
        const f  = repelStrength / (d * d);
        if (!a.pinned) { a.vx += dx / d * f; a.vy += dy / d * f; }
        if (!b.pinned) { b.vx -= dx / d * f; b.vy -= dy / d * f; }
      }
    }

    // Spring attraction along edges
    const nodeById = new Map(this._nodes.map(n => [n.graphNode.id, n]));
    for (const edge of this._edges) {
      const a = nodeById.get(edge.source);
      const b = nodeById.get(edge.target);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d  = Math.sqrt(dx * dx + dy * dy) || 1;
      const f  = (d - springLen) * springStrength;
      const fx = dx / d * f;
      const fy = dy / d * f;
      if (!a.pinned) { a.vx += fx; a.vy += fy; }
      if (!b.pinned) { b.vx -= fx; b.vy -= fy; }
    }

    // Integrate + clamp
    const pad = 20;
    for (const n of this._nodes) {
      if (n.pinned) continue;
      n.vx *= damping;
      n.vy *= damping;
      n.x  += n.vx;
      n.y  += n.vy;
      n.x   = Math.max(pad + n.radius, Math.min(this._width  - pad - n.radius, n.x));
      n.y   = Math.max(pad + n.radius, Math.min(this._height - pad - n.radius, n.y));
      if (Math.abs(n.vx) > 0.05 || Math.abs(n.vy) > 0.05) moved = true;
    }

    return moved;
  }

  // ── Draw ──────────────────────────────────────────────────────────────────

  private _draw(): void {
    const ctx = this._ctx;
    const W   = this._width;
    const H   = this._height;

    ctx.clearRect(0, 0, W, H);
    ctx.save();
    ctx.translate(this._camera.x, this._camera.y);
    ctx.scale(this._camera.zoom, this._camera.zoom);

    // Phase lanes (full mode)
    if (this._config.showPhaseLanes && this._config.mode === 'full') {
      this._drawPhaseLanes(ctx, W, H);
    }

    // Edges
    this._drawEdges(ctx);

    // Nodes
    this._drawNodes(ctx);

    ctx.restore();
  }

  private _drawPhaseLanes(ctx: CanvasRenderingContext2D, W: number, H: number): void {
    const lanes = ['Input', 'Simulation', 'PostSimulation', 'Render'];
    const laneH = H / lanes.length;
    lanes.forEach((label, i) => {
      const y = i * laneH;
      ctx.fillStyle = i % 2 === 0
        ? 'rgba(255,255,255,.012)'
        : 'rgba(255,255,255,.006)';
      ctx.fillRect(0, y, W, laneH);
      ctx.fillStyle = 'rgba(255,255,255,.06)';
      ctx.font      = '10px Inter, sans-serif';
      ctx.fillText(label, 8, y + 14);
    });
  }

  private _drawEdges(ctx: CanvasRenderingContext2D): void {
    const nodeById = new Map(this._nodes.map(n => [n.graphNode.id, n]));

    for (const edge of this._edges) {
      const a = nodeById.get(edge.source);
      const b = nodeById.get(edge.target);
      if (!a || !b) continue;

      const color = EDGE_COLORS[edge.kind] ?? 'rgba(255,255,255,.15)';
      const width = edge.kind === 'writes' ? 2 : 1.2;

      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = color;
      ctx.lineWidth   = width;
      if (edge.kind === 'reads') {
        ctx.setLineDash([5, 3]);
      } else {
        ctx.setLineDash([]);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Edge label (full mode only)
      if (this._config.showEdgeLabels && this._config.mode === 'full') {
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        ctx.fillStyle = 'rgba(90,104,128,.8)';
        ctx.font      = '8px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        ctx.fillText(edge.kind, mx, my);
      }
    }
  }

  private _drawNodes(ctx: CanvasRenderingContext2D): void {
    const selected = this._uiStore.selectedEntity;

    for (const n of this._nodes) {
      const r      = n.radius;
      const isHov  = n === this._hovering;
      const isSel  = selected?.id === n.graphNode.id;
      const isHigh = n.highlighted;
      const color  = NODE_COLORS[n.graphNode.kind] ?? '#5a6880';

      // Glow for highlighted nodes
      if (isHigh) {
        ctx.shadowColor = color;
        ctx.shadowBlur  = 12;
      }

      // Fill
      ctx.beginPath();
      if (n.graphNode.kind === 'rule') {
        // Diamond
        ctx.moveTo(n.x, n.y - r);
        ctx.lineTo(n.x + r, n.y);
        ctx.lineTo(n.x, n.y + r);
        ctx.lineTo(n.x - r, n.y);
        ctx.closePath();
      } else if (n.graphNode.kind === 'mode') {
        this._roundRect(ctx, n.x - r * 1.3, n.y - r * .7, r * 2.6, r * 1.4, 6);
      } else {
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      }

      ctx.fillStyle = color + (isHigh ? '33' : '1a');
      ctx.fill();

      // Stroke
      ctx.strokeStyle = isHigh ? color : (isSel ? color : (isHov ? color : color + '88'));
      ctx.lineWidth   = isSel ? 2.5 : (isHigh ? 2 : 1.5);
      ctx.stroke();

      ctx.shadowBlur  = 0;
      ctx.shadowColor = 'transparent';

      // Pin indicator
      if (n.pinned) {
        ctx.fillStyle = color + 'aa';
        ctx.fillRect(n.x - 3, n.y - r - 7, 6, 6);
      }

      // Label
      const label = n.graphNode.label.length > 14
        ? n.graphNode.label.slice(0, 13) + '…'
        : n.graphNode.label;
      ctx.fillStyle = isHov || isSel ? color : (n.graphNode.kind === 'component' ? '#ff9f43cc' : '#dde4f0cc');
      ctx.font      = this._config.mode === 'mini'
        ? '8px Inter, sans-serif'
        : `${n.graphNode.kind === 'mode' ? 11 : 9}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(label, n.x, n.y + r + (this._config.mode === 'mini' ? 9 : 11));
    }

    ctx.textAlign = 'left';
  }

  private _roundRect(
    ctx: CanvasRenderingContext2D,
    x: number, y: number, w: number, h: number, r: number,
  ): void {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  // ── Events ───────────────────────────────────────────────────────────────

  private _bindEvents(): void {
    const c = this._canvas;
    c.addEventListener('mousedown',  this._onMouseDown.bind(this));
    c.addEventListener('mousemove',  this._onMouseMove.bind(this));
    c.addEventListener('mouseup',    this._onMouseUp.bind(this));
    c.addEventListener('dblclick',   this._onDblClick.bind(this));
    c.addEventListener('contextmenu', this._onContextMenu.bind(this));
    c.addEventListener('wheel',      this._onWheel.bind(this), { passive: false });
    c.addEventListener('mouseleave', () => { this._hovering = null; this._dirty = true; });
  }

  private _worldPos(e: MouseEvent): { x: number; y: number } {
    const rect = this._canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left - this._camera.x) / this._camera.zoom,
      y: (e.clientY - rect.top  - this._camera.y) / this._camera.zoom,
    };
  }

  private _nodeAt(wx: number, wy: number): PhysNode | null {
    for (let i = this._nodes.length - 1; i >= 0; i--) {
      const n  = this._nodes[i]!;
      const dx = wx - n.x;
      const dy = wy - n.y;
      if (Math.sqrt(dx * dx + dy * dy) <= n.radius + 4) return n;
    }
    return null;
  }

  private _onMouseDown(e: MouseEvent): void {
    const { x, y } = this._worldPos(e);
    const hit      = this._nodeAt(x, y);
    this._closeContextMenu();

    if (hit && e.button === 0) {
      this._dragging = hit;
      this._dragOffX = x - hit.x;
      this._dragOffY = y - hit.y;
      this._canvas.style.cursor = 'grabbing';
    } else if (!hit && e.button === 0) {
      this._panning  = true;
      this._panStart = { x: e.clientX - this._camera.x, y: e.clientY - this._camera.y };
      this._canvas.style.cursor = 'grabbing';
    }
  }

  private _onMouseMove(e: MouseEvent): void {
    const { x, y } = this._worldPos(e);

    if (this._dragging) {
      this._dragging.x      = x - this._dragOffX;
      this._dragging.y      = y - this._dragOffY;
      this._dragging.vx     = 0;
      this._dragging.vy     = 0;
      this._dragging.pinned = true;
      this._dirty           = true;
      return;
    }

    if (this._panning) {
      this._camera.x = e.clientX - this._panStart.x;
      this._camera.y = e.clientY - this._panStart.y;
      this._dirty    = true;
      return;
    }

    const prev      = this._hovering;
    this._hovering  = this._nodeAt(x, y);
    this._canvas.style.cursor = this._hovering ? 'pointer' : 'grab';
    if (prev !== this._hovering) this._dirty = true;
  }

  private _onMouseUp(e: MouseEvent): void {
    if (e.button === 0) {
      if (this._dragging && !this._panning) {
        // Short drag = click → select
        const { x, y } = this._worldPos(e);
        const dx = x - this._dragging.x + this._dragOffX;
        const dy = y - this._dragging.y + this._dragOffY;
        if (Math.abs(dx) < 5 && Math.abs(dy) < 5) {
          this._selectNode(this._dragging);
        }
      }
      this._dragging = null;
      this._panning  = false;
      this._canvas.style.cursor = 'grab';
    }
  }

  private _onDblClick(e: MouseEvent): void {
    const { x, y } = this._worldPos(e);
    const hit       = this._nodeAt(x, y);
    if (hit) {
      hit.pinned  = false;
      this._dirty = true;
    } else {
      // Reset camera
      this._camera = { x: 0, y: 0, zoom: 1 };
      this._dirty  = true;
    }
  }

  private _onContextMenu(e: MouseEvent): void {
    e.preventDefault();
    const { x, y } = this._worldPos(e);
    const hit       = this._nodeAt(x, y);
    if (!hit) return;

    const items: ContextMenuItem[] = [
      {
        label:  '✦ Edit via prompt',
        action: () => {
          this._selectNode(hit);
          // Dispatch event for prompt_input to pre-fill
          window.dispatchEvent(new CustomEvent('xace:prefill-prompt', {
            detail: { nodeId: hit.graphNode.id, nodeLabel: hit.graphNode.label },
          }));
        },
      },
      {
        label:  '? Explain this',
        action: () => {
          window.dispatchEvent(new CustomEvent('xace:explain-node', {
            detail: { nodeId: hit.graphNode.id, nodeLabel: hit.graphNode.label },
          }));
        },
      },
      {
        label:  hit.pinned ? '⊙ Unpin' : '⊡ Pin here',
        action: () => { hit.pinned = !hit.pinned; this._dirty = true; },
      },
    ];

    this._showContextMenu(e.clientX, e.clientY, items);
  }

  private _onWheel(e: WheelEvent): void {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    const rect   = this._canvas.getBoundingClientRect();
    const mx     = e.clientX - rect.left;
    const my     = e.clientY - rect.top;

    // Zoom toward cursor
    this._camera.x  = mx - (mx - this._camera.x) * factor;
    this._camera.y  = my - (my - this._camera.y) * factor;
    this._camera.zoom = Math.max(0.3, Math.min(3, this._camera.zoom * factor));
    this._dirty     = true;
  }

  // ── Context menu ──────────────────────────────────────────────────────────

  private _showContextMenu(cx: number, cy: number, items: ContextMenuItem[]): void {
    this._closeContextMenu();

    const menu = document.createElement('div');
    menu.style.cssText = `
      position:fixed;left:${cx}px;top:${cy}px;
      background:var(--bga);border:1px solid var(--bdh);border-radius:var(--r);
      padding:4px;z-index:500;min-width:160px;box-shadow:0 4px 20px rgba(0,0,0,.4);
      animation:fade-in 100ms ease-out;
    `;

    for (const item of items) {
      const row = document.createElement('button');
      row.style.cssText = `
        display:block;width:100%;text-align:left;padding:5px 10px;
        background:transparent;border:none;color:var(--txt2);font-size:11px;
        border-radius:var(--rs);cursor:pointer;font-family:inherit;
        transition:all 100ms;
      `;
      if (item.color) row.style.color = item.color;
      row.textContent = item.label;
      row.addEventListener('mouseenter', () => {
        row.style.background = 'rgba(255,255,255,.05)';
        row.style.color      = item.color ?? 'var(--txt)';
      });
      row.addEventListener('mouseleave', () => {
        row.style.background = 'transparent';
        row.style.color      = item.color ?? 'var(--txt2)';
      });
      row.addEventListener('click', () => {
        item.action();
        this._closeContextMenu();
      });
      menu.appendChild(row);
    }

    document.body.appendChild(menu);
    this._contextMenu = menu;

    // Close on outside click
    const close = (e: MouseEvent) => {
      if (!menu.contains(e.target as Node)) {
        this._closeContextMenu();
        document.removeEventListener('click', close);
      }
    };
    setTimeout(() => document.addEventListener('click', close), 10);
  }

  private _closeContextMenu(): void {
    this._contextMenu?.remove();
    this._contextMenu = null;
  }

  // ── Selection ─────────────────────────────────────────────────────────────

  private _selectNode(n: PhysNode): void {
    const entity: SelectedEntity = {
      id:     n.graphNode.id,
      kind:   n.graphNode.kind,
      label:  n.graphNode.label,
      modeId: n.graphNode.modeId ?? '',
    };
    this._uiStore.selectEntity(entity);
    this._dirty = true;
  }

  // ── Utilities ─────────────────────────────────────────────────────────────

  private _resize(): void {
    const rect   = this._canvas.parentElement?.getBoundingClientRect();
    const dpr    = window.devicePixelRatio || 1;
    this._width  = rect?.width  ?? 400;
    this._height = rect?.height ?? 300;
    this._canvas.width  = this._width  * dpr;
    this._canvas.height = this._height * dpr;
    this._canvas.style.width  = `${this._width}px`;
    this._canvas.style.height = `${this._height}px`;
    this._ctx.scale(dpr, dpr);
    this._dirty = true;
  }

  private _nodeRadius(n: CGSGraphNode): number {
    const base = NODE_BASE_RADIUS[n.kind] ?? 9;
    if (this._config.mode === 'mini') return Math.min(base, 11);
    return base + Math.min(n.weight * .8, 6);
  }

  private _edgeVisible(edge: CGSGraphEdge, graph: CGSGraph): boolean {
    const kinds = this._config.visibleKinds;
    const srcNode = graph.nodes.find(n => n.id === edge.source);
    const tgtNode = graph.nodes.find(n => n.id === edge.target);
    return (
      srcNode !== undefined &&
      tgtNode !== undefined &&
      kinds.has(srcNode.kind) &&
      kinds.has(tgtNode.kind)
    );
  }
}