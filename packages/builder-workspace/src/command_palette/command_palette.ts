/**
 * command_palette.ts — Cmd+K Command Palette
 *
 * Global modal. Triggered by Cmd+K (wired in ui_store.ts).
 * Provides fuzzy search over all CGS nodes + built-in actions.
 *
 * Keyboard: ↑/↓ navigate, Enter select, Escape close.
 * Mouse: hover highlights, click selects.
 *
 * On selection:
 *   actor/component/system/rule → selectEntity in uiStore
 *   action → pre-fills prompt bar
 */

import { CGSSearchEngine }    from './search_engine';
import type { SearchResult }   from './search_engine';
import type { CGSStore }       from '../state/cgs_store';
import type { UIStore }        from '../state/ui_store';

const STYLES = `
.xb-cp-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  display: flex; align-items: flex-start; justify-content: center;
  padding-top: 15vh; z-index: 800; backdrop-filter: blur(4px);
  animation: fade-in 100ms ease-out;
}
.xb-cp-modal {
  width: 540px; max-width: 94vw;
  background: var(--bgc); border: 1px solid var(--bdh);
  border-radius: var(--rl); overflow: hidden;
  box-shadow: 0 20px 60px rgba(0,0,0,.6);
  animation: fade-in 120ms ease-out;
}
.xb-cp-search-row {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 14px; border-bottom: 1px solid var(--bd);
}
.xb-cp-search-icon { font-size: 14px; color: var(--txt2); flex-shrink: 0; }
.xb-cp-inp {
  flex: 1; background: transparent; border: none; outline: none;
  color: var(--txt); font-size: 13px; font-family: inherit; caret-color: var(--cyan);
}
.xb-cp-inp::placeholder { color: var(--txt3); }
.xb-cp-kbd {
  font-size: 9.5px; padding: 2px 5px; border-radius: 3px;
  background: rgba(255,255,255,.05); border: 1px solid var(--bd);
  color: var(--txt3); font-family: var(--font-mono); flex-shrink: 0;
}
.xb-cp-results { max-height: 360px; overflow-y: auto; padding: 4px 0; }
.xb-cp-section-lbl {
  font-size: 8.5px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: var(--txt3); padding: 5px 14px 2px;
}
.xb-cp-result {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 14px; cursor: pointer; transition: background var(--tr-f);
}
.xb-cp-result:hover, .xb-cp-result.active { background: rgba(0,212,255,.06); }
.xb-cp-result.active { border-left: 2px solid var(--cyan); padding-left: 12px; }
.xb-cp-kind-badge {
  font-size: 8px; padding: 2px 5px; border-radius: 3px;
  font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
  flex-shrink: 0; width: 56px; text-align: center;
}
.kind-actor     { background: rgba(59,139,212,.12);  color: #3b8bd4; }
.kind-component { background: rgba(255,159,67,.12);  color: var(--amb); }
.kind-system    { background: rgba(168,85,247,.12);  color: var(--vlt); }
.kind-rule      { background: rgba(16,185,129,.12);  color: var(--grn); }
.kind-action    { background: rgba(255,255,255,.06); color: var(--txt2); }
.kind-version   { background: rgba(0,212,255,.08);   color: var(--cyan); }
.xb-cp-label {
  flex: 1; font-size: 11.5px; color: var(--txt);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.xb-cp-sub {
  font-size: 9.5px; color: var(--txt2); flex-shrink: 0;
  max-width: 160px; overflow: hidden; text-overflow: ellipsis;
}
.xb-cp-empty {
  padding: 20px 14px; font-size: 10.5px; color: var(--txt2); text-align: center;
}
.xb-cp-footer {
  padding: 6px 14px; border-top: 1px solid var(--bd);
  display: flex; gap: 10px; font-size: 9.5px; color: var(--txt3);
  align-items: center;
}
.xb-cp-footer kbd {
  font-family: var(--font-mono); background: rgba(255,255,255,.05);
  border: 1px solid var(--bd); border-radius: 3px; padding: 1px 5px;
}
`;

interface PaletteDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
}

export class CommandPalette {
  private readonly _deps:   PaletteDeps;
  private readonly _engine: CGSSearchEngine;
  private _overlay!:        HTMLElement;
  private _inp!:            HTMLInputElement;
  private _results!:        HTMLElement;
  private _items:           SearchResult[] = [];
  private _activeIdx:       number         = 0;
  private _isOpen:          boolean        = false;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: PaletteDeps) {
    this._deps   = deps;
    this._engine = new CGSSearchEngine();
    this._injectStyles();
  }

  mount(): void {
    // Rebuild index on CGS changes
    this._unsubs.push(
      this._deps.cgsStore.subscribe(() => {
        this._engine.buildIndex(
          this._deps.cgsStore.cgs,
          result => { this._selectResult(result); this.close(); },
          text => {
            window.dispatchEvent(new CustomEvent('xace:prefill-prompt', { detail: { text } }));
            this.close();
          },
        );
      }),
    );

    // React to ui_store open/close
    this._unsubs.push(
      this._deps.uiStore.select(s => s.commandPaletteOpen, open => {
        if (open && !this._isOpen)  this.open();
        if (!open && this._isOpen)  this.close();
      }),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this.close();
  }

  open(): void {
    if (this._isOpen) return;
    this._isOpen = true;

    this._overlay = document.createElement('div');
    this._overlay.className = 'xb-cp-overlay';
    this._overlay.addEventListener('click', e => {
      if (e.target === this._overlay) this.close();
    });

    const modal = document.createElement('div');
    modal.className = 'xb-cp-modal';

    // Search row
    const row = document.createElement('div');
    row.className = 'xb-cp-search-row';
    row.innerHTML = `<span class="xb-cp-search-icon">⌕</span>`;

    this._inp = document.createElement('input');
    this._inp.className   = 'xb-cp-inp';
    this._inp.placeholder = 'Search entities, systems, rules…';
    this._inp.setAttribute('spellcheck', 'false');
    this._inp.setAttribute('autocomplete', 'off');
    this._inp.addEventListener('input', () => this._search(this._inp.value));
    this._inp.addEventListener('keydown', e => this._onKey(e));
    row.appendChild(this._inp);
    row.innerHTML += `<span class="xb-cp-kbd">Esc</span>`;
    modal.appendChild(row);

    // Results container
    this._results = document.createElement('div');
    this._results.className = 'xb-cp-results';
    modal.appendChild(this._results);

    // Footer
    modal.innerHTML += `
      <div class="xb-cp-footer">
        <kbd>↑↓</kbd> navigate &nbsp;
        <kbd>↵</kbd> select &nbsp;
        <kbd>Esc</kbd> close
        <span style="margin-left:auto">${this._engine.indexSize} items indexed</span>
      </div>
    `;

    this._overlay.appendChild(modal);
    document.body.appendChild(this._overlay);

    // Initial results (built-in actions)
    this._search('');
    requestAnimationFrame(() => this._inp.focus());
  }

  close(): void {
    if (!this._isOpen) return;
    this._isOpen = false;
    this._overlay?.remove();
    this._deps.uiStore.setCommandPaletteOpen(false);
  }

  private _search(query: string): void {
    this._items     = this._engine.search(query);
    this._activeIdx = 0;
    this._renderResults();
  }

  private _renderResults(): void {
    this._results.innerHTML = '';

    if (this._items.length === 0) {
      this._results.innerHTML = `<div class="xb-cp-empty">No results found.</div>`;
      return;
    }

    // Group by kind
    const groups = new Map<string, SearchResult[]>();
    for (const item of this._items) {
      const k = item.kind;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)!.push(item);
    }

    let flatIdx = 0;
    for (const [kind, items] of groups) {
      const lbl = document.createElement('div');
      lbl.className   = 'xb-cp-section-lbl';
      lbl.textContent = kind === 'action' ? 'Actions' : kind.charAt(0).toUpperCase() + kind.slice(1) + 's';
      this._results.appendChild(lbl);

      for (const item of items) {
        const row = document.createElement('div');
        const isActive = flatIdx === this._activeIdx;
        row.className = `xb-cp-result${isActive ? ' active' : ''}`;
        row.dataset['idx'] = String(flatIdx);
        row.innerHTML = `
          <span class="xb-cp-kind-badge kind-${item.kind}">${item.kind}</span>
          <span class="xb-cp-label">${item.label}</span>
          <span class="xb-cp-sub">${item.subLabel}</span>
        `;
        row.addEventListener('click', () => { this._selectResult(item); this.close(); });
        row.addEventListener('mouseenter', () => {
          this._activeIdx = flatIdx;
          this._renderResults();
        });
        this._results.appendChild(row);
        flatIdx++;
      }
    }
  }

  private _onKey(e: KeyboardEvent): void {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      this._activeIdx = Math.min(this._activeIdx + 1, this._items.length - 1);
      this._renderResults();
      this._scrollActive();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      this._activeIdx = Math.max(0, this._activeIdx - 1);
      this._renderResults();
      this._scrollActive();
    } else if (e.key === 'Enter') {
      const item = this._items[this._activeIdx];
      if (item) { this._selectResult(item); this.close(); }
    } else if (e.key === 'Escape') {
      this.close();
    }
  }

  private _scrollActive(): void {
    const el = this._results.querySelector<HTMLElement>(`[data-idx="${this._activeIdx}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }

  private _selectResult(result: SearchResult): void {
    if (result.kind === 'action') {
      result.action();
      return;
    }
    this._deps.uiStore.selectEntity({
      id:     result.id,
      kind:   result.kind as any,
      label:  result.label,
      modeId: result.modeId ?? '',
    });
    result.action();
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-cp-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-cp-styles'; s.textContent = STYLES;
    document.head.appendChild(s);
  }
}