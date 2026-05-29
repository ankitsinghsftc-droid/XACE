/**
 * cgs_explorer.ts — CGS Explorer (left sidebar container)
 *
 * Top-level container for the left sidebar. Manages:
 *   - Tree ↔ Graph view toggle
 *   - Search bar (filters tree nodes in real-time)
 *   - Section tabs: Entities | Systems | Rules | Assets | History
 *   - Asset status badge (placeholder count)
 *   - Mounts and switches between EntityTree, SystemList, RuleBrowser,
 *     AssetStatusPanel, VersionTimeline sub-components
 */

import type { CGSStore }           from '../state/cgs_store';
import type { UIStore }            from '../state/ui_store';
import type { BuilderClient }      from '../api/builder_client';
import { EntityTree }              from './entity_tree';
import { SystemList, RuleBrowser, VersionTimeline } from './system_list';
import { SchemaGraphView }         from '../graph/schema_graph_view';

const STYLES = `
.xb-exp {
  display:         flex;
  flex-direction:  column;
  height:          100%;
  overflow:        hidden;
}
.xb-exp-head {
  padding:         6px 10px;
  border-bottom:   1px solid var(--bd);
  display:         flex;
  align-items:     center;
  gap:             6px;
  flex-shrink:     0;
}
.xb-exp-title {
  font-size:       9px;
  font-weight:     700;
  letter-spacing:  .12em;
  text-transform:  uppercase;
  color:           var(--txt2);
  flex:            1;
}
.xb-view-tog {
  display:         flex;
  gap:             2px;
  background:      rgba(255,255,255,.03);
  border:          1px solid var(--bd);
  border-radius:   4px;
  padding:         2px;
  flex-shrink:     0;
}
.xb-vt-btn {
  font-size:       9px;
  padding:         2px 7px;
  border-radius:   3px;
  cursor:          pointer;
  color:           var(--txt2);
  border:          none;
  background:      transparent;
  transition:      all var(--tr-f);
  font-family:     inherit;
  display:         flex;
  align-items:     center;
  gap:             3px;
}
.xb-vt-btn.on {
  background:      var(--bgc);
  color:           var(--txt);
}
.xb-vt-btn:hover:not(.on) { color: var(--txt); }
.xb-exp-add {
  color:           var(--txt2);
  font-size:       14px;
  cursor:          pointer;
  transition:      color var(--tr-f);
  line-height:     1;
  padding:         0 2px;
  background:      none;
  border:          none;
}
.xb-exp-add:hover { color: var(--cyan); }
/* Search */
.xb-exp-search {
  padding:         5px 10px;
  border-bottom:   1px solid var(--bd);
  flex-shrink:     0;
}
.xb-search-wrap {
  display:         flex;
  align-items:     center;
  gap:             5px;
  background:      var(--bgc);
  border:          1px solid var(--bd);
  border-radius:   var(--rs);
  padding:         3px 7px;
  transition:      border-color var(--tr-f);
}
.xb-search-wrap:focus-within { border-color: var(--cyan); }
.xb-search-icon { color: var(--txt3); font-size: 11px; flex-shrink: 0; }
.xb-search-inp {
  flex:            1;
  background:      transparent;
  border:          none;
  outline:         none;
  color:           var(--txt);
  font-size:       10.5px;
  font-family:     inherit;
  caret-color:     var(--cyan);
}
.xb-search-inp::placeholder { color: var(--txt3); }
.xb-search-clear {
  color:           var(--txt3);
  font-size:       11px;
  cursor:          pointer;
  background:      none;
  border:          none;
  padding:         0 1px;
  line-height:     1;
  display:         none;
}
.xb-search-clear.vis { display: block; }
.xb-search-clear:hover { color: var(--txt2); }
/* Section tabs */
.xb-exp-tabs {
  display:         flex;
  border-bottom:   1px solid var(--bd);
  flex-shrink:     0;
  overflow-x:      auto;
  scrollbar-width: none;
}
.xb-exp-tabs::-webkit-scrollbar { display: none; }
.xb-exp-tab {
  font-size:       9.5px;
  color:           var(--txt2);
  padding:         5px 9px;
  cursor:          pointer;
  border-bottom:   2px solid transparent;
  white-space:     nowrap;
  transition:      all var(--tr-f);
  background:      none;
  border-top:      none;
  border-left:     none;
  border-right:    none;
  font-family:     inherit;
  display:         flex;
  align-items:     center;
  gap:             4px;
}
.xb-exp-tab.on { color: var(--cyan); border-bottom-color: var(--cyan); }
.xb-exp-tab:hover:not(.on) { color: var(--txt); }
.xb-exp-badge {
  font-size:       8px;
  padding:         1px 4px;
  border-radius:   3px;
  background:      rgba(255,159,67,.12);
  color:           var(--amb);
  border:          1px solid rgba(255,159,67,.2);
}
/* Content area */
.xb-exp-content {
  flex:            1;
  overflow:        hidden;
  display:         flex;
  flex-direction:  column;
}
.xb-exp-section {
  flex:            1;
  overflow:        hidden;
  display:         none;
  flex-direction:  column;
}
.xb-exp-section.on { display: flex; }
/* Graph view */
.xb-exp-graph-canvas {
  flex:            1;
  overflow:        hidden;
}
`;

type Tab = 'entities' | 'systems' | 'rules' | 'assets' | 'history';

interface CGSExplorerDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
  client:   BuilderClient;
}

export class CGSExplorer {
  private readonly _deps: CGSExplorerDeps;
  private _el!:           HTMLElement;
  private _activeTab:     Tab = 'entities';
  private _graphView:     SchemaGraphView | null = null;
  private readonly _unsubs: Array<() => void> = [];

  // Sub-components
  private _entityTree!:    EntityTree;
  private _systemList!:    SystemList;
  private _ruleBrowser!:   RuleBrowser;
  private _versionTl!:     VersionTimeline;

  constructor(deps: CGSExplorerDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = this._build();
    container.appendChild(this._el);
    this._mountSubComponents();
    this._wireReactive();
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._graphView?.unmount();
    this._el?.remove();
  }

  private _build(): HTMLElement {
    const root = document.createElement('div');
    root.className = 'xb-exp';

    // ── Header ──────────────────────────────────────────────────────────
    const head = document.createElement('div');
    head.className = 'xb-exp-head';

    const title = document.createElement('span');
    title.className   = 'xb-exp-title';
    title.textContent = 'CGS Explorer';
    head.appendChild(title);

    // Tree / Graph toggle
    const tog = document.createElement('div');
    tog.className = 'xb-view-tog';

    const treeBtn = document.createElement('button');
    treeBtn.className   = 'xb-vt-btn on';
    treeBtn.id          = 'xb-vt-tree';
    treeBtn.textContent = '≡ Tree';
    treeBtn.addEventListener('click', () => this._setView('tree'));

    const graphBtn = document.createElement('button');
    graphBtn.className   = 'xb-vt-btn';
    graphBtn.id          = 'xb-vt-graph';
    graphBtn.textContent = '⬡ Graph';
    graphBtn.addEventListener('click', () => this._setView('graph'));

    tog.appendChild(treeBtn);
    tog.appendChild(graphBtn);
    head.appendChild(tog);

    const addBtn = document.createElement('button');
    addBtn.className   = 'xb-exp-add';
    addBtn.textContent = '+';
    addBtn.title       = 'Add entity via prompt (Cmd+K)';
    addBtn.addEventListener('click', () => {
      this._deps.uiStore.setCommandPaletteOpen(true);
    });
    head.appendChild(addBtn);
    root.appendChild(head);

    // ── Search ──────────────────────────────────────────────────────────
    const searchArea = document.createElement('div');
    searchArea.className = 'xb-exp-search';
    const wrap = document.createElement('div');
    wrap.className = 'xb-search-wrap';
    wrap.innerHTML = `<span class="xb-search-icon">⌕</span>`;

    const inp = document.createElement('input');
    inp.className   = 'xb-search-inp';
    inp.placeholder = 'Search…';
    inp.setAttribute('spellcheck', 'false');
    inp.addEventListener('input', () => {
      this._deps.uiStore.setSidebarSearch(inp.value);
      clearBtn.classList.toggle('vis', inp.value.length > 0);
    });

    const clearBtn = document.createElement('button');
    clearBtn.className   = 'xb-search-clear';
    clearBtn.textContent = '✕';
    clearBtn.addEventListener('click', () => {
      inp.value = '';
      inp.focus();
      this._deps.uiStore.setSidebarSearch('');
      clearBtn.classList.remove('vis');
    });

    wrap.appendChild(inp);
    wrap.appendChild(clearBtn);
    searchArea.appendChild(wrap);
    root.appendChild(searchArea);

    // ── Section tabs ─────────────────────────────────────────────────────
    const tabs = document.createElement('div');
    tabs.className = 'xb-exp-tabs';

    const tabDefs: Array<{ id: Tab; label: string; badge?: string }> = [
      { id: 'entities', label: 'Entities' },
      { id: 'systems',  label: 'Systems' },
      { id: 'rules',    label: 'Rules' },
      { id: 'assets',   label: 'Assets', badge: '7' },
      { id: 'history',  label: 'History' },
    ];

    for (const def of tabDefs) {
      const tab = document.createElement('button');
      tab.className   = `xb-exp-tab${def.id === this._activeTab ? ' on' : ''}`;
      tab.dataset['tab'] = def.id;
      tab.textContent = def.label;
      if (def.badge) {
        const badge = document.createElement('span');
        badge.className   = 'xb-exp-badge';
        badge.id          = `xb-exp-badge-${def.id}`;
        badge.textContent = def.badge;
        tab.appendChild(badge);
      }
      tab.addEventListener('click', () => this._setTab(def.id));
      tabs.appendChild(tab);
    }
    root.appendChild(tabs);

    // ── Content sections ─────────────────────────────────────────────────
    const content = document.createElement('div');
    content.className = 'xb-exp-content';

    for (const def of tabDefs) {
      const sec = document.createElement('div');
      sec.className = `xb-exp-section${def.id === this._activeTab ? ' on' : ''}`;
      sec.id        = `xb-exp-sec-${def.id}`;
      content.appendChild(sec);
    }

    // Graph canvas (shown instead of sections when graph view active)
    const graphCanvas = document.createElement('div');
    graphCanvas.className = 'xb-exp-graph-canvas';
    graphCanvas.id        = 'xb-exp-graph-canvas';
    graphCanvas.style.display = 'none';
    content.appendChild(graphCanvas);

    root.appendChild(content);
    return root;
  }

  private _mountSubComponents(): void {
    const { cgsStore, uiStore, client } = this._deps;

    this._entityTree = new EntityTree({ cgsStore, uiStore });
    this._entityTree.mount(document.getElementById('xb-exp-sec-entities')!);

    this._systemList = new SystemList({ cgsStore, uiStore });
    this._systemList.mount(document.getElementById('xb-exp-sec-systems')!);

    this._ruleBrowser = new RuleBrowser({ cgsStore, uiStore });
    this._ruleBrowser.mount(document.getElementById('xb-exp-sec-rules')!);

    this._versionTl = new VersionTimeline({ cgsStore, uiStore, client });
    this._versionTl.mount(document.getElementById('xb-exp-sec-history')!);

    // Asset section — placeholder until AssetStatusPanel is mounted by panels layer
    const assetSec = document.getElementById('xb-exp-sec-assets')!;
    assetSec.innerHTML =
      `<div style="padding:10px;font-size:10px;color:var(--txt2)">
         Asset panel loading…
       </div>`;
  }

  private _wireReactive(): void {
    // Update asset badge count reactively
    this._unsubs.push(
      this._deps.cgsStore.subscribe(state => {
        const badge = document.getElementById('xb-exp-badge-assets');
        if (badge) badge.textContent = String(state ? this._deps.cgsStore.assetStatusSummary.placeholder : 0);
      }),
    );
  }

  private _setView(view: 'tree' | 'graph'): void {
    this._deps.uiStore.setSidebarView(view);

    const treeBtnEl  = document.getElementById('xb-vt-tree');
    const graphBtnEl = document.getElementById('xb-vt-graph');
    const graphCanvas = document.getElementById('xb-exp-graph-canvas');

    const isGraph = view === 'graph';

    treeBtnEl?.classList.toggle('on',  !isGraph);
    graphBtnEl?.classList.toggle('on',  isGraph);

    // Show/hide tab sections vs graph canvas
    document.querySelectorAll<HTMLElement>('.xb-exp-section').forEach(s => {
      s.style.display = isGraph ? 'none' : '';
    });
    const tabsEl = this._el.querySelector<HTMLElement>('.xb-exp-tabs');
    if (tabsEl) tabsEl.style.display = isGraph ? 'none' : '';

    if (graphCanvas) {
      graphCanvas.style.display = isGraph ? 'flex' : 'none';
      if (isGraph && !this._graphView) {
        this._graphView = new SchemaGraphView(
          { mode: 'mini', showEdgeLabels: false, showPhaseLanes: false },
          this._deps.uiStore,
        );
        this._graphView.mount(graphCanvas);
        // Initial data
        this._graphView.setGraph(this._deps.cgsStore.graph);
        this._unsubs.push(
          this._deps.cgsStore.subscribe(() => {
            this._graphView?.setGraph(this._deps.cgsStore.graph);
          }),
        );
      }
    }
  }

  private _setTab(tab: Tab): void {
    this._activeTab = tab;
    document.querySelectorAll<HTMLElement>('.xb-exp-tab').forEach(t => {
      t.classList.toggle('on', t.dataset['tab'] === tab);
    });
    document.querySelectorAll<HTMLElement>('.xb-exp-section').forEach(s => {
      s.classList.toggle('on', s.id === `xb-exp-sec-${tab}`);
    });
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-exp-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-exp-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}