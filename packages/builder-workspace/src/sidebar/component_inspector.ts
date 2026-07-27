/**
 * component_inspector.ts — Component Field Inspector (Sidebar)
 *
 * Lightweight read-only field viewer shown in the left sidebar when
 * a component is selected in the entity tree.
 *
 * THE GOLDEN RULE enforced here:
 *   Every field has a small [→] affordance button.
 *   Clicking [→] pre-fills the prompt bar: "Set {actor}.{component}.{field}"
 *   Nothing is directly editable. ALL mutations go through PIL.
 *
 * Also shows:
 *   - Component name + type_id badge
 *   - Field name → Rust type (from the type mapping)
 *   - Current value with appropriate formatting
 *   - "Affected by N systems" derived info
 */

import type { CGSStore }    from '../state/cgs_store';
import type { UIStore }     from '../state/ui_store';
import type { CGSComponent, CGSFieldValue } from '../types/cgs';
import { allSystems }                       from '../types/cgs';

const STYLES = `
.xb-ci {
  padding:         8px 0;
  overflow-y:      auto;
  flex:            1;
}
.xb-ci-header {
  padding:         5px 10px 7px;
  border-bottom:   1px solid var(--bd);
  margin-bottom:   4px;
}
.xb-ci-name {
  font-size:       11px;
  font-weight:     600;
  color:           var(--txt);
  font-family:     var(--font-mono);
  display:         flex;
  align-items:     center;
  gap:             6px;
  margin-bottom:   3px;
}
.xb-ci-tid {
  font-size:       8px;
  padding:         1px 4px;
  border-radius:   3px;
  background:      rgba(255,255,255,.04);
  color:           var(--txt2);
  border:          1px solid var(--bd);
}
.xb-ci-affected {
  font-size:       9.5px;
  color:           var(--txt2);
}
.xb-ci-affected span { color: var(--vlt); }
.xb-ci-field {
  display:         flex;
  align-items:     center;
  padding:         3px 10px;
  gap:             6px;
  transition:      background var(--tr-f);
  position:        relative;
}
.xb-ci-field:hover { background: var(--bgh); }
.xb-ci-field-name {
  font-family:     var(--font-mono);
  font-size:       9.5px;
  color:           var(--txt2);
  min-width:       90px;
  flex-shrink:     0;
}
.xb-ci-field-val {
  font-family:     var(--font-mono);
  font-size:       10px;
  color:           var(--cyan);
  flex:            1;
}
.xb-ci-field-val.bool-true  { color: var(--grn); }
.xb-ci-field-val.bool-false { color: var(--red); }
.xb-ci-field-val.str-val    { color: var(--amb); }
.xb-ci-edit-btn {
  font-size:       9px;
  color:           var(--txt3);
  background:      none;
  border:          none;
  cursor:          pointer;
  padding:         1px 4px;
  border-radius:   var(--rs);
  opacity:         0;
  transition:      all var(--tr-f);
  font-family:     inherit;
  white-space:     nowrap;
}
.xb-ci-field:hover .xb-ci-edit-btn {
  opacity:         1;
  color:           var(--cyan);
}
.xb-ci-edit-btn:hover { background: var(--cynd); }
.xb-ci-readonly-note {
  padding:         8px 10px;
  font-size:       9.5px;
  color:           var(--txt3);
  font-style:      italic;
  border-top:      1px solid var(--bd);
  margin-top:      4px;
}
.xb-ci-empty {
  padding:         12px 10px;
  font-size:       10px;
  color:           var(--txt3);
  font-style:      italic;
}
`;

interface ComponentInspectorDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
}

export class ComponentInspector {
  private readonly _deps: ComponentInspectorDeps;
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: ComponentInspectorDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-ci';
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
    if (!sel || sel.kind !== 'component') {
      this._el.innerHTML = `<div class="xb-ci-empty">Select a component to inspect its fields.</div>`;
      return;
    }

    const typeId = parseInt(sel.id.replace('comp:', ''), 10);
    if (isNaN(typeId)) { this._el.innerHTML = ''; return; }

    const cgs  = this._deps.cgsStore.cgs;

    // Find the component across all actors
    let comp: CGSComponent | null = null;
    let actorId = '';
    for (const mode of cgs.modes) {
      for (const actor of mode.actors) {
        const c = actor.components.find(c => c.type_id === typeId);
        if (c) { comp = c; actorId = actor.id; break; }
      }
      if (comp) break;
    }

    if (!comp) {
      this._el.innerHTML = `<div class="xb-ci-empty">Component type_id=${typeId} not found.</div>`;
      return;
    }

    // Count systems affected
    const allSys     = allSystems(cgs);
    const readers    = allSys.filter(({ system }) => (system.reads as readonly number[]).includes(typeId));
    const writers    = allSys.filter(({ system }) => (system.writes as readonly number[]).includes(typeId));
    const affectedN  = new Set([...readers, ...writers].map(s => s.system.id)).size;

    const frag = document.createDocumentFragment();

    // Header
    const header = document.createElement('div');
    header.className = 'xb-ci-header';
    header.innerHTML = `
      <div class="xb-ci-name">
        ${comp.name}
        <span class="xb-ci-tid">type_id=${typeId}</span>
      </div>
      <div class="xb-ci-affected">
        Affected by <span>${affectedN} system${affectedN !== 1 ? 's' : ''}</span>
        (${readers.length} read, ${writers.length} write)
      </div>
    `;
    frag.appendChild(header);

    // Fields
    for (const [fieldName, value] of Object.entries(comp.defaults)) {
      frag.appendChild(this._fieldRow(fieldName, value, comp.name, actorId));
    }

    if (Object.keys(comp.defaults).length === 0) {
      const empty = document.createElement('div');
      empty.className   = 'xb-ci-empty';
      empty.textContent = 'No default fields defined.';
      frag.appendChild(empty);
    }

    // Read-only note
    const note = document.createElement('div');
    note.className   = 'xb-ci-readonly-note';
    note.textContent = 'Fields are read-only — click → to edit via prompt.';
    frag.appendChild(note);

    this._el.innerHTML = '';
    this._el.appendChild(frag);
  }

  private _fieldRow(
    fieldName: string,
    value:     CGSFieldValue,
    compName:  string,
    actorId:   string,
  ): HTMLElement {
    const row = document.createElement('div');
    row.className = 'xb-ci-field';

    const name = document.createElement('span');
    name.className   = 'xb-ci-field-name';
    name.textContent = fieldName;
    row.appendChild(name);

    const val = document.createElement('span');
    val.className = 'xb-ci-field-val';
    if (typeof value === 'boolean') {
      val.classList.add(value ? 'bool-true' : 'bool-false');
      val.textContent = String(value);
    } else if (typeof value === 'string') {
      val.classList.add('str-val');
      val.textContent = `"${value}"`;
    } else if (typeof value === 'number') {
      val.textContent = Number.isInteger(value) ? String(value) : value.toFixed(3);
    } else if (value === null) {
      val.textContent = 'null';
      val.style.color = 'var(--txt3)';
    } else {
      val.textContent = JSON.stringify(value);
      val.style.color = 'var(--txt2)';
    }
    row.appendChild(val);

    // Edit affordance
    const editBtn = document.createElement('button');
    editBtn.className   = 'xb-ci-edit-btn';
    editBtn.textContent = '→ edit';
    editBtn.title       = `Edit ${actorId}.${compName}.${fieldName} via prompt`;
    editBtn.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('xace:prefill-prompt', {
        detail: {
          text: `Set ${actorId} ${compName} ${fieldName} to `,
        },
      }));
    });
    row.appendChild(editBtn);

    return row;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-ci-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-ci-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}
