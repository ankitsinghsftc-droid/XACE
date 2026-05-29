/**
 * bottom_bar.ts — Version Timeline Bar
 *
 * Fixed bar at the bottom of the workspace.
 * Shows the CGS version history as a scrollable horizontal timeline of snapshot dots.
 *
 * Each dot = one committed mutation. Clicking a dot shows the snapshot
 * summary in a tooltip, double-clicking triggers rollback (with confirmation).
 *
 * The current snapshot dot pulses cyan. Past dots are white at reduced opacity.
 * Version bump type (patch/minor/major) is encoded in dot size.
 */

import type { BuilderClient } from '../api/builder_client';
import type { CGSStore }      from '../state/cgs_store';
import type { UIStore }       from '../state/ui_store';
import type { CGSSnapshot }   from '../types/cgs';

const STYLES = `
.xb-bottom-bar {
  height:          var(--bottombar-h);
  background:      var(--bgp);
  border-top:      1px solid var(--bd);
  display:         flex;
  flex-direction:  column;
  flex-shrink:     0;
  user-select:     none;
}
.xb-bb-drag {
  height:          5px;
  display:         flex;
  align-items:     center;
  justify-content: center;
  cursor:          row-resize;
  flex-shrink:     0;
}
.xb-bb-drag-pip {
  width:         30px;
  height:        2px;
  background:    var(--bd);
  border-radius: 2px;
  transition:    background var(--tr-f);
}
.xb-bb-drag:hover .xb-bb-drag-pip { background: var(--bdh); }
.xb-bb-head {
  display:         flex;
  align-items:     center;
  gap:             8px;
  padding:         3px 12px 3px;
  border-bottom:   1px solid var(--bd);
  flex-shrink:     0;
}
.xb-bb-title {
  font-size:       9px;
  font-weight:     700;
  letter-spacing:  .12em;
  text-transform:  uppercase;
  color:           var(--txt2);
  flex:            1;
}
.xb-bb-meta {
  font-size:       9.5px;
  font-family:     var(--font-mono);
  color:           var(--txt3);
}
.xb-bb-ver-lbl {
  font-size:       9px;
  font-family:     var(--font-mono);
  color:           var(--txt2);
  max-width:       260px;
  overflow:        hidden;
  text-overflow:   ellipsis;
  white-space:     nowrap;
}
.xb-bb-body {
  flex:            1;
  display:         flex;
  align-items:     center;
  padding:         0 12px;
  overflow-x:      auto;
  gap:             0;
  scrollbar-width: none;
}
.xb-bb-body::-webkit-scrollbar { display: none; }
.xb-tl-wrap {
  position:        relative;
  display:         flex;
  align-items:     center;
  flex:            1;
  min-width:       0;
}
.xb-tl-line {
  position:        absolute;
  left:            0;
  right:           0;
  height:          1px;
  background:      var(--bd);
  pointer-events:  none;
}
.xb-tl-snaps {
  display:         flex;
  align-items:     center;
  gap:             18px;
  position:        relative;
  z-index:         1;
}
.xb-snap {
  display:         flex;
  flex-direction:  column;
  align-items:     center;
  gap:             3px;
  cursor:          pointer;
  transition:      transform var(--tr-f);
  position:        relative;
}
.xb-snap:hover { transform: translateY(-1px); }
.xb-snap-dot {
  border-radius:   50%;
  border:          2px solid var(--bd);
  background:      rgba(255,255,255,.08);
  transition:      all var(--tr);
  flex-shrink:     0;
}
.xb-snap-dot.patch  { width: 9px;  height: 9px; }
.xb-snap-dot.minor  { width: 11px; height: 11px; }
.xb-snap-dot.major  { width: 13px; height: 13px; }
.xb-snap.current .xb-snap-dot {
  background:    var(--cyan);
  border-color:  var(--cyan);
  box-shadow:    0 0 8px rgba(0,212,255,.5);
  animation:     pulse-dot 2.2s ease-in-out infinite;
  color:         var(--cyan);
}
.xb-snap:hover:not(.current) .xb-snap-dot {
  background:   rgba(0,212,255,.2);
  border-color: var(--cyan);
}
.xb-snap-ver {
  font-family:  var(--font-mono);
  font-size:    8px;
  color:        var(--txt2);
  text-align:   center;
  line-height:  1.2;
}
.xb-snap.current .xb-snap-ver {
  color:       var(--cyan);
  font-weight: 600;
}
.xb-snap-time {
  font-size:   7.5px;
  color:       var(--txt3);
  text-align:  center;
}
/* Rollback tooltip */
.xb-snap-tip {
  position:      absolute;
  bottom:        calc(100% + 8px);
  left:          50%;
  transform:     translateX(-50%);
  background:    var(--bga);
  border:        1px solid var(--bdh);
  border-radius: var(--r);
  padding:       7px 9px;
  font-size:     10px;
  white-space:   nowrap;
  pointer-events: none;
  opacity:       0;
  transition:    opacity var(--tr-f);
  z-index:       200;
  min-width:     140px;
}
.xb-snap:hover .xb-snap-tip { opacity: 1; }
.xb-snap-tip-hash {
  font-family: var(--font-mono);
  font-size:   9px;
  color:       var(--grn);
  margin-bottom: 2px;
}
.xb-snap-tip-sum  { color: var(--txt); margin-bottom: 2px; }
.xb-snap-tip-meta { color: var(--txt2); font-size: 9px; }
.xb-snap-tip-btn {
  margin-top:    5px;
  width:         100%;
  background:    rgba(255,255,255,.04);
  border:        1px solid var(--bd);
  border-radius: var(--rs);
  color:         var(--txt2);
  font-size:     9px;
  padding:       2px 0;
  cursor:        pointer;
  font-family:   inherit;
  transition:    all var(--tr-f);
  pointer-events: auto;
}
.xb-snap-tip-btn:hover {
  border-color: rgba(239,68,68,.4);
  color:        var(--red);
  background:   rgba(239,68,68,.06);
}
/* Rollback confirm modal */
.xb-rb-modal {
  position:        fixed;
  inset:           0;
  background:      rgba(0,0,0,.6);
  display:         flex;
  align-items:     center;
  justify-content: center;
  z-index:         1000;
  backdrop-filter: blur(4px);
}
.xb-rb-card {
  background:    var(--bgc);
  border:        1px solid var(--bdh);
  border-radius: var(--rl);
  padding:       20px 24px;
  max-width:     360px;
  width:         90%;
  animation:     fade-in 150ms ease-out;
}
.xb-rb-title {
  font-size:     13px;
  font-weight:   600;
  color:         var(--txt);
  margin-bottom: 8px;
}
.xb-rb-body {
  font-size:     11px;
  color:         var(--txt2);
  margin-bottom: 16px;
  line-height:   1.6;
}
.xb-rb-hash {
  font-family: var(--font-mono);
  color:       var(--grn);
  font-size:   10px;
}
.xb-rb-btns {
  display:   flex;
  gap:       8px;
  justify-content: flex-end;
}
.xb-rb-cancel {
  background:    rgba(255,255,255,.04);
  border:        1px solid var(--bd);
  border-radius: var(--rs);
  color:         var(--txt2);
  font-size:     11px;
  padding:       5px 14px;
  cursor:        pointer;
  font-family:   inherit;
  transition:    all var(--tr-f);
}
.xb-rb-cancel:hover { border-color: var(--bdh); color: var(--txt); }
.xb-rb-confirm {
  background:    rgba(239,68,68,.12);
  border:        1px solid rgba(239,68,68,.3);
  border-radius: var(--rs);
  color:         var(--red);
  font-size:     11px;
  font-weight:   600;
  padding:       5px 14px;
  cursor:        pointer;
  font-family:   inherit;
  transition:    all var(--tr-f);
}
.xb-rb-confirm:hover {
  background: rgba(239,68,68,.22);
  border-color: rgba(239,68,68,.5);
}
`;

interface BottomBarDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
  client:   BuilderClient;
}

export class BottomBar {
  private readonly _deps: BottomBarDeps;
  private _el!: HTMLElement;
  private _snapsEl!: HTMLElement;
  private _verLblEl!: HTMLElement;
  private _metaEl!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: BottomBarDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = this._build();
    container.appendChild(this._el);

    this._unsubs.push(
      this._deps.cgsStore.subscribe(state => this._update(state)),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _build(): HTMLElement {
    const root = el('div', 'xb-bottom-bar');

    // Drag handle
    const drag = el('div', 'xb-bb-drag');
    drag.appendChild(el('div', 'xb-bb-drag-pip'));
    root.appendChild(drag);

    // Header
    const head = el('div', 'xb-bb-head');
    head.appendChild(el('span', 'xb-bb-title', { textContent: 'Version Timeline' }));
    this._metaEl = el('span', 'xb-bb-meta', { textContent: '0 snapshots' });
    head.appendChild(this._metaEl);
    this._verLblEl = el('span', 'xb-bb-ver-lbl', { textContent: '—' });
    head.appendChild(this._verLblEl);
    root.appendChild(head);

    // Body / timeline
    const body = el('div', 'xb-bb-body');
    const wrap = el('div', 'xb-tl-wrap');
    wrap.appendChild(el('div', 'xb-tl-line'));
    this._snapsEl = el('div', 'xb-tl-snaps');
    wrap.appendChild(this._snapsEl);
    body.appendChild(wrap);
    root.appendChild(body);

    return root;
  }

  private _update(state: import('../state/cgs_store').CGSStoreState): void {
    const snaps   = state.snapshots;
    const current = state.hash;

    this._metaEl.textContent = `${snaps.length} snapshot${snaps.length !== 1 ? 's' : ''}`;

    // Version label
    const latest = snaps[0];
    if (latest) {
      const d  = new Date(latest.timestamp * 1000);
      const ts = this._relativeTime(d);
      this._verLblEl.textContent =
        `v${latest.schema_version} · ${latest.summary || 'mutation'} · ${ts}`;
    } else {
      this._verLblEl.textContent = `v${state.version}`;
    }

    // Render snapshot dots (newest left)
    this._snapsEl.innerHTML = '';
    const toShow = snaps.slice(0, 20); // max 20 dots visible

    for (const snap of toShow) {
      const isCur  = snap.cgs_hash === current;
      const dot    = this._makeSnapDot(snap, isCur);
      this._snapsEl.appendChild(dot);
    }

    // Empty state
    if (toShow.length === 0) {
      const empty = el('span', '', {
        textContent: 'No snapshots yet — apply a mutation to create the first.',
        style: 'font-size:10px;color:var(--txt3);',
      });
      this._snapsEl.appendChild(empty);
    }
  }

  private _makeSnapDot(snap: CGSSnapshot, isCurrent: boolean): HTMLElement {
    const bump   = snap.version_bump ?? 'patch';
    const snap_  = el('div', `xb-snap${isCurrent ? ' current' : ''}`);

    const dot = el('div', `xb-snap-dot ${bump}`);
    snap_.appendChild(dot);

    // Labels
    snap_.appendChild(el('div', 'xb-snap-ver', {
      textContent: `v${snap.schema_version}`,
    }));
    const d  = new Date(snap.timestamp * 1000);
    snap_.appendChild(el('div', 'xb-snap-time', {
      textContent: this._relativeTime(d),
    }));

    // Tooltip
    const tip = el('div', 'xb-snap-tip');
    tip.appendChild(el('div', 'xb-snap-tip-hash', {
      textContent: snap.cgs_hash.slice(0, 12) + '…',
    }));
    tip.appendChild(el('div', 'xb-snap-tip-sum', {
      textContent: snap.summary || '(no summary)',
    }));
    tip.appendChild(el('div', 'xb-snap-tip-meta', {
      textContent: `${bump} bump · risk: ${snap.risk_level ?? 'low'}`,
    }));

    if (!isCurrent) {
      const rbBtn = el('button', 'xb-snap-tip-btn', { textContent: '↩ Rollback to this' });
      rbBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._confirmRollback(snap);
      });
      tip.appendChild(rbBtn);
    } else {
      tip.appendChild(el('div', 'xb-snap-tip-meta', {
        textContent: '● current version',
        style: 'color:var(--cyan)',
      }));
    }

    snap_.appendChild(tip);
    return snap_;
  }

  private _confirmRollback(snap: CGSSnapshot): void {
    const modal = el('div', 'xb-rb-modal');
    const card  = el('div', 'xb-rb-card');

    card.appendChild(el('div', 'xb-rb-title', {
      textContent: 'Roll back to this version?',
    }));

    const body = el('div', 'xb-rb-body');
    body.innerHTML =
      `This will replace the current CGS with snapshot<br>` +
      `<span class="xb-rb-hash">${snap.cgs_hash}</span><br>` +
      `<em>"${snap.summary || '(no summary)'}"</em><br>` +
      `All unsaved changes will be lost.`;
    card.appendChild(body);

    const btns   = el('div', 'xb-rb-btns');
    const cancel = el('button', 'xb-rb-cancel', { textContent: 'Cancel' });
    const confirm = el('button', 'xb-rb-confirm', { textContent: '↩ Rollback' });

    cancel.addEventListener('click', () => modal.remove());
    confirm.addEventListener('click', () => {
      this._deps.client.send({
        type:        'cgs_rollback',
        target_hash: snap.cgs_hash,
        session_id:  this._deps.client.sessionId,
      });
      modal.remove();
    });

    btns.appendChild(cancel);
    btns.appendChild(confirm);
    card.appendChild(btns);
    modal.appendChild(card);
    document.body.appendChild(modal);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.remove();
    });
  }

  private _relativeTime(d: Date): string {
    const sec = Math.floor((Date.now() - d.getTime()) / 1000);
    if (sec < 60)    return 'just now';
    if (sec < 3600)  return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-bottombar-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-bottombar-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}

function el(tag: string, cls: string, attrs: Record<string, string> = {}): HTMLElement {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'textContent') e.textContent = v;
    else if (k === 'innerHTML') e.innerHTML = v;
    else if (k === 'style') e.setAttribute('style', v);
    else e.setAttribute(k, v);
  }
  return e;
}