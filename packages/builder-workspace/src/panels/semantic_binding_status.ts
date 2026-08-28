import type { AssetRef, SemanticAssetBinding, SemanticPlaybackKind } from '../types/cgs';
import {
  ENGINE_TARGETS,
  type EngineTarget,
  isAssetCompatibleWithPlaybackKind,
  rustAssetType,
} from './semantic_binding_catalog';

export type SemanticBindingEngineStatus = 'resolved' | 'unresolved' | 'unsupported' | 'missing' | 'fallback';

export interface SemanticBindingStatusRecord {
  readonly bindingId: string;
  readonly engine: EngineTarget;
  readonly status: SemanticBindingEngineStatus;
  readonly reason: string;
  readonly assetId: string;
}

const ENGINE_SUPPORTED_TYPES: Record<EngineTarget, readonly string[]> = {
  godot: ['Mesh', 'Texture', 'Material', 'AnimationClip', 'AudioClip', 'AudioMusic', 'Sprite', 'Particle', 'Prefab', 'Font'],
  unity: ['Mesh', 'Texture', 'Material', 'AnimationClip', 'AnimationController', 'AudioClip', 'AudioMusic', 'Sprite', 'Particle', 'Prefab', 'Font'],
  unreal: ['Mesh', 'Texture', 'Material', 'AnimationClip', 'AnimationController', 'AudioClip', 'AudioMusic', 'Sprite', 'Particle', 'Prefab', 'Font'],
};

const ENGINE_EXTENSION_OVERRIDES: Record<EngineTarget, Partial<Record<string, readonly string[]>>> = {
  godot: {
    AnimationController: ['.tres', '.res'],
    Material: ['.material', '.tres', '.res'],
    Particle: ['.tscn', '.tres'],
    Prefab: ['.tscn', '.scn'],
  },
  unity: {
    Material: ['.mat'],
    AnimationController: ['.controller'],
    Particle: ['.prefab', '.vfx'],
    Prefab: ['.prefab'],
  },
  unreal: {
    Material: ['.uasset'],
    AnimationController: ['.uasset'],
    AnimationClip: ['.uasset', '.fbx'],
    Particle: ['.uasset', '.niagara'],
    Prefab: ['.uasset', '.umap'],
  },
};

const COMMON_EXTENSIONS: Record<string, readonly string[]> = {
  Mesh: ['.fbx', '.obj', '.gltf', '.glb', '.mesh'],
  Texture: ['.png', '.jpg', '.jpeg', '.tga', '.exr', '.bmp', '.dds'],
  Material: ['.mat', '.material', '.uasset', '.tres', '.res'],
  AnimationController: ['.controller', '.anim', '.uasset', '.tres', '.res'],
  AnimationClip: ['.anim', '.fbx', '.glb', '.gltf', '.uasset', '.res', '.tres'],
  AudioClip: ['.wav', '.ogg', '.mp3', '.aiff', '.flac'],
  AudioMusic: ['.wav', '.ogg', '.mp3', '.aiff', '.flac'],
  Sprite: ['.png', '.jpg', '.jpeg', '.tga', '.sprite'],
  Particle: ['.prefab', '.niagara', '.tscn', '.tres', '.vfx', '.uasset'],
  Prefab: ['.prefab', '.uasset', '.tscn', '.scn'],
  Font: ['.ttf', '.otf', '.fnt', '.asset'],
};

export function evaluateSemanticBindingStatuses(
  binding: SemanticAssetBinding,
  assets: readonly AssetRef[],
): SemanticBindingStatusRecord[] {
  const targets = engineTargetsFromBinding(binding);
  return ENGINE_TARGETS.map((engine) => evaluateForEngine(binding, assets, engine, targets));
}

export function semanticBindingStatusSummary(
  bindings: readonly SemanticAssetBinding[],
  assets: readonly AssetRef[],
): Record<SemanticBindingEngineStatus, number> {
  const summary: Record<SemanticBindingEngineStatus, number> = {
    resolved: 0,
    unresolved: 0,
    unsupported: 0,
    missing: 0,
    fallback: 0,
  };
  for (const binding of bindings) {
    for (const record of evaluateSemanticBindingStatuses(binding, assets)) {
      summary[record.status] += 1;
    }
  }
  return summary;
}

export function statusBlocksLaunch(status: SemanticBindingEngineStatus): boolean {
  return status === 'unresolved' || status === 'unsupported' || status === 'missing';
}

function evaluateForEngine(
  binding: SemanticAssetBinding,
  assets: readonly AssetRef[],
  engine: EngineTarget,
  targets: ReadonlySet<string>,
): SemanticBindingStatusRecord {
  const assetId = binding.asset?.id || '';
  const asset = assets.find((item) => item.placeholder_id === assetId);
  const fallback = hasDocumentedFallback(binding, asset);
  const record = (status: SemanticBindingEngineStatus, reason: string): SemanticBindingStatusRecord => ({
    bindingId: binding.binding_id,
    engine,
    status,
    reason,
    assetId,
  });
  const fallbackOr = (status: SemanticBindingEngineStatus, reason: string): SemanticBindingStatusRecord => {
    if (fallback) return record('fallback', `${reason} Documented fallback is present.`);
    return record(status, reason);
  };

  if (!targets.has(engine)) {
    return record('unsupported', `${engine} is not selected for this binding.`);
  }
  if (!assetId || !asset) {
    return fallbackOr('unresolved', 'Binding asset is not present in the CGS asset manifest.');
  }
  const kind = binding.playback_kind as SemanticPlaybackKind;
  if (!isAssetCompatibleWithPlaybackKind(asset, kind)) {
    return fallbackOr('unsupported', `${kind} playback cannot use ${asset.asset_type || binding.asset.asset_type}.`);
  }
  const assetType = rustAssetType(asset.asset_type || binding.asset.asset_type, kind);
  if (!ENGINE_SUPPORTED_TYPES[engine].includes(assetType)) {
    return fallbackOr('unsupported', `${engine} does not support ${assetType} bindings.`);
  }
  const status = (asset.status || '').toLowerCase();
  if (status === 'unresolved') {
    return fallbackOr('unresolved', 'Asset has not been resolved to an engine-loadable reference.');
  }
  if (status === 'missing') {
    return fallbackOr('missing', 'Asset is marked missing.');
  }
  if (status !== 'linked') {
    return fallbackOr('missing', 'Asset is not linked before runtime/handoff launch.');
  }
  const path = (asset.asset_path || binding.parameters?.resource_path || binding.parameters?.asset_path || binding.parameters?.path || '').trim();
  if (!path) {
    return fallbackOr('missing', 'Linked asset has no resource path before runtime/handoff launch.');
  }
  const ext = extensionOf(path);
  const allowed = ENGINE_EXTENSION_OVERRIDES[engine][assetType] || COMMON_EXTENSIONS[assetType] || [];
  if (ext && allowed.length > 0 && !allowed.includes(ext)) {
    return fallbackOr('unsupported', `${engine} does not support ${ext} for ${assetType}.`);
  }
  return record('resolved', 'Binding has a linked asset path and supported type for this engine.');
}

function engineTargetsFromBinding(binding: SemanticAssetBinding): ReadonlySet<string> {
  const raw = binding.parameters?.xace_engine_targets || '';
  const targets = raw.split(',').map((item) => item.trim().toLowerCase()).filter(Boolean);
  return new Set(targets.length > 0 ? targets : ENGINE_TARGETS);
}

function hasDocumentedFallback(binding: SemanticAssetBinding, asset: AssetRef | undefined): boolean {
  const params = binding.parameters || {};
  const raw = asset as unknown as Record<string, unknown> | undefined;
  return Boolean(
    params.fallback
    || params.fallback_asset
    || params.fallback_asset_id
    || params.fallback_policy
    || params.placeholder_fallback
    || raw?.fallback
    || raw?.fallback_asset
    || raw?.fallback_asset_id
    || raw?.fallback_policy
    || raw?.placeholder_fallback
    || raw?.allow_fallback === true
  );
}

function extensionOf(path: string): string {
  const clean = (path.split(/[?#]/)[0] || '').toLowerCase();
  const slash = Math.max(clean.lastIndexOf('/'), clean.lastIndexOf('\\'));
  const leaf = clean.slice(slash + 1);
  const dot = leaf.lastIndexOf('.');
  return dot >= 0 ? leaf.slice(dot) : '';
}
