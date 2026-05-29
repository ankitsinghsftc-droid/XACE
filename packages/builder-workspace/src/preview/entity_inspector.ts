/**
 * entity_inspector.ts — Right Panel Entity Inspector
 *
 * Shows the full component breakdown of the currently selected entity.
 * Mirrors the sidebar's ComponentInspector but full-width with richer display:
 *   - Actor header: name, type, control_type badge
 *   - Each component as a collapsible section
 *   - Each field: name → value → [→ edit] button
 *   - AI state display (for AI actors)
 *   - "Edit via Prompt" header button — pre-fills the bar with actor name
 *
 * THE GOLDEN RULE enforced here:
 *   No field is directly editable. Every field has [→ edit].
 *   The bottom note "Read-only — edit via prompt only." is persistent
 *   and styled prominently, not as an afterthought footnote.
 */

import type { CGSStore }    from '../state/cgs_store';
import type { UIStore }     from '../state/ui_store';
import type { CGSActor, CGSComponent, CGSFieldValue } from '../types/cgs';
import { allActors, allSystems } from '../types/cgs';

const STYLES = `
.xb-ins { display: flex; flex-direction: column; overflow: hidden; flex: 1; }
.xb-ins-head {
  padding:      5px 9px;
  border-bottom: 1px solid var(--bd);
  display:      flex;
  align-items:  center;
  gap:          6px;
  flex-shrink:  0;
}
.xb-ins-entity-name {
  font-size:  12px;
  font-weight: 600;
  color:      var(--txt);
  flex:       1;
  overflow:   hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor:     pointer;
}
.xb-ins-edit-btn {
  font-size:    9.5px;
  color:        var(--vlt);
  border:       1px solid rgba(168,85,247,.25);
  padding:      2px 8px;
  border-radius: 3px;
  cursor:       pointer;
  background:   transparent;
  transition:   all var(--tr-f);
  font-family:  inherit;
  flex-shrink:  0;
}
.xb-ins-edit-btn:hover { background: var(--vltd); border-color: var(--vlt); }
.xb-ins-scroll { flex: 1; overflow-y: auto; }
.xb-ins-section {
  border-bottom: 1px solid var(--bd);
}
.xb-ins-section-hd {
  padding:      5px 9px;
  display:      flex;
  align-items:  center;
  gap:          6px;
  cursor:       pointer;
  transition:   background var(--tr-f);
  user-select:  none;
}
.xb-ins-section-hd:hover { background: rgba(255,255,255,.02); }
.xb-ins-comp-icon {
  width:           13px;
  height:          13px;
  border-radius:   3px;
  display:         flex;
  align-items:     center;
  justify-content: center;
  font-size:       8px;
  font-weight:     700;
  flex-shrink:     0;
}
.xb-ins-comp-name {
  font-size:  11px;
  font-weight: 600;
  color:      var(--txt);
  flex:       1;
}
.xb-ins-comp-tag {
  font-size:    8.5px;
  padding:      1px 4px;
  border-radius: 3px;
  background:   rgba(255,255,255,.04);
  color:        var(--txt2);
  border:       1px solid var(--bd);
}
.xb-ins-chv {
  font-size:  9px;
  color:      var(--txt2);
  flex-shrink: 0;
  transition: transform var(--tr-f);
}
.xb-ins-chv.open { transform: rotate(0deg); }
.xb-ins-body { padding: 5px 9px 7px; }
.xb-ins-field {
  display:      flex;
  align-items:  center;
  padding:      2.5px 0;
  gap:          6px;
  position:     relative;
}
.xb-ins-field:hover .xb-ins-field-edit { opacity: 1; }
.xb-ins-field-name {
  font-family:  var(--font-mono);
  font-size:    9.5px;
  color:        var(--txt2);
  min-width:    100px;
  flex-shrink:  0;
}
.xb-ins-field-val {
  font-family:  var(--font-mono);
  font-size:    10px;
  color:        var(--cyan);
  flex:         1;
}
.xb-ins-field-val.live { animation: pulse-dot .5s ease-out; }
.xb-ins-field-val.t-bool-true  { color: var(--grn); }
.xb-ins-field-val.t-bool-false { color: var(--red); }
.xb-ins-field-val.t-str        { color: var(--amb); }
.xb-ins-field-edit {
  font-size:    9px;
  color:        var(--txt3);
  background:   none;
  border:       none;
  cursor:       pointer;
  padding:      1px 4px;
  border-radius: var(--rs);
  opacity:      0;
  transition:   all var(--tr-f);
  font-family:  inherit;
}
.xb-ins-field-edit:hover { background: var(--cynd); color: var(--cyan); }
/* Health bar for health components */
.xb-ins-hpbar {
  margin-top:   4px;
  height:       3px;
  background:   rgba(255,255,255,.05);
  border-radius: 2px;
  overflow:     hidden;
}
.xb-ins-hpbar-fill {
  height:       100%;
  border-radius: 2px;
  background:   linear-gradient(90deg, var(--grn), var(--cyan));
  transition:   width 400ms ease-out;
}
/* AI state badges */
.xb-ins-ai-states {
  display:      flex;
  gap:          4px;
  flex-wrap:    wrap;
  margin-top:   3px;
}
.xb-ins-ai-state {
  padding:      2px 7px;
  border-radius: 20px;
  font-size:    9px;
  border:       1px solid var(--bd);
  color:        var(--txt2);
}
.xb-ins-ai-state.active {
  border-color: rgba(0,212,255,.38);
  color:        var(--cyan);
  background:   var(--cynd);
}
.xb-ins-readonly-note {
  padding:      8px 9px;
  font-size:    9.5px;
  color:        var(--txt3);
  text-align:   center;
  border-top:   1px solid var(--bd);
  flex-shrink:  0;
  background:   rgba(0,0,0,.1);
}
.xb-ins-empty {
  padding:      20px 12px;
  font-size:    10.5px;
  color:        var(--txt2);
  text-align:   center;
  line-height:  1.7;
}
`;

const COMP_ICON_COLORS: Record<string, { bg: string; fg: string; letter: string }> = {
  COMP_TRANSFORM_V1: { bg: 'rgba(153,60,29,.15)', fg: '#993C1D', letter: 'T' },
  COMP_HEALTH_V1:    { bg: 'rgba(139,34,34,.15)', fg: '#8B2222', letter: 'H' },
  COMP_VELOCITY_V1:  { bg: 'rgba(83,74,183,.15)', fg: '#534AB7', letter: 'V' },
  COMP_AI_V1:        { bg: 'rgba(58,122,90,.15)', fg: '#3A7A5A', letter: 'A' },
  COMP_RENDER_V1:    { bg: 'rgba(24,95,165,.15)', fg: '#185FA5', letter: 'R' },
};

interface InspectorDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
}

export class EntityInspector {
  private readonly _deps:    InspectorDeps;
  private _el!:              HTMLElement;
  private _expandedComps:    Set<string> = new Set();
  private readonly _unsubs:  Array<() => void> = [];

  constructor(deps: InspectorDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-ins';
    container.appendChild(this._el);

    this._unsubs.push(
      this._deps.uiStore.select(s => s.selectedEntity?.id, () => this._render()),
      this._deps.cgsStore.subscribe(() => this._render()),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _render(): void {
    const sel = this._deps.uiStore.state.selectedEntity;
    const cgs = this._deps.cgsStore.cgs;

    if (!sel || sel.kind !== 'actor') {
      this._renderEmpty(sel?.label);
      return;
    }

    // Find the actor
    const located = allActors(cgs).find(({ actor }) => actor.id === sel.label || `actor:${sel.modeId}:${actor.id}` === sel.id);
    if (!located) { this._renderEmpty(); return; }

    const { actor, modeId } = located;

    const frag = document.createDocumentFragment();

    // Header
    const head = document.createElement('div');
    head.className = 'xb-ins-head';

    const nameEl = document.createElement('div');
    nameEl.className   = 'xb-ins-entity-name';
    nameEl.textContent = actor.id;
    nameEl.title       = `${actor.actor_type} · ${actor.control_type}`;
    head.appendChild(nameEl);

    const editBtn = document.createElement('button');
    editBtn.className   = 'xb-ins-edit-btn';
    editBtn.textContent = 'Edit via Prompt';
    editBtn.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('xace:prefill-prompt', {
        detail: { text: `Modify ${actor.id}: ` },
      }));
    });
    head.appendChild(editBtn);
    frag.appendChild(head);

    // Scroll body
    const scroll = document.createElement('div');
    scroll.className = 'xb-ins-scroll';

    // Actor meta row
    const metaRow = document.createElement('div');
    metaRow.style.cssText = 'padding:4px 9px;display:flex;gap:6px;border-bottom:1px solid var(--bd)';
    metaRow.innerHTML = `
      <span style="font-size:9px;padding:1px 5px;border-radius:3px;background:rgba(0,212,255,.07);color:var(--txt2);border:1px solid var(--bd)">${actor.actor_type}</span>
      <span style="font-size:9px;padding:1px 5px;border-radius:3px;background:rgba(255,255,255,.03);color:var(--txt2);border:1px solid var(--bd)">${actor.control_type}</span>
      <span style="font-size:9px;color:var(--txt3);margin-left:auto">${actor.components.length} components</span>
    `;
    scroll.appendChild(metaRow);

    // Components
    for (const comp of actor.components) {
      scroll.appendChild(this._buildCompSection(comp, actor.id));
    }

    frag.appendChild(scroll);

    // Read-only note
    const note = document.createElement('div');
    note.className   = 'xb-ins-readonly-note';
    note.textContent = 'Read-only — all edits through the prompt bar.';
    frag.appendChild(note);

    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }

  private _buildCompSection(comp: CGSComponent, actorId: string): HTMLElement {
    const section = document.createElement('div');
    section.className = 'xb-ins-section';

    const iconInfo  = COMP_ICON_COLORS[comp.name] ?? { bg: 'rgba(255,255,255,.05)', fg: '#5a6880', letter: '?' };
    const isExpanded = this._expandedComps.has(comp.name) || comp.name.includes('HEALTH') || comp.name.includes('VELOCITY');

    // Section header
    const hd = document.createElement('div');
    hd.className = 'xb-ins-section-hd';

    const icon = document.createElement('div');
    icon.className = 'xb-ins-comp-icon';
    icon.style.background = iconInfo.bg;
    icon.style.color      = iconInfo.fg;
    icon.textContent      = iconInfo.letter;
    hd.appendChild(icon);

    const name = document.createElement('div');
    name.className   = 'xb-ins-comp-name';
    name.textContent = comp.name;
    hd.appendChild(name);

    const tag = document.createElement('span');
    tag.className   = 'xb-ins-comp-tag';
    tag.textContent = `id:${comp.type_id}`;
    hd.appendChild(tag);

    const chv = document.createElement('span');
    chv.className   = `xb-ins-chv${isExpanded ? ' open' : ''}`;
    chv.textContent = isExpanded ? '▾' : '▶';
    hd.appendChild(chv);

    section.appendChild(hd);

    // Body
    const body = document.createElement('div');
    body.className    = 'xb-ins-body';
    body.style.display = isExpanded ? 'block' : 'none';

    for (const [fieldName, value] of Object.entries(comp.defaults)) {
      body.appendChild(this._fieldRow(fieldName, value, comp.name, actorId));
    }

    // Health bar for health components
    if (comp.name.includes('HEALTH')) {
      const cur = comp.defaults['current'] as number ?? 0;
      const max = comp.defaults['max'] as number ?? 100;
      const pct = max > 0 ? Math.max(0, Math.min(100, (cur / max) * 100)) : 0;
      const bar = document.createElement('div');
      bar.className = 'xb-ins-hpbar';
      const fill = document.createElement('div');
      fill.className    = 'xb-ins-hpbar-fill';
      fill.style.width  = `${pct}%`;
      bar.appendChild(fill);
      body.appendChild(bar);
    }

    // AI states
    if (comp.name.includes('AI')) {
      const behavior = comp.defaults['behavior_model'] as string ?? 'CHASE';
      const states   = ['Patrol', 'Idle', 'Chase', 'Attack'];
      const wrap     = document.createElement('div');
      wrap.className = 'xb-ins-ai-states';
      for (const s of states) {
        const badge = document.createElement('div');
        badge.className   = `xb-ins-ai-state${s.toUpperCase() === behavior ? ' active' : ''}`;
        badge.textContent = s;
        wrap.appendChild(badge);
      }
      body.appendChild(wrap);
      const aiNote = document.createElement('div');
      aiNote.style.cssText = 'font-size:9px;color:var(--txt3);margin-top:4px;font-style:italic';
      aiNote.textContent   = 'Read-only. Edit via prompt only.';
      body.appendChild(aiNote);
    }

    section.appendChild(body);

    // Toggle expand/collapse
    hd.addEventListener('click', () => {
      const expanded = body.style.display !== 'none';
      body.style.display = expanded ? 'none' : 'block';
      chv.textContent    = expanded ? '▶' : '▾';
      chv.classList.toggle('open', !expanded);
      if (expanded) this._expandedComps.delete(comp.name);
      else this._expandedComps.add(comp.name);
    });

    return section;
  }

  private _fieldRow(
    fieldName: string,
    value:     CGSFieldValue,
    compName:  string,
    actorId:   string,
  ): HTMLElement {
    const row  = document.createElement('div');
    row.className = 'xb-ins-field';

    const name = document.createElement('span');
    name.className   = 'xb-ins-field-name';
    name.textContent = fieldName;
    row.appendChild(name);

    const val = document.createElement('span');
    val.className = 'xb-ins-field-val';
    if (typeof value === 'boolean') {
      val.classList.add(value ? 't-bool-true' : 't-bool-false');
      val.textContent = String(value);
    } else if (typeof value === 'string') {
      val.classList.add('t-str');
      val.textContent = `"${value}"`;
    } else if (typeof value === 'number') {
      val.textContent = Number.isInteger(value) ? String(value) : value.toFixed(3);
    } else {
      val.textContent = JSON.stringify(value);
      val.style.color = 'var(--txt2)';
    }
    row.appendChild(val);

    const editBtn = document.createElement('button');
    editBtn.className   = 'xb-ins-field-edit';
    editBtn.textContent = '→ edit';
    editBtn.title       = `Edit ${actorId}.${compName}.${fieldName}`;
    editBtn.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('xace:prefill-prompt', {
        detail: { text: `Set ${actorId} ${compName} ${fieldName} to ` },
      }));
    });
    row.appendChild(editBtn);

    return row;
  }

  private _renderEmpty(label?: string): void {
    this._el.innerHTML = `
      <div class="xb-ins-empty">
        ${label
          ? `<strong style="color:var(--txt)">${label}</strong><br><span style="color:var(--txt3);font-size:9.5px">${label.startsWith('sys:') ? 'System — select an actor to inspect fields.' : 'Select an actor to inspect its component fields.'}</span>`
          : `<div style="font-size:22px;margin-bottom:8px;color:var(--txt3)">◎</div>
             Select an entity from the explorer or graph<br>
             <span style="color:var(--txt3);font-size:9.5px">to inspect its component fields</span>`}
      </div>
    `;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-ins-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-ins-styles'; s.textContent = STYLES;
    document.head.appendChild(s);
  }
}