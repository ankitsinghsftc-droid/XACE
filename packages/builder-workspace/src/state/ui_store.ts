/**
 * ui_store.ts — UI state store
 *
 * Manages selection, mode, panel layout, and ephemeral UI state.
 * Selected entity drives the inspector and graph highlight.
 * Mode drives PILModeProfile behavior (verbosity, clarification depth, etc.)
 *
 * Mode preference is persisted to localStorage so returning users
 * don't have to reset it every session.
 */

import type { AssistanceMode } from '../types/pil';
import type { GraphNodeKind } from '../types/cgs';
import type { PromptCapabilityMatrix } from '../api/builder_client';

// ── Sidebar view ──────────────────────────────────────────────────────────────

export type SidebarView = 'tree' | 'graph';

// ── Right panel tab ───────────────────────────────────────────────────────────

export type RightPanelTab =
  | 'preview'       // 2D schema canvas (Phase 14) / engine viewport (Phase 15)
  | 'inspector'     // entity inspector
  | 'stats'         // runtime stats
  | 'debug'         // tick debugger
  | 'telemetry';    // inference telemetry (ARCHITECT_MODE only)

// ── Center panel tab ──────────────────────────────────────────────────────────

export type CenterTab = 'builder' | 'schema-graph';

// ── Selected entity ───────────────────────────────────────────────────────────

export interface SelectedEntity {
  readonly id:     string;
  readonly kind:   GraphNodeKind;
  readonly label:  string;
  readonly modeId: string;
}

// ── Store state ───────────────────────────────────────────────────────────────

export interface UIStoreState {
  readonly mode:               AssistanceMode;
  readonly sidebarView:        SidebarView;
  readonly rightPanelTab:      RightPanelTab;
  readonly centerTab:          CenterTab;
  readonly selectedEntity:     SelectedEntity | null;
  readonly sidebarCollapsed:   boolean;
  readonly rightPanelCollapsed: boolean;
  /** Which tree sections are expanded (set of section keys) */
  readonly expandedSections:   ReadonlySet<string>;
  /** Whether Cmd+K command palette is open */
  readonly commandPaletteOpen: boolean;
  /** Current search query in sidebar */
  readonly sidebarSearch:      string;
  /** Whether the bottom bar is expanded */
  readonly bottomBarExpanded:  boolean;
  readonly promptCapabilityMatrix: PromptCapabilityMatrix | null;
  readonly promptCapabilityMatrixError: string;
}

// ── Persistence keys ──────────────────────────────────────────────────────────

const STORAGE_KEY_MODE             = 'xace:ui:mode';
const STORAGE_KEY_SIDEBAR_VIEW     = 'xace:ui:sidebarView';
const STORAGE_KEY_RIGHT_PANEL_TAB  = 'xace:ui:rightPanelTab';
const STORAGE_KEY_BOTTOM_EXPANDED  = 'xace:ui:bottomExpanded';

function readStored(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeStored(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* ignore */ }
}

// ── Store implementation ──────────────────────────────────────────────────────

type Listener = (state: UIStoreState) => void;

export class UIStore {
  private _state: UIStoreState = {
    mode:                readStored(STORAGE_KEY_MODE, 'COLLABORATIVE') as AssistanceMode,
    sidebarView:         readStored(STORAGE_KEY_SIDEBAR_VIEW, 'tree') as SidebarView,
    rightPanelTab:       readStored(STORAGE_KEY_RIGHT_PANEL_TAB, 'inspector') as RightPanelTab,
    centerTab:           'builder',
    selectedEntity:      null,
    sidebarCollapsed:    false,
    rightPanelCollapsed: false,
    expandedSections:    new Set(['modes', 'globalSystems']),
    commandPaletteOpen:  false,
    sidebarSearch:       '',
    bottomBarExpanded:   readStored('xace:ui:bottomExpanded', 'false') === 'true',
    promptCapabilityMatrix: null,
    promptCapabilityMatrixError: '',
  };

  private _listeners: Set<Listener> = new Set();

  // ── Read ──────────────────────────────────────────────────────────────────

  get state(): UIStoreState { return this._state; }
  get mode():  AssistanceMode { return this._state.mode; }
  get selectedEntity(): SelectedEntity | null { return this._state.selectedEntity; }

  // ── Subscribe ─────────────────────────────────────────────────────────────

  subscribe(fn: Listener): () => void {
    this._listeners.add(fn);
    fn(this._state);
    return () => this._listeners.delete(fn);
  }

  select<T>(selector: (s: UIStoreState) => T, fn: (v: T) => void): () => void {
    let prev = selector(this._state);
    fn(prev);
    return this.subscribe(state => {
      const next = selector(state);
      if (next !== prev) { prev = next; fn(next); }
    });
  }

  // ── Mutations ─────────────────────────────────────────────────────────────

  setMode(mode: AssistanceMode): void {
    writeStored(STORAGE_KEY_MODE, mode);

    // ARCHITECT_MODE → auto-switch right panel to telemetry
    const rightPanelTab = mode === 'ARCHITECT_MODE'
      ? 'telemetry' as const
      : this._state.rightPanelTab === 'telemetry'
        ? 'inspector' as const   // leave architect mode → go back to inspector
        : this._state.rightPanelTab;

    this._update({ mode, rightPanelTab });
  }

  setSidebarView(view: SidebarView): void {
    writeStored(STORAGE_KEY_SIDEBAR_VIEW, view);
    this._update({ sidebarView: view });
  }

  setRightPanelTab(tab: RightPanelTab): void {
    // Only allow telemetry tab in ARCHITECT_MODE
    if (tab === 'telemetry' && this._state.mode !== 'ARCHITECT_MODE') return;
    writeStored(STORAGE_KEY_RIGHT_PANEL_TAB, tab);
    this._update({ rightPanelTab: tab });
  }

  setCenterTab(tab: CenterTab): void {
    this._update({ centerTab: tab });
  }

  selectEntity(entity: SelectedEntity | null): void {
    this._update({ selectedEntity: entity });
    // When an entity is selected, switch right panel to inspector
    if (entity && this._state.rightPanelTab === 'preview') {
      this.setRightPanelTab('inspector');
    }
  }

  clearSelection(): void {
    this._update({ selectedEntity: null });
  }

  toggleSidebar(): void {
    this._update({ sidebarCollapsed: !this._state.sidebarCollapsed });
  }

  toggleRightPanel(): void {
    this._update({ rightPanelCollapsed: !this._state.rightPanelCollapsed });
  }

  toggleSection(key: string): void {
    const sections = new Set(this._state.expandedSections);
    if (sections.has(key)) sections.delete(key);
    else sections.add(key);
    this._update({ expandedSections: sections });
  }

  setCommandPaletteOpen(open: boolean): void {
    this._update({ commandPaletteOpen: open });
  }

  setSidebarSearch(query: string): void {
    this._update({ sidebarSearch: query });
  }

  setBottomBarExpanded(expanded: boolean): void {
    writeStored(STORAGE_KEY_BOTTOM_EXPANDED, String(expanded));
    this._update({ bottomBarExpanded: expanded });
  }

  setPromptCapabilityMatrix(matrix: PromptCapabilityMatrix): void {
    this._update({ promptCapabilityMatrix: matrix, promptCapabilityMatrixError: '' });
  }

  setPromptCapabilityMatrixError(error: string): void {
    this._update({ promptCapabilityMatrixError: error });
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  private _update(partial: Partial<UIStoreState>): void {
    this._state = { ...this._state, ...partial };
    this._listeners.forEach(fn => fn(this._state));
  }
}

/** Shared singleton */
export const uiStore = new UIStore();

// ── Keyboard shortcut wiring ──────────────────────────────────────────────────
// Registered here so it's active from app startup regardless of which
// component is focused.

if (typeof window !== 'undefined') {
  window.addEventListener('keydown', (e: KeyboardEvent) => {
    const meta = e.metaKey || e.ctrlKey;

    // Cmd+K — command palette
    if (meta && e.key === 'k') {
      e.preventDefault();
      uiStore.setCommandPaletteOpen(!uiStore.state.commandPaletteOpen);
    }

    // Escape — dismiss command palette or clear selection
    if (e.key === 'Escape') {
      if (uiStore.state.commandPaletteOpen) {
        uiStore.setCommandPaletteOpen(false);
      } else if (uiStore.state.selectedEntity) {
        uiStore.clearSelection();
      }
    }

    // Cmd+\ — toggle sidebar
    if (meta && e.key === '\\') {
      e.preventDefault();
      uiStore.toggleSidebar();
    }

    // Cmd+Shift+\ — toggle right panel
    if (meta && e.shiftKey && e.key === '|') {
      e.preventDefault();
      uiStore.toggleRightPanel();
    }
  });
}
