/**
 * builder_canvas.ts — Builder Canvas Composition
 *
 * Wires all components into the MainLayout slots.
 * This is the final integration layer — nothing renders
 * until this file runs.
 *
 * Mounting order:
 *   1. Left slot   ← CGSExplorer
 *   2. Center slot ← BuilderCenter (state-machine-driven views + prompt bar)
 *   3. Right slot  ← RightPanel (viewport + tabbed inspector/stats/debug/telemetry)
 *
 * Center panel view switching is driven by consoleSM state.
 */

import type { MainLayout }    from '../layout/main_layout';
import type { BuilderClient } from '../api/builder_client';
import type { ConsoleSM }     from '../state/console_state_machine';
import type { CGSStore }      from '../state/cgs_store';
import type { UIStore, UIStoreState, RightPanelTab } from '../state/ui_store';
import type { AssistanceMode } from '../types/pil';

// Left panel
import { CGSExplorer }        from '../sidebar/cgs_explorer';

// Center: state-driven views
import { PromptInput }        from '../canvas/prompt_input';
import { ProcessingView, IdleView, ReviewView, BlockedView, DiagnosticView }
                              from '../views/processing_view';
import { ClarificationCards } from '../canvas/clarification_cards';

// Right panel
import { EngineViewport }     from '../preview/engine_viewport';
import { EntityInspector }    from '../preview/entity_inspector';
import { RuntimeStats }       from '../preview/runtime_stats';
import { TickDebugger }       from '../preview/tick_debugger';
import { InferenceTelemetryPanel } from '../telemetry/inference_telemetry_panel';

// Asset panel
import { AssetStatusPanel }   from '../panels/asset_status_panel';

// Command palette
import { CommandPalette }     from '../command_palette/command_palette';

interface CanvasDeps {
  layout:    MainLayout;
  client:    BuilderClient;
  consoleSM: ConsoleSM;
  cgsStore:  CGSStore;
  uiStore:   UIStore;
}

export class BuilderCanvas {
  private readonly _deps: CanvasDeps;
  private readonly _unsubs: Array<() => void> = [];

  // Center view elements — swap visibility based on SM state
  private _centerViews!: {
    idle:         HTMLElement;
    processing:   HTMLElement;
    review:       HTMLElement;
    clarification: HTMLElement;
    blocked:      HTMLElement;
    diagnostic:   HTMLElement;
  };

  // Component instances
  private _idleView!:    IdleView;
  private _procView!:    ProcessingView;
  private _reviewView!:  ReviewView;
  private _clarCards!:   ClarificationCards;
  private _blockedView!: BlockedView;
  private _diagView!:    DiagnosticView;

  // Right panel
  private _rightTabs!:   HTMLElement;
  private _rightContent!: HTMLElement;
  private _rightTabContent!: HTMLElement;
  private _viewportWrap!: HTMLElement;
  private _telemetryPanel!: InferenceTelemetryPanel;

  // Command palette (global)
  private _cmdPalette!:  CommandPalette;

  constructor(deps: CanvasDeps) {
    this._deps = deps;
  }

  mount(): void {
    this._mountLeft();
    this._mountCenter();
    this._mountRight();
    this._mountCommandPalette();
    this._wireStateMachine();
    this._wireRightTabs();
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._cmdPalette?.unmount();
  }

  // ── Left panel ────────────────────────────────────────────────────────

  private _mountLeft(): void {
    const explorer = new CGSExplorer({
      cgsStore: this._deps.cgsStore,
      uiStore:  this._deps.uiStore,
      client:   this._deps.client,
    });
    explorer.mount(this._deps.layout.leftSlot);

    // Wire asset panel into the explorer's asset section
    const assetSec = document.getElementById('xb-exp-sec-assets');
    if (assetSec) {
      assetSec.innerHTML = '';
      const assetPanel = new AssetStatusPanel({
        cgsStore: this._deps.cgsStore,
        uiStore:  this._deps.uiStore,
        client:   this._deps.client,
      });
      assetPanel.mount(assetSec);
    }
  }

  // ── Center panel ──────────────────────────────────────────────────────

  private _mountCenter(): void {
    const center = this._deps.layout.centerSlot;

    // Center tabs (Builder | Schema Graph)
    const tabs = document.createElement('div');
    tabs.style.cssText = `
      display:flex;border-bottom:1px solid var(--bd);padding:0 12px;
      background:rgba(8,12,24,.9);flex-shrink:0;z-index:2;position:relative
    `;
    const tabDefs = [
      { id: 'builder',      label: 'Builder' },
      { id: 'schema-graph', label: 'Schema Graph' },
    ];
    for (const td of tabDefs) {
      const btn = document.createElement('div');
      btn.style.cssText = `
        font-size:11px;color:var(--txt2);padding:8px 12px;cursor:pointer;
        border-bottom:2px solid ${td.id === 'builder' ? 'var(--cyan)' : 'transparent'};
        color:${td.id === 'builder' ? 'var(--txt)' : 'var(--txt2)'};
        font-weight:500;transition:all var(--tr-f)
      `;
      btn.textContent = td.label;
      btn.dataset['tab'] = td.id;
      btn.addEventListener('click', () => {
        this._deps.uiStore.setCenterTab(td.id as any);
      });
      tabs.appendChild(btn);
    }
    center.appendChild(tabs);

    // Update tab styles reactively
    this._unsubs.push(
      this._deps.uiStore.select((s: UIStoreState) => s.centerTab, (tab: string) => {
        tabs.querySelectorAll<HTMLElement>('[data-tab]').forEach(btn => {
          const isActive = btn.dataset['tab'] === tab;
          btn.style.borderBottomColor = isActive ? 'var(--cyan)' : 'transparent';
          btn.style.color             = isActive ? 'var(--txt)' : 'var(--txt2)';
        });
      }),
    );

    // View container — holds all state-driven views
    const viewContainer = document.createElement('div');
    viewContainer.style.cssText = 'flex:1;overflow-y:auto;overflow-x:hidden;display:flex;flex-direction:column;position:relative;z-index:1';
    center.appendChild(viewContainer);

    // Create one div per view, hidden by default
    const views = ['idle', 'processing', 'review', 'clarification', 'blocked', 'diagnostic'] as const;
    const viewEls: Record<string, HTMLElement> = {};
    for (const v of views) {
      const el = document.createElement('div');
      el.id             = `xb-view-${v}`;
      el.style.display  = 'none';
      el.style.cssText += ';flex:1;display:none;flex-direction:column';
      viewContainer.appendChild(el);
      viewEls[v] = el;
    }
    this._centerViews = viewEls as any;

    // Mount each view component
    this._idleView = new IdleView();
    this._idleView.mount(viewEls['idle']!, this._deps.uiStore);

    this._procView = new ProcessingView(this._deps.consoleSM, this._deps.uiStore);
    this._procView.mount(viewEls['processing']!);

    this._reviewView = new ReviewView(this._deps.consoleSM, this._deps.uiStore, this._deps.client);
    this._reviewView.mount(viewEls['review']!);

    this._clarCards = new ClarificationCards({ client: this._deps.client, consoleSM: this._deps.consoleSM });
    this._clarCards.mount(viewEls['clarification']!);

    this._blockedView = new BlockedView(this._deps.consoleSM);
    this._blockedView.mount(viewEls['blocked']!);

    this._diagView = new DiagnosticView(this._deps.consoleSM);
    this._diagView.mount(viewEls['diagnostic']!);

    // Prompt input (always at bottom)
    const promptWrap = document.createElement('div');
    promptWrap.style.cssText = 'flex-shrink:0;position:relative;z-index:10';
    const promptInput = new PromptInput({
      client:    this._deps.client,
      consoleSM: this._deps.consoleSM,
      cgsStore:  this._deps.cgsStore,
      uiStore:   this._deps.uiStore,
    });
    promptInput.mount(promptWrap);
    center.appendChild(promptWrap);

    // Show idle by default
    this._showView('idle');
  }

  // ── Right panel ───────────────────────────────────────────────────────

  private _mountRight(): void {
    const right = this._deps.layout.rightSlot;

    // Tabs
    this._rightTabs = document.createElement('div');
    this._rightTabs.style.cssText = 'display:flex;border-bottom:1px solid var(--bd);flex-shrink:0;overflow-x:auto;scrollbar-width:none';
    right.appendChild(this._rightTabs);

    // Content area
    this._rightContent = document.createElement('div');
    this._rightContent.style.cssText = 'flex:1;overflow:hidden;display:flex;flex-direction:column';
    right.appendChild(this._rightContent);

    // Viewport (always visible at top in preview tab)
    const viewport = new EngineViewport({ cgsStore: this._deps.cgsStore, uiStore: this._deps.uiStore, client: this._deps.client });
    this._viewportWrap = document.createElement('div');
    this._viewportWrap.id = 'xb-vp-wrap';
    this._viewportWrap.style.cssText = 'flex:0 0 42%;overflow:hidden;display:flex;flex-direction:column;border-bottom:1px solid var(--bd)';
    viewport.mount(this._viewportWrap);
    this._rightContent.appendChild(this._viewportWrap);

    // Tab content area
    const tabContent = document.createElement('div');
    tabContent.style.cssText = 'flex:1;overflow:hidden;display:flex;flex-direction:column;min-height:0';
    this._rightContent.appendChild(tabContent);
    this._rightTabContent = tabContent;

    // Define tabs + their components
    type RightTab = 'preview' | 'inspector' | 'stats' | 'debug' | 'telemetry';
    const tabDefs: Array<{ id: RightTab; label: string; architectOnly?: boolean }> = [
      { id: 'preview',    label: 'Preview' },
      { id: 'inspector',  label: 'Inspector' },
      { id: 'stats',      label: 'Stats' },
      { id: 'debug',      label: 'Debug' },
      { id: 'telemetry',  label: 'Telemetry', architectOnly: true },
    ];

    // Create tab buttons
    for (const td of tabDefs) {
      const btn = document.createElement('button');
      btn.style.cssText = `
        font-size:10px;color:var(--txt2);padding:7px 10px;cursor:pointer;
        border-bottom:2px solid transparent;border-top:none;border-left:none;
        border-right:none;font-weight:500;transition:all var(--tr-f);
        font-family:inherit;background:transparent;white-space:nowrap;
        display:${td.architectOnly ? 'none' : 'block'}
      `;
      btn.dataset['tab'] = td.id;
      if (td.architectOnly) btn.dataset['architectOnly'] = '1';
      btn.textContent = td.label;
      btn.addEventListener('click', () => this._deps.uiStore.setRightPanelTab(td.id));
      this._rightTabs.appendChild(btn);
    }

    // Create tab panels
    const panels: Record<string, HTMLElement> = {};
    for (const td of tabDefs) {
      const panel = document.createElement('div');
      panel.style.cssText = 'flex:1;overflow:hidden;display:none;flex-direction:column;min-height:0';
      panel.dataset['panel'] = td.id;
      tabContent.appendChild(panel);
      panels[td.id] = panel;
    }

    const previewPanel = panels['preview']!;
    previewPanel.innerHTML = `
      <div style="padding:8px 10px;font-size:10px;color:var(--txt3);line-height:1.45;border-top:1px solid var(--bd)">
        Live preview uses the active CGS. Select an actor in the preview or tree to inspect and edit it.
      </div>
    `;

    // Mount inspector
    const inspector = new EntityInspector({ cgsStore: this._deps.cgsStore, uiStore: this._deps.uiStore, client: this._deps.client });
    inspector.mount(panels['inspector']!);

    // Mount stats
    const stats = new RuntimeStats({ cgsStore: this._deps.cgsStore, uiStore: this._deps.uiStore, client: this._deps.client });
    stats.mount(panels['stats']!);

    // Mount debugger
    const debugger_ = new TickDebugger({ cgsStore: this._deps.cgsStore, uiStore: this._deps.uiStore, client: this._deps.client });
    debugger_.mount(panels['debug']!);

    // Mount telemetry (Architect only)
    this._telemetryPanel = new InferenceTelemetryPanel({ consoleSM: this._deps.consoleSM, uiStore: this._deps.uiStore });
    this._telemetryPanel.mount(panels['telemetry']!);

    // Default: inspector
    this._showRightTab('inspector', panels);

    // Wire tab switching — two separate selects so each has a primitive selector
    this._unsubs.push(
      this._deps.uiStore.select(
        (s: UIStoreState) => s.rightPanelTab,
        (tab: RightPanelTab) => this._showRightTab(tab, panels),
      ),
    );
    this._unsubs.push(
      this._deps.uiStore.select(
        (s: UIStoreState) => s.mode,
        (mode: AssistanceMode) => {
          this._rightTabs.querySelectorAll<HTMLElement>('[data-architect-only]').forEach(btn => {
            btn.style.display = mode === 'ARCHITECT_MODE' ? 'block' : 'none';
          });
        },
      ),
    );
  }

  private _showRightTab(tab: string, panels: Record<string, HTMLElement>): void {
    if (this._viewportWrap) {
      this._viewportWrap.style.flex = tab === 'preview' ? '1 1 auto' : '0 0 42%';
    }
    if (this._rightTabContent) {
      this._rightTabContent.style.flex = tab === 'preview' ? '0 0 auto' : '1 1 auto';
    }
    // Update tab buttons
    this._rightTabs.querySelectorAll<HTMLElement>('[data-tab]').forEach(btn => {
      const active = btn.dataset['tab'] === tab;
      btn.style.borderBottomColor = active ? 'var(--cyan)' : 'transparent';
      btn.style.color             = active ? 'var(--cyan)' : 'var(--txt2)';
    });
    // Switch panels
    Object.entries(panels).forEach(([id, panel]) => {
      panel.style.display = id === tab ? 'flex' : 'none';
    });
  }

  // ── Command Palette ───────────────────────────────────────────────────

  private _mountCommandPalette(): void {
    this._cmdPalette = new CommandPalette({ cgsStore: this._deps.cgsStore, uiStore: this._deps.uiStore });
    this._cmdPalette.mount();
  }

  // ── State machine → view switching ────────────────────────────────────

  private _wireStateMachine(): void {
    this._unsubs.push(
      this._deps.consoleSM.subscribe(state => {
        switch (state.name) {
          case 'Idle':              this._showView('idle');          break;
          case 'Processing':        this._showView('processing');    break;
          case 'ApplyingMutation':  this._showView('processing');    break;
          case 'PreviewPending':    this._showView('review');        break;
          case 'ClarificationFlow': this._showView('clarification'); break;
          case 'BlockedView':       this._showView('blocked');       break;
          case 'DiagnosticView':    this._showView('diagnostic');    break;
          case 'ErrorView':         this._showView('blocked');       break; // reuse blocked layout
          default:                  this._showView('idle');
        }
      }),
    );
  }

  private _showView(name: keyof typeof this._centerViews): void {
    for (const [k, el] of Object.entries(this._centerViews)) {
      (el as HTMLElement).style.display = k === name ? 'flex' : 'none';
    }
  }

  // ── Right tab state machine hook ──────────────────────────────────────

  private _wireRightTabs(): void {
    // Auto-switch to telemetry after a mutation in ARCHITECT_MODE
    this._unsubs.push(
      this._deps.consoleSM.on('mutation_applied', () => {
        if (this._deps.uiStore.mode === 'ARCHITECT_MODE') {
          this._deps.uiStore.setRightPanelTab('telemetry');
        }
      }),
    );
  }
}
