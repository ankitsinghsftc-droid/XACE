/**
 * cgs_store.ts — Canonical Game Schema reactive store
 *
 * Single source of truth for the current CGS. All components that
 * display schema data subscribe here. Never mutate CGS objects directly —
 * updates come exclusively from the WebSocket (cgs_update messages).
 *
 * Uses an immutable update pattern: every set() call creates a new
 * state object. Subscribers receive the full new state.
 *
 * Derived state (actor count, asset status, etc.) is computed lazily
 * and cached per-hash so expensive traversals run at most once per
 * mutation.
 */

import type { CGS, CGSAssetReference, CGSSnapshot, CGSGraph, AssetRef, SemanticAssetBinding } from '../types/cgs';
import {
  EMPTY_CGS,
  allActors,
  allSystems,
  buildCGSGraph,
} from '../types/cgs';

// ── Store state ───────────────────────────────────────────────────────────────

export interface CGSStoreState {
  /** Current CGS. Never null — starts as EMPTY_CGS sentinel. */
  readonly cgs:               CGS;
  /** SHA hash of the current CGS. Empty string = not yet loaded. */
  readonly hash:              string;
  /** Schema version string from metadata */
  readonly version:           string;
  /** Ordered list of past snapshots (newest first) */
  readonly snapshots:         CGSSnapshot[];
  /** True while waiting for first server response */
  readonly isLoading:         boolean;
  /** True if the last update contained a pending (unapplied) mutation diff */
  readonly hasPendingMutation: boolean;
  /** Set of node IDs to highlight after a mutation (cleared after 2s) */
  readonly highlightedNodeIds: ReadonlySet<string>;
}

const INITIAL_STATE: CGSStoreState = {
  cgs:               EMPTY_CGS,
  hash:              '',
  version:           '—',
  snapshots:         [],
  isLoading:         true,
  hasPendingMutation: false,
  highlightedNodeIds: new Set(),
};

// ── Derived state cache ───────────────────────────────────────────────────────

interface DerivedCache {
  hash:        string;
  actorCount:  number;
  systemCount: number;
  ruleCount:   number;
  graph:       CGSGraph;
  assetRefs:   AssetRef[];
  semanticBindings: SemanticAssetBinding[];
}

// ── Store implementation ──────────────────────────────────────────────────────

type Listener = (state: CGSStoreState) => void;

export class CGSStore {
  private _state:     CGSStoreState = INITIAL_STATE;
  private _listeners: Set<Listener> = new Set();
  private _cache:     DerivedCache | null = null;

  // ── Read ──────────────────────────────────────────────────────────────────

  get state(): CGSStoreState {
    return this._state;
  }

  get cgs(): CGS {
    return this._state.cgs;
  }

  get hash(): string {
    return this._state.hash;
  }

  get isLoaded(): boolean {
    return !this._state.isLoading && this._state.hash !== '';
  }

  // ── Derived (cached per hash) ─────────────────────────────────────────────

  private ensureCache(): DerivedCache {
    if (this._cache?.hash === this._state.hash) {
      return this._cache;
    }

    const cgs = this._state.cgs;

    // Count entities
    const actorCount  = allActors(cgs).length;
    const systemCount = allSystems(cgs).length;
    const ruleCount   = cgs.modes.reduce((n, m) => n + m.rules.length, 0);

    // Build graph for visualization
    const graph = buildCGSGraph(cgs);

    const manifestAssets = collectCgsAssets(cgs);
    const manifestById = new Map<string, CGSAssetReference>();
    for (const asset of manifestAssets) {
      const id = assetRecordId(asset);
      if (id) manifestById.set(id, asset);
    }

    // Scan for asset references in component defaults. The identity field is
    // the asset placeholder (`mesh_id`, `audio_ref`, etc.); a sibling
    // `<field>_path` stores the designer-linked project path.
    const assetRefs: AssetRef[] = [];
    const componentAssetIds = new Set<string>();
    for (const { actor, modeId } of allActors(cgs)) {
      void modeId;
      for (const comp of actor.components) {
        for (const [key, value] of Object.entries(comp.defaults)) {
          if (
            typeof key === 'string' &&
            !key.endsWith('_path') &&
            (key.endsWith('_id') || key.endsWith('_ref')) &&
            typeof value === 'string'
          ) {
            const pathKey = `${key}_path`;
            const rawPath = comp.defaults[pathKey];
            const manifest = manifestById.get(value);
            const assetPath = typeof rawPath === 'string' ? rawPath.trim() : '';
            const manifestPath = manifest ? assetRecordPath(manifest) : '';
            const finalPath = assetPath || manifestPath;
            componentAssetIds.add(value);
            assetRefs.push({
              placeholder_id: value,
              asset_path:     finalPath || undefined,
              status:         normaliseAssetStatus(manifest?.status, Boolean(finalPath)),
              component_name: comp.name,
              actor_id:       actor.id,
              asset_type:     assetRecordType(manifest) || inferAssetType(key, comp.name, value),
              source:         'component',
              sha256:         assetRecordHash(manifest) || undefined,
              ...assetFallbackMetadata(manifest),
            });
          }
        }
      }
    }

    for (const asset of manifestAssets) {
      const id = assetRecordId(asset);
      if (!id || componentAssetIds.has(id)) continue;
      const path = assetRecordPath(asset);
      assetRefs.push({
        placeholder_id: id,
        asset_path: path || undefined,
        status: normaliseAssetStatus(asset.status, Boolean(path)),
        component_name: 'assets',
        actor_id: 'project',
        asset_type: assetRecordType(asset),
        source: 'manifest',
        sha256: assetRecordHash(asset) || undefined,
        ...assetFallbackMetadata(asset),
      });
    }

    const semanticBindings = collectSemanticBindings(cgs);

    this._cache = {
      hash: this._state.hash,
      actorCount,
      systemCount,
      ruleCount,
      graph,
      assetRefs,
      semanticBindings,
    };
    return this._cache;
  }

  get actorCount():  number    { return this.ensureCache().actorCount; }
  get systemCount(): number    { return this.ensureCache().systemCount; }
  get ruleCount():   number    { return this.ensureCache().ruleCount; }
  get graph():       CGSGraph  { return this.ensureCache().graph; }
  get assetRefs():   AssetRef[] { return this.ensureCache().assetRefs; }
  get semanticBindings(): SemanticAssetBinding[] { return this.ensureCache().semanticBindings; }

  get assetStatusSummary(): { linked: number; placeholder: number; missing: number } {
    const refs = this.assetRefs;
    return {
      linked:      refs.filter(r => r.status === 'linked').length,
      placeholder: refs.filter(r => r.status === 'placeholder').length,
      missing:     refs.filter(r => r.status === 'missing').length,
    };
  }

  // ── Subscribe ─────────────────────────────────────────────────────────────

  /**
   * Subscribe to state changes.
   * The callback is called immediately with the current state,
   * then on every subsequent change.
   * Returns an unsubscribe function.
   */
  subscribe(fn: Listener): () => void {
    this._listeners.add(fn);
    fn(this._state);           // immediate
    return () => this._listeners.delete(fn);
  }

  /**
   * Subscribe to a derived value — only calls fn when selector result changes.
   * Useful for components that only care about one slice of state.
   */
  select<T>(selector: (state: CGSStoreState) => T, fn: (value: T) => void): () => void {
    let prev = selector(this._state);
    fn(prev);
    return this.subscribe(state => {
      const next = selector(state);
      if (next !== prev) {
        prev = next;
        fn(next);
      }
    });
  }

  // ── Updates (called by builder_client) ────────────────────────────────────

  /**
   * Full CGS replacement — from cgs_update WebSocket message.
   * Adds current state to snapshots before replacing.
   */
  setCGS(cgs: CGS, hash: string, snapshot?: CGSSnapshot): void {
    const prev = this._state;
    const snapshots = snapshot?.cgs_hash
      ? [snapshot, ...prev.snapshots].slice(0, 50)
      : prev.snapshots;

    this._update({
      cgs,
      hash,
      version:           cgs.metadata.schema_version,
      snapshots,
      isLoading:         false,
      hasPendingMutation: false,
      highlightedNodeIds: new Set(),
    });
  }

  /**
   * Initial load — called when session_init arrives.
   */
  initialize(cgs: CGS, hash: string, snapshots: CGSSnapshot[]): void {
    this._update({
      cgs,
      hash,
      version:           cgs.metadata.schema_version,
      snapshots,
      isLoading:         false,
      hasPendingMutation: false,
      highlightedNodeIds: new Set(),
    });
  }

  /**
   * Mark which CGS nodes are affected by an in-flight mutation.
   * Used by the graph to highlight affected nodes.
   */
  setHighlightedNodes(nodeIds: string[]): void {
    this._update({ highlightedNodeIds: new Set(nodeIds) });
    // Auto-clear after 2s
    setTimeout(() => {
      if (this._state.highlightedNodeIds.size > 0) {
        this._update({ highlightedNodeIds: new Set() });
      }
    }, 2000);
  }

  /**
   * Add or update an asset link (from asset_link_dialog).
   * Writes the path into the CGS in-memory and notifies subscribers.
   * The server persists this via the asset_link WebSocket message.
   */
  linkAsset(placeholderId: string, assetPath: string): void {
    this._cache = null;  // invalidate derived cache
    // Update is applied when server echoes back cgs_update
    // Nothing to do locally except invalidate cache
    void placeholderId; void assetPath;
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  private _update(partial: Partial<CGSStoreState>): void {
    this._state = { ...this._state, ...partial };
    this._listeners.forEach(fn => fn(this._state));
  }
}

function collectCgsAssets(cgs: CGS): CGSAssetReference[] {
  return [
    ...assetArrayFrom((cgs as any).assets),
    ...assetArrayFrom((cgs.metadata as any)?.assets),
  ];
}

function assetArrayFrom(value: unknown): CGSAssetReference[] {
  if (Array.isArray(value)) return value.filter(isRecord) as CGSAssetReference[];
  if (isRecord(value) && Array.isArray(value['items'])) return value['items'].filter(isRecord) as CGSAssetReference[];
  return [];
}

function collectSemanticBindings(cgs: CGS): SemanticAssetBinding[] {
  const table = cgs.semantic_bindings;
  if (!table || !Array.isArray(table.bindings)) return [];
  return table.bindings.filter(isRecord) as unknown as SemanticAssetBinding[];
}

function assetRecordId(asset: CGSAssetReference | undefined): string {
  if (!asset) return '';
  return stringField(asset.id) || stringField(asset.asset_id);
}

function assetRecordType(asset: CGSAssetReference | undefined): string | undefined {
  if (!asset) return undefined;
  return stringField(asset.asset_type) || stringField(asset.type) || undefined;
}

function assetRecordPath(asset: CGSAssetReference | undefined): string {
  if (!asset) return '';
  return (
    stringField(asset.resolved_path)
    || stringField(asset.source_path)
    || stringField(asset.path)
    || stringField(asset.resource_path)
    || stringField(asset.asset_path)
  );
}

function assetRecordHash(asset: CGSAssetReference | undefined): string {
  if (!asset) return '';
  return (
    stringField(asset.sha256)
    || stringField(asset.content_hash)
    || stringField(asset.asset_hash)
    || stringField(asset.hash)
  );
}

function assetFallbackMetadata(asset: CGSAssetReference | undefined): Partial<AssetRef> {
  if (!asset) return {};
  const result: Record<string, unknown> = {};
  if (asset.fallback !== undefined) result.fallback = asset.fallback;
  if (asset.fallback_asset !== undefined) result.fallback_asset = asset.fallback_asset;
  if (asset.fallback_asset_id !== undefined) result.fallback_asset_id = asset.fallback_asset_id;
  if (asset.fallback_policy !== undefined) result.fallback_policy = asset.fallback_policy;
  if (asset.placeholder_fallback !== undefined) result.placeholder_fallback = asset.placeholder_fallback;
  if (asset.allow_fallback !== undefined) result.allow_fallback = asset.allow_fallback;
  return result as Partial<AssetRef>;
}

function normaliseAssetStatus(rawStatus: string | undefined, hasPath: boolean): AssetRef['status'] {
  const value = (rawStatus || '').trim().toLowerCase();
  if (value === 'unresolved') return 'unresolved';
  if (value === 'missing') return 'missing';
  if (value === 'linked') return 'linked';
  return hasPath ? 'linked' : 'placeholder';
}

function inferAssetType(fieldName: string, componentName: string, assetId: string): string | undefined {
  const text = `${fieldName} ${componentName} ${assetId}`.toLowerCase();
  if (text.includes('anim_clip') || text.includes('animation_clip')) return 'AnimationClip';
  if (text.includes('anim') || text.includes('animation')) return 'AnimationClip';
  if (text.includes('audio') || text.includes('sfx') || text.includes('sound')) return 'AudioClip';
  if (text.includes('music') || text.includes('bgm')) return 'AudioMusic';
  if (text.includes('vfx') || text.includes('particle')) return 'Particle';
  if (text.includes('sprite')) return 'Sprite';
  if (text.includes('texture') || text.includes('tex')) return 'Texture';
  if (text.includes('material') || text.includes('mat')) return 'Material';
  if (text.includes('prefab')) return 'Prefab';
  if (text.includes('font')) return 'Font';
  if (text.includes('mesh')) return 'Mesh';
  return undefined;
}

function stringField(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Shared singleton */
export const cgsStore = new CGSStore();
