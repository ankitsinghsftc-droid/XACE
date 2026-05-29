/**
 * main_layout.ts — XACE Builder main three-panel layout shell
 *
 * Structure:
 *   ┌─────────────────────────────────────────────────────┐
 *   │  TopBar (42px fixed)                                │
 *   ├────────┬────────────────────────────┬───────────────┤
 *   │ Left   │  Center canvas             │  Right panel  │
 *   │ Sidebar│  (flex: 1)                 │  (310px)      │
 *   │ (230px)│                            │               │
 *   └────────┴────────────────────────────┴───────────────┘
 *
 * Panels collapse/expand via uiStore flags.
 * Resize handles allow dragging panel width (stored in localStorage).
 * Top bar contains: logo, project name, mode selector, engine status, run button.
 *
 * This file mounts the top bar and wires up the panel layout.
 * Actual panel content (CGSExplorer, BuilderCanvas, PreviewPanel) is
 * mounted by their respective component files, not here.
 */

import type { BuilderClient }  from '../src/api/builder_client';
import type { ConsoleSM }      from '../src/state/console_state_machine';
import type { CGSStore }       from '../src/state/cgs_store';
import type { UIStore }        from '../src/state/ui_store';
import {
  AssistanceMode,
  MODE_LABELS,
  MODE_DESCRIPTIONS,
}                               from '../src/types/pil';

// ── Layout styles ─────────────────────────────────────────────────────────────

const STYLES = `
.xb-layout {
  display:        flex;
  flex-direction: column;
  height:         100vh;
  overflow:       hidden;
  background:     var(--bg);
}

/* ── Top bar ── */
.xb-topbar {
  height:          var(--topbar-h);
  background:      var(--bgp);
  border-bottom:   1px solid var(--bd);
  display:         flex;
  align-items:     center;
  padding:         0 12px;
  gap:             8px;
  flex-shrink:     0;
  z-index:         100;
  user-select:     none;
}
.xb-logo {
  display:     flex;
  align-items: center;
  gap:         7px;
  font-size:   15px;
  font-weight: 700;
  letter-spacing: -.02em;
  color:       var(--txt);
  flex-shrink: 0;
}
.xb-logo-icon {
  width:           24px;
  height:          24px;
  background:      linear-gradient(135deg, var(--cyan), var(--vlt));
  border-radius:   5px;
  display:         flex;
  align-items:     center;
  justify-content: center;
  font-size:       12px;
  font-weight:     900;
  color:           #000;
  flex-shrink:     0;
}
.xb-divider {
  width:      1px;
  height:     16px;
  background: var(--bd);
  flex-shrink: 0;
}
.xb-project {
  font-size: 11px;
  color:     var(--txt2);
  display:   flex;
  align-items: center;
  gap:       4px;
}
.xb-project strong {
  color:       var(--txt);
  font-weight: 500;
}
.xb-spacer { flex: 1; }

/* ── Mode pills ── */
.xb-modes {
  display:     flex;
  align-items: center;
  gap:         3px;
  background:  rgba(255,255,255,.03);
  border:      1px solid var(--bd);
  border-radius: 20px;
  padding:     3px;
}
.xb-mode-pill {
  padding:       3px 10px;
  border-radius: 20px;
  font-size:     10px;
  font-weight:   600;
  letter-spacing: .04em;
  cursor:        pointer;
  border:        1px solid transparent;
  color:         var(--txt2);
  background:    transparent;
  transition:    all var(--tr);
  white-space:   nowrap;
  font-family:   inherit;
}
.xb-mode-pill:hover:not(.active) {
  color:      var(--txt);
  background: rgba(255,255,255,.04);
}
.xb-mode-pill.active[data-mode="FULLY_ASSISTED"] {
  background:  var(--cynd);
  border-color: rgba(0,212,255,.3);
  color:       var(--cyan);
}
.xb-mode-pill.active[data-mode="COLLABORATIVE"] {
  background:  var(--cynd);
  border-color: rgba(0,212,255,.25);
  color:       var(--cyan);
}
.xb-mode-pill.active[data-mode="ADVANCED"] {
  background:  var(--ambd);
  border-color: rgba(255,159,67,.3);
  color:       var(--amb);
}
.xb-mode-pill.active[data-mode="ARCHITECT_MODE"] {
  background:  var(--vltd);
  border-color: rgba(168,85,247,.35);
  color:       var(--vlt);
}

/* ── Engine status ── */
.xb-engine-status {
  display:     flex;
  align-items: center;
  gap:         5px;
  font-size:   10.5px;
  color:       var(--txt2);
  flex-shrink: 0;
}
.xb-status-dot {
  width:         7px;
  height:        7px;
  border-radius: 50%;
  flex-shrink:   0;
}
.xb-status-dot.live {
  background: var(--grn);
  animation:  pulse-dot 2.2s ease-in-out infinite;
  color:      var(--grn);
}
.xb-status-dot.connecting {
  background: var(--amb);
  animation:  pulse-dot 1s ease-in-out infinite;
  color:      var(--amb);
}
.xb-status-dot.disconnected {
  background: var(--txt3);
}

/* ── Run button ── */
.xb-run-btn {
  background:   none;
  border:       1px solid rgba(0,212,255,.35);
  border-radius: var(--rs);
  color:        var(--cyan);
  font-size:    10px;
  font-weight:  600;
  padding:      3px 10px;
  display:      flex;
  align-items:  center;
  gap:          4px;
  transition:   all var(--tr);
  flex-shrink:  0;
}
.xb-run-btn:hover {
  background:  var(--cynd);
  box-shadow:  0 0 12px rgba(0,212,255,.2);
}

.xb-icon-btn {
  background:    none;
  border:        none;
  color:         var(--txt2);
  font-size:     15px;
  padding:       3px 6px;
  border-radius: var(--rs);
  transition:    all var(--tr-f);
  flex-shrink:   0;
}
.xb-icon-btn:hover { color: var(--txt); background: rgba(255,255,255,.04); }

/* ── Workspace ── */
.xb-workspace {
  display:    flex;
  flex:       1;
  overflow:   hidden;
  position:   relative;
}

/* ── Left sidebar ── */
.xb-left {
  width:        var(--sidebar-w);
  flex-shrink:  0;
  background:   var(--bgp);
  border-right: 1px solid var(--bd);
  display:      flex;
  flex-direction: column;
  overflow:     hidden;
  transition:   width var(--tr), opacity var(--tr);
  position:     relative;
}
.xb-left.collapsed {
  width:   0;
  opacity: 0;
}

/* ── Center ── */
.xb-center {
  flex:           1;
  background:     var(--bg);
  display:        flex;
  flex-direction: column;
  overflow:       hidden;
  position:       relative;
  min-width:      0;
}
/* Subtle grid background */
.xb-center::before {
  content:           '';
  position:          absolute;
  inset:             0;
  background-image:  linear-gradient(rgba(255,255,255,.015) 1px, transparent 1px),
                     linear-gradient(90deg, rgba(255,255,255,.015) 1px, transparent 1px);
  background-size:   24px 24px;
  pointer-events:    none;
  z-index:           0;
}

/* ── Right panel ── */
.xb-right {
  width:        var(--right-panel-w);
  flex-shrink:  0;
  background:   var(--bgp);
  border-left:  1px solid var(--bd);
  display:      flex;
  flex-direction: column;
  overflow:     hidden;
  transition:   width var(--tr), opacity var(--tr);
}
.xb-right.collapsed {
  width:   0;
  opacity: 0;
}

/* ── Resize handles ── */
.xb-resize-handle {
  position:   absolute;
  top:        0;
  bottom:     0;
  width:      4px;
  cursor:     col-resize;
  z-index:    50;
  background: transparent;
  transition: background var(--tr-f);
}
.xb-resize-handle:hover,
.xb-resize-handle.dragging {
  background: rgba(0,212,255,.3);
}
.xb-resize-left  { right: -2px; }
.xb-resize-right { left: -2px; }

/* ── Architect mode banner ── */
.xb-arch-bar {
  background:    rgba(168,85,247,.06);
  border-bottom: 1px solid rgba(168,85,247,.12);
  padding:       4px 10px;
  display:       flex;
  align-items:   center;
  gap:           6px;
  font-size:     9.5px;
  color:         var(--vlt);
  flex-shrink:   0;
  z-index:       1;
}
.xb-arch-bar.hidden { display: none; }
`;

// ── Component ─────────────────────────────────────────────────────────────────

interface MainLayoutDeps {
  client:    BuilderClient;
  consoleSM: ConsoleSM;
  cgsStore:  CGSStore;
  uiStore:   UIStore;
}

export class MainLayout {
  private readonly _deps: MainLayoutDeps;
  private _el!:      HTMLElement;
  private _leftEl!:  HTMLElement;
  private _rightEl!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  // Slots exposed for other components to mount into
  leftSlot!:   HTMLElement;
  centerSlot!: HTMLElement;
  rightSlot!:  HTMLElement;

  constructor(deps: MainLayoutDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = this._build();
    container.appendChild(this._el);
    this._wireReactive();
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  // ── Build DOM ─────────────────────────────────────────────────────────────

  private _build(): HTMLElement {
    const root = el('div', 'xb-layout');

    // ── Top bar ──────────────────────────────────────────────────────────
    root.appendChild(this._buildTopBar());

    // ── Architect mode banner ─────────────────────────────────────────────
    const archBar = el('div', 'xb-arch-bar hidden', {
      id:          'xb-arch-bar',
      textContent: '▣ Architect Mode — raw schema paths · full telemetry · determinism invariants visible',
    });
    root.appendChild(archBar);

    // ── Workspace ─────────────────────────────────────────────────────────
    const workspace = el('div', 'xb-workspace');

    // Left sidebar
    this._leftEl = el('div', 'xb-left');
    this.leftSlot = el('div', '', { style: 'flex:1;overflow:hidden;display:flex;flex-direction:column' });
    this._leftEl.appendChild(this.leftSlot);
    const leftHandle = el('div', 'xb-resize-handle xb-resize-left');
    this._leftEl.appendChild(leftHandle);
    workspace.appendChild(this._leftEl);

    // Center
    const center = el('div', 'xb-center');
    this.centerSlot = el('div', '', { style: 'flex:1;overflow:hidden;display:flex;flex-direction:column;position:relative;z-index:1' });
    center.appendChild(this.centerSlot);
    workspace.appendChild(center);

    // Right panel
    this._rightEl = el('div', 'xb-right');
    const rightHandle = el('div', 'xb-resize-handle xb-resize-right');
    this._rightEl.appendChild(rightHandle);
    this.rightSlot = el('div', '', { style: 'flex:1;overflow:hidden;display:flex;flex-direction:column' });
    this._rightEl.appendChild(this.rightSlot);
    workspace.appendChild(this._rightEl);

    root.appendChild(workspace);

    // Wire resize handles
    this._wireResize(leftHandle,  this._leftEl,  '--sidebar-w',     160, 320);
    this._wireResize(rightHandle, this._rightEl, '--right-panel-w', 220, 460);

    return root;
  }

  private _buildTopBar(): HTMLElement {
    const bar = el('div', 'xb-topbar');

    // Logo
    const logo = el('div', 'xb-logo');
    logo.appendChild(el('div', 'xb-logo-icon', { textContent: 'X' }));
    logo.appendChild(text('XACE'));
    bar.appendChild(logo);
    bar.appendChild(el('div', 'xb-divider'));

    // Project name
    const project = el('div', 'xb-project', { id: 'xb-project-name' });
    project.innerHTML = '/ <strong>Loading…</strong>';
    bar.appendChild(project);

    bar.appendChild(el('div', 'xb-spacer'));

    // Mode pills
    const modes = el('div', 'xb-modes');
    const modeOrder: AssistanceMode[] = [
      'FULLY_ASSISTED', 'COLLABORATIVE', 'ADVANCED', 'ARCHITECT_MODE',
    ];
    for (const m of modeOrder) {
      const pill = el('button', 'xb-mode-pill', {
        textContent:     MODE_LABELS[m],
        'data-mode':     m,
        'data-tip':      MODE_DESCRIPTIONS[m],
      });
      pill.addEventListener('click', () => this._deps.uiStore.setMode(m));
      modes.appendChild(pill);
    }
    bar.appendChild(modes);

    bar.appendChild(el('div', 'xb-spacer'));

    // Connection / engine status
    const status = el('div', 'xb-engine-status', { id: 'xb-engine-status' });
    status.appendChild(el('div', 'xb-status-dot connecting', { id: 'xb-status-dot' }));
    status.appendChild(el('span', '', { id: 'xb-status-text', textContent: 'Connecting…' }));
    bar.appendChild(status);

    // Run button (Phase 15: triggers engine run)
    const runBtn = el('button', 'xb-run-btn', { textContent: '▷ Run' });
    runBtn.addEventListener('click', () => {
      console.info('[TopBar] Run clicked — engine integration in Phase 15');
    });
    bar.appendChild(runBtn);

    // Settings
    const settingsBtn = el('button', 'xb-icon-btn', {
      textContent: '⚙',
      title:       'Settings',
    });
    bar.appendChild(settingsBtn);

    return bar;
  }

  // ── Reactive wiring ───────────────────────────────────────────────────────

  private _wireReactive(): void {
    const { uiStore, cgsStore } = this._deps;

    // Mode changes → update pills + arch bar
    this._unsubs.push(
      uiStore.subscribe(state => {
        // Update mode pills
        const pills = this._el.querySelectorAll('.xb-mode-pill');
        pills.forEach(pill => {
          const m = (pill as HTMLElement).dataset['mode'];
          pill.classList.toggle('active', m === state.mode);
        });

        // Show/hide arch bar
        const archBar = document.getElementById('xb-arch-bar');
        archBar?.classList.toggle('hidden', state.mode !== 'ARCHITECT_MODE');

        // Left/right collapse
        this._leftEl.classList.toggle('collapsed', state.sidebarCollapsed);
        this._rightEl.classList.toggle('collapsed', state.rightPanelCollapsed);
      }),
    );

    // CGS loaded → update project name
    this._unsubs.push(
      cgsStore.subscribe(state => {
        const nameEl = document.getElementById('xb-project-name');
        if (nameEl) {
          nameEl.innerHTML = `/ <strong>${state.cgs.metadata.name}</strong>`;
        }
      }),
    );

    // Connection state → update status dot
    this._unsubs.push(
      this._deps.client.onConnectionState(connState => {
        const dot  = document.getElementById('xb-status-dot');
        const text = document.getElementById('xb-status-text');
        if (!dot || !text) return;

        dot.className = 'xb-status-dot';
        if (connState === 'connected') {
          dot.classList.add('live');
          text.textContent = 'Connected';
        } else if (connState === 'connecting' || connState === 'reconnecting') {
          dot.classList.add('connecting');
          text.textContent = connState === 'reconnecting' ? 'Reconnecting…' : 'Connecting…';
        } else {
          dot.classList.add('disconnected');
          text.textContent = 'Offline';
        }
      }),
    );
  }

  // ── Resize handles ────────────────────────────────────────────────────────

  private _wireResize(
    handle:    HTMLElement,
    panel:     HTMLElement,
    cssVar:    string,
    minWidth:  number,
    maxWidth:  number,
  ): void {
    let startX   = 0;
    let startW   = 0;
    let dragging = false;

    const onMove = (e: MouseEvent) => {
      if (!dragging) return;
      const delta  = e.clientX - startX;
      const isLeft = cssVar === '--sidebar-w';
      const newW   = Math.max(minWidth, Math.min(maxWidth,
        isLeft ? startW + delta : startW - delta,
      ));
      document.documentElement.style.setProperty(cssVar, `${newW}px`);
    };

    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('dragging');
      document.body.style.cursor   = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup',   onUp);
    };

    handle.addEventListener('mousedown', (e: MouseEvent) => {
      dragging = true;
      startX   = e.clientX;
      startW   = panel.offsetWidth;
      handle.classList.add('dragging');
      document.body.style.cursor    = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup',   onUp);
      e.preventDefault();
    });
  }

  // ── Style injection ───────────────────────────────────────────────────────

  private _injectStyles(): void {
    if (document.getElementById('xb-layout-styles')) return;
    const style = document.createElement('style');
    style.id        = 'xb-layout-styles';
    style.textContent = STYLES;
    document.head.appendChild(style);
  }
}

// ── DOM helpers ───────────────────────────────────────────────────────────────

function el(
  tag:   string,
  cls:   string,
  attrs: Record<string, string> = {},
): HTMLElement {
  const elem = document.createElement(tag);
  if (cls) elem.className = cls;
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'textContent') elem.textContent = v;
    else if (k === 'innerHTML') elem.innerHTML = v;
    else elem.setAttribute(k, v);
  }
  return elem;
}

function text(content: string): Text {
  return document.createTextNode(content);
}