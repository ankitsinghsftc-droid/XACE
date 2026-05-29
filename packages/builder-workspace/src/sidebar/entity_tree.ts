/**
 * entity_tree.ts — Hierarchical CGS Entity Tree
 *
 * Renders the full CGS hierarchy as a collapsible tree:
 *   Mode ▾
 *     Entities ▾
 *       Actor (circle dot, size by component count)
 *         COMP_TRANSFORM_V1  [type_id badge]
 *         COMP_HEALTH_V1
 *     Systems ▾ (in entity tree for context)
 *     Rules ▾
 *   Global Systems ▾
 *
 * Clicking an actor or component selects it → entity_inspector updates.
 * Right-clicking opens the same context menu as the graph (edit via prompt, explain).
 * Search query (from ui_store) filters visible nodes in real-time.
 *
 * Component colors match the CGS graph color scheme.
 */

import type { CGSStore } from '../state/cgs_store';
import type { UIStore }  from '../state/ui_store';
import type { CGS, CGSActor, CGSComponent, CGSMode, CGSSystem } from '../types/cgs';

const ACTOR_DOT_COLOR: Record<string, string> = {
  PlayerCharacter: '#3b8bd4',
  Enemy:           '#993C1D',
  NPC:             '#8B8B22',
  Projectile:      '#185FA5',
  Obstacle:        '#4A4A4A',
  Collectible:     '#10b981',
  Environment:     '#2a3347',
  Trigger:         '#534AB7',
  Camera:          '#993C1D',
};

const COMP_COLORS: Record<number, string> = {
  1:  '#993C1D',   // TRANSFORM
  2:  '#3b8bd4',   // IDENTITY
  5:  '#534AB7',   // VELOCITY
  6:  '#185FA5',   // INPUT
  100:'#8B2222',   // HEALTH
  101:'#5F3A8B',   // DAMAGE
  160:'#3A7A5A',   // AI
};

const STYLES = `
.xb-tree {
  flex:            1;
  overflow-y:      auto;
  font-size:       10.5px;
  padding:         4px 0;
}
.xb-tree-section-lbl {
  font-size:       8.5px;
  font-weight:     700;
  letter-spacing:  .12em;
  color:           var(--txt3);
  text-transform:  uppercase;
  padding:         6px 10px 3px;
  display:         flex;
  align-items:     center;
  justify-content: space-between;
}
.xb-tree-add {
  color:           var(--txt3);
  font-size:       12px;
  cursor:          pointer;
  background:      none;
  border:          none;
  line-height:     1;
  transition:      color var(--tr-f);
}
.xb-tree-add:hover { color: var(--cyan); }
.xb-ti {
  display:         flex;
  align-items:     center;
  gap:             5px;
  padding:         3px 10px 3px 0;
  cursor:          pointer;
  border-left:     2px solid transparent;
  transition:      all var(--tr-f);
  user-select:     none;
}
.xb-ti:hover { background: var(--bgh); }
.xb-ti.selected {
  background:      rgba(0,212,255,.06);
  border-left-color: var(--cyan);
}
.xb-ti .chv {
  font-size:       9px;
  color:           var(--txt3);
  width:           12px;
  text-align:      center;
  flex-shrink:     0;
  transition:      transform var(--tr-f);
}
.xb-ti .chv.open { transform: rotate(0deg); }
.xb-ti-dot {
  width:           8px;
  height:          8px;
  border-radius:   50%;
  flex-shrink:     0;
}
.xb-ti-dot.sq { border-radius: 2px; }
.xb-ti-lbl {
  flex:            1;
  white-space:     nowrap;
  overflow:        hidden;
  text-overflow:   ellipsis;
  color:           var(--txt);
}
.xb-ti-lbl.mono {
  font-family:     var(--font-mono);
  font-size:       9.5px;
  color:           var(--txt2);
}
.xb-ti-tag {
  font-size:       8.5px;
  padding:         1px 5px;
  border-radius:   3px;
  flex-shrink:     0;
}
.tag-warn { background: rgba(255,159,67,.12); color: var(--amb); border: 1px solid rgba(255,159,67,.2); }
.tag-live { background: rgba(0,212,255,.1);   color: var(--cyan); border: 1px solid rgba(0,212,255,.18); }
.tag-new  { background: rgba(16,185,129,.1);  color: var(--grn);  border: 1px solid rgba(16,185,129,.2); }
.xb-ti-star { font-size: 9px; color: var(--grn); flex-shrink: 0; }
.xb-tree-empty {
  padding:         12px 14px;
  font-size:       10px;
  color:           var(--txt3);
  font-style:      italic;
}
`;

interface EntityTreeDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
}

export class EntityTree {
  private readonly _deps: EntityTreeDeps;
  private _el!:           HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: EntityTreeDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-tree';
    container.appendChild(this._el);

    this._unsubs.push(
      this._deps.cgsStore.subscribe(() => this._render()),
      this._deps.uiStore.select(s => s.sidebarSearch, () => this._render()),
      this._deps.uiStore.select(s => s.selectedEntity?.id, () => this._render()),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _render(): void {
    const cgs    = this._deps.cgsStore.cgs;
    const query  = this._deps.uiStore.state.sidebarSearch.toLowerCase().trim();
    const selId  = this._deps.uiStore.state.selectedEntity?.id;
    const expSec = this._deps.uiStore.state.expandedSections;

    if (!this._deps.cgsStore.isLoaded) {
      this._el.innerHTML = `<div class="xb-tree-empty">Loading…</div>`;
      return;
    }

    const frag = document.createDocumentFragment();

    // ── Modes ────────────────────────────────────────────────────────────
    for (const mode of cgs.modes) {
      const modeOpen = expSec.has(`mode:${mode.id}`);
      const modeRow  = this._modeRow(mode, modeOpen);
      frag.appendChild(modeRow);

      if (!modeOpen) continue;

      // Entities section
      const entOpen = expSec.has(`entities:${mode.id}`);
      frag.appendChild(this._sectionRow('Entities', `entities:${mode.id}`, entOpen, 14, true));
      if (entOpen) {
        for (const actor of mode.actors) {
          if (query && !actor.id.toLowerCase().includes(query)) continue;
          const actorId  = `actor:${mode.id}:${actor.id}`;
          const actorOpen = expSec.has(actorId);
          const isPlayer = actor.actor_type === 'PlayerCharacter';
          frag.appendChild(this._actorRow(actor, actorId, actorOpen, selId === actorId, isPlayer, 20));

          if (actorOpen) {
            for (const comp of actor.components) {
              const compId = `comp:${comp.type_id}`;
              frag.appendChild(this._compRow(comp, compId, selId === compId, 30));
            }
          }
        }
        if (mode.actors.length === 0) {
          frag.appendChild(this._emptyRow('No entities — use prompt to add', 20));
        }
      }

      // Systems section (condensed in tree)
      const sysOpen = expSec.has(`systems:${mode.id}`);
      frag.appendChild(this._sectionRow('Systems', `systems:${mode.id}`, sysOpen, 14, true));
      if (sysOpen) {
        for (const sys of mode.systems) {
          if (query && !sys.id.toLowerCase().includes(query)) continue;
          frag.appendChild(this._sysRow(sys, `sys:${mode.id}:${sys.id}`, selId === `sys:${mode.id}:${sys.id}`, 20));
        }
      }
    }

    // ── Global Systems ───────────────────────────────────────────────────
    if (cgs.global_systems.length > 0) {
      const gsOpen = expSec.has('global_systems');
      frag.appendChild(this._sectionRow('Global Systems', 'global_systems', gsOpen, 0, false));
      if (gsOpen) {
        for (const sys of cgs.global_systems) {
          if (query && !sys.id.toLowerCase().includes(query)) continue;
          frag.appendChild(this._sysRow(sys, `sys:global:${sys.id}`, selId === `sys:global:${sys.id}`, 10));
        }
      }
    }

    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }

  private _modeRow(mode: CGSMode, isOpen: boolean): HTMLElement {
    const row = this._ti(0);
    const chv = this._chv(isOpen);
    row.appendChild(chv);
    row.appendChild(this._dot('#00d4ff', false));
    const lbl = document.createElement('span');
    lbl.className   = 'xb-ti-lbl';
    lbl.style.fontWeight = '600';
    lbl.textContent = mode.id;
    row.appendChild(lbl);
    if (mode.is_default) row.appendChild(this._star());
    row.addEventListener('click', () => this._deps.uiStore.toggleSection(`mode:${mode.id}`));
    return row;
  }

  private _sectionRow(
    label: string, key: string, isOpen: boolean,
    indent: number, showAdd: boolean,
  ): HTMLElement {
    const row = document.createElement('div');
    row.className = 'xb-tree-section-lbl';
    row.style.paddingLeft = `${indent + 10}px`;

    const span = document.createElement('span');
    span.textContent = label;
    span.style.cursor = 'pointer';
    span.addEventListener('click', () => this._deps.uiStore.toggleSection(key));
    row.appendChild(span);

    if (showAdd) {
      const btn = document.createElement('button');
      btn.className   = 'xb-tree-add';
      btn.textContent = '+';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        // Pre-fill prompt with "add a new [label]"
        window.dispatchEvent(new CustomEvent('xace:prefill-prompt', {
          detail: { text: `Add a new ${label.toLowerCase().replace(/s$/, '')}` },
        }));
      });
      row.appendChild(btn);
    }

    return row;
  }

  private _actorRow(
    actor: CGSActor, nodeId: string, isOpen: boolean,
    isSelected: boolean, isPlayer: boolean, indent: number,
  ): HTMLElement {
    const row = this._ti(indent, isSelected);
    row.appendChild(this._chv(isOpen));
    const color = ACTOR_DOT_COLOR[actor.actor_type] ?? '#5a6880';
    row.appendChild(this._dot(color, false));
    const lbl = document.createElement('span');
    lbl.className   = 'xb-ti-lbl';
    lbl.textContent = actor.id;
    row.appendChild(lbl);
    if (isPlayer) row.appendChild(this._star());

    row.addEventListener('click', () => {
      this._deps.uiStore.selectEntity({
        id: nodeId, kind: 'actor', label: actor.id, modeId: nodeId.split(':')[1]!,
      });
      this._deps.uiStore.toggleSection(nodeId);
    });
    this._bindContextMenu(row, nodeId, actor.id);
    return row;
  }

  private _compRow(
    comp: CGSComponent, nodeId: string, isSelected: boolean, indent: number,
  ): HTMLElement {
    const row = this._ti(indent, isSelected);
    const color = COMP_COLORS[comp.type_id] ?? '#5a6880';
    row.appendChild(this._pad(12));
    row.appendChild(this._dot(color, true));
    const lbl = document.createElement('span');
    lbl.className   = 'xb-ti-lbl mono';
    lbl.textContent = comp.name;
    row.appendChild(lbl);

    row.addEventListener('click', () => {
      this._deps.uiStore.selectEntity({
        id: nodeId, kind: 'component', label: comp.name, modeId: '',
      });
    });
    this._bindContextMenu(row, nodeId, comp.name);
    return row;
  }

  private _sysRow(
    sys: CGSSystem, nodeId: string, isSelected: boolean, indent: number,
  ): HTMLElement {
    const row = this._ti(indent, isSelected);
    row.appendChild(this._pad(12));
    row.appendChild(this._dot('#a855f7', false));
    const lbl = document.createElement('span');
    lbl.className   = 'xb-ti-lbl';
    lbl.textContent = sys.id;
    row.appendChild(lbl);

    const tag = document.createElement('span');
    tag.className   = 'xb-ti-tag tag-live';
    tag.textContent = sys.phase.slice(0, 3).toLowerCase();
    row.appendChild(tag);

    row.addEventListener('click', () => {
      this._deps.uiStore.selectEntity({
        id: nodeId, kind: 'system', label: sys.id, modeId: '',
      });
    });
    return row;
  }

  private _emptyRow(text: string, indent: number): HTMLElement {
    const e = document.createElement('div');
    e.className = 'xb-tree-empty';
    e.style.paddingLeft = `${indent + 10}px`;
    e.textContent = text;
    return e;
  }

  private _ti(indent: number, selected = false): HTMLElement {
    const row = document.createElement('div');
    row.className = `xb-ti${selected ? ' selected' : ''}`;
    row.style.paddingLeft = `${indent + 10}px`;
    return row;
  }

  private _chv(open: boolean): HTMLElement {
    const s = document.createElement('span');
    s.className = `chv${open ? ' open' : ''}`;
    s.textContent = open ? '▾' : '▶';
    return s;
  }

  private _dot(color: string, square: boolean): HTMLElement {
    const d = document.createElement('div');
    d.className = `xb-ti-dot${square ? ' sq' : ''}`;
    d.style.background = color;
    return d;
  }

  private _star(): HTMLElement {
    const s = document.createElement('span');
    s.className   = 'xb-ti-star';
    s.textContent = '★';
    s.title       = 'Primary entity';
    return s;
  }

  private _pad(w: number): HTMLElement {
    const p = document.createElement('span');
    p.style.cssText = `width:${w}px;flex-shrink:0;display:inline-block`;
    return p;
  }

  private _bindContextMenu(el: HTMLElement, nodeId: string, label: string): void {
    el.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent('xace:prefill-prompt', {
        detail: { nodeId, nodeLabel: label },
      }));
    });
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-tree-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-tree-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}