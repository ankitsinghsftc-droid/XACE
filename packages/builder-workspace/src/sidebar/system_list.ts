/**
 * system_list.ts — System Registry sidebar view
 * Grouped by execution phase. Read/write type_ids shown inline.
 */

import type { CGSStore } from '../state/cgs_store';
import type { UIStore }  from '../state/ui_store';
import { allSystems }    from '../types/cgs';

const PHASE_COLOR: Record<string, string> = {
  Input:          'var(--cyan)',
  Simulation:     'var(--vlt)',
  PostSimulation: 'var(--amb)',
  Render:         'var(--grn)',
};

export class SystemList {
  private readonly _deps: { cgsStore: CGSStore; uiStore: UIStore };
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: { cgsStore: CGSStore; uiStore: UIStore }) {
    this._deps = deps;
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'flex:1;overflow-y:auto;font-size:10.5px;padding:4px 0';
    container.appendChild(this._el);
    this._unsubs.push(
      this._deps.cgsStore.subscribe(() => this._render()),
      this._deps.uiStore.select(s => s.selectedEntity?.id, () => this._render()),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _render(): void {
    const cgs    = this._deps.cgsStore.cgs;
    const selId  = this._deps.uiStore.state.selectedEntity?.id;
    const query  = this._deps.uiStore.state.sidebarSearch.toLowerCase();
    const phases = ['Input', 'Simulation', 'PostSimulation', 'Render'];
    const frag   = document.createDocumentFragment();

    for (const phase of phases) {
      const sys = allSystems(cgs).filter(
        ({ system }) =>
          system.phase === phase &&
          (!query || system.id.toLowerCase().includes(query))
      );
      if (sys.length === 0) continue;

      const lbl = document.createElement('div');
      lbl.style.cssText = `font-size:8.5px;font-weight:700;letter-spacing:.12em;color:${PHASE_COLOR[phase] ?? 'var(--txt3)'};text-transform:uppercase;padding:6px 10px 3px`;
      lbl.textContent   = phase;
      frag.appendChild(lbl);

      for (const { system, modeId } of sys) {
        const nodeId   = `sys:${modeId}:${system.id}`;
        const isSel    = selId === nodeId;
        const row      = document.createElement('div');
        row.style.cssText = `display:flex;align-items:center;gap:5px;padding:4px 10px;cursor:pointer;
          border-left:2px solid ${isSel ? 'var(--vlt)' : 'transparent'};
          background:${isSel ? 'rgba(168,85,247,.06)' : 'transparent'};
          transition:all 120ms`;
        row.addEventListener('click', () => {
          this._deps.uiStore.selectEntity({ id: nodeId, kind: 'system', label: system.id, modeId });
        });

        const dot = document.createElement('div');
        dot.style.cssText = `width:7px;height:7px;border-radius:50%;background:var(--vlt);flex-shrink:0`;
        row.appendChild(dot);

        const text = document.createElement('span');
        text.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt)';
        text.textContent   = system.id;
        row.appendChild(text);

        const rw = document.createElement('span');
        rw.style.cssText = 'font-family:var(--font-mono);font-size:9px;color:var(--txt3)';
        rw.textContent   = `R:${system.reads.length} W:${system.writes.length}`;
        row.appendChild(rw);

        frag.appendChild(row);
      }
    }

    if (!frag.childNodes.length) {
      const e = document.createElement('div');
      e.style.cssText = 'padding:12px 10px;font-size:10px;color:var(--txt3);font-style:italic';
      e.textContent   = 'No systems found.';
      frag.appendChild(e);
    }

    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }
}


/**
 * rule_browser.ts — Rule Browser sidebar view
 * Shows rule ID, condition, effect, priority badge.
 */
export class RuleBrowser {
  private readonly _deps: { cgsStore: CGSStore; uiStore: UIStore };
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: { cgsStore: CGSStore; uiStore: UIStore }) {
    this._deps = deps;
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'flex:1;overflow-y:auto;padding:4px 0';
    container.appendChild(this._el);
    this._unsubs.push(this._deps.cgsStore.subscribe(() => this._render()));
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _render(): void {
    const cgs  = this._deps.cgsStore.cgs;
    const frag = document.createDocumentFragment();

    for (const mode of cgs.modes) {
      for (const rule of mode.rules) {
        const card = document.createElement('div');
        card.style.cssText = `
          margin:4px 8px;padding:7px 9px;
          background:var(--bgc);border:1px solid var(--bd);border-radius:var(--r);
          cursor:pointer;transition:all 120ms;
        `;
        card.addEventListener('mouseenter', () => { card.style.borderColor = 'var(--bdh)'; });
        card.addEventListener('mouseleave', () => { card.style.borderColor = 'var(--bd)'; });
        card.addEventListener('click', () => {
          this._deps.uiStore.selectEntity({
            id: `rule:${mode.id}:${rule.id}`, kind: 'rule',
            label: rule.id, modeId: mode.id,
          });
        });

        card.innerHTML = `
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
            <span style="color:var(--grn);font-size:10px">◇</span>
            <span style="font-size:11px;font-weight:600;color:var(--txt);flex:1">${rule.id}</span>
            <span style="font-size:8px;padding:1px 4px;border-radius:3px;
              background:rgba(255,255,255,.04);color:var(--txt2);border:1px solid var(--bd)">
              p${rule.priority}
            </span>
            <span style="font-size:8px;padding:1px 4px;border-radius:3px;
              background:${rule.is_active ? 'rgba(16,185,129,.1)' : 'rgba(255,255,255,.03)'};
              color:${rule.is_active ? 'var(--grn)' : 'var(--txt3)'};
              border:1px solid ${rule.is_active ? 'rgba(16,185,129,.2)' : 'var(--bd)'}">
              ${rule.is_active ? 'active' : 'inactive'}
            </span>
          </div>
          <div style="font-family:var(--font-mono);font-size:9.5px;color:var(--txt2);margin-bottom:2px">
            when: <span style="color:var(--amb)">${rule.condition}</span>
          </div>
          <div style="font-family:var(--font-mono);font-size:9.5px;color:var(--txt2)">
            then: <span style="color:var(--cyan)">${rule.effect}</span>
          </div>
        `;
        frag.appendChild(card);
      }
    }

    if (!frag.childNodes.length) {
      const e = document.createElement('div');
      e.style.cssText = 'padding:12px 10px;font-size:10px;color:var(--txt3);font-style:italic';
      e.textContent   = 'No rules defined. Use prompt to add one.';
      frag.appendChild(e);
    }

    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }
}


/**
 * version_timeline.ts — Compact version history sidebar view
 * Shows the last 20 snapshots in a scrollable list with rollback buttons.
 */
export class VersionTimeline {
  private readonly _deps: { cgsStore: CGSStore; uiStore: UIStore; client: import('../api/builder_client').BuilderClient };
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: { cgsStore: CGSStore; uiStore: UIStore; client: import('../api/builder_client').BuilderClient }) {
    this._deps = deps;
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'flex:1;overflow-y:auto;padding:4px 0';
    container.appendChild(this._el);
    this._unsubs.push(this._deps.cgsStore.subscribe(() => this._render()));
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _render(): void {
    const snaps = this._deps.cgsStore.state.snapshots.slice(0, 20);
    const curH  = this._deps.cgsStore.hash;
    const frag  = document.createDocumentFragment();

    for (const snap of snaps) {
      const isCur  = snap.cgs_hash === curH;
      const bumpC  = { patch: 'var(--grn)', minor: 'var(--cyan)', major: 'var(--vlt)' }[snap.version_bump ?? 'patch'] ?? 'var(--txt3)';
      const d      = new Date((snap.timestamp ?? 0) * 1000);
      const ts     = `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;

      const row = document.createElement('div');
      row.style.cssText = `
        display:flex;align-items:flex-start;gap:8px;padding:6px 10px;
        background:${isCur ? 'rgba(0,212,255,.05)' : 'transparent'};
        border-left:2px solid ${isCur ? 'var(--cyan)' : 'transparent'};
        transition:all 120ms;cursor:pointer;
      `;
      row.addEventListener('mouseenter', () => {
        if (!isCur) row.style.background = 'var(--bgh)';
      });
      row.addEventListener('mouseleave', () => {
        row.style.background = isCur ? 'rgba(0,212,255,.05)' : 'transparent';
      });

      row.innerHTML = `
        <div style="width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:3px;
          background:${isCur ? 'var(--cyan)' : bumpC};
          ${isCur ? 'box-shadow:0 0 6px var(--cyan)' : ''}">
        </div>
        <div style="flex:1;min-width:0">
          <div style="font-size:10px;color:${isCur ? 'var(--cyan)' : 'var(--txt)'};
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
            ${snap.summary || '(no summary)'}
          </div>
          <div style="font-size:9px;color:var(--txt3);font-family:var(--font-mono);margin-top:1px">
            v${snap.schema_version} · ${snap.version_bump ?? 'patch'} · ${ts}
          </div>
          <div style="font-size:8.5px;font-family:var(--font-mono);color:var(--grn);margin-top:1px">
            ${snap.cgs_hash.slice(0, 8)}…
          </div>
        </div>
        ${!isCur ? `<button
          style="font-size:8.5px;padding:1px 5px;background:rgba(255,255,255,.03);
          border:1px solid var(--bd);border-radius:var(--rs);color:var(--txt2);
          cursor:pointer;font-family:inherit;flex-shrink:0;margin-top:1px"
          data-hash="${snap.cgs_hash}">↩</button>` : ''}
      `;

      const btn = row.querySelector<HTMLButtonElement>('[data-hash]');
      btn?.addEventListener('click', (e) => {
        e.stopPropagation();
        this._deps.client.send({
          type: 'cgs_rollback',
          target_hash: snap.cgs_hash,
          session_id: this._deps.client.sessionId,
        });
      });

      frag.appendChild(row);
    }

    if (!snaps.length) {
      const e = document.createElement('div');
      e.style.cssText = 'padding:12px 10px;font-size:10px;color:var(--txt3);font-style:italic';
      e.textContent   = 'No version history yet.';
      frag.appendChild(e);
    }

    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }
}
