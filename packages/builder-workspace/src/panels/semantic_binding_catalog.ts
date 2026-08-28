import type { AssetRef, SemanticPlaybackKind } from '../types/cgs';

export interface SemanticEventOption {
  readonly name: string;
  readonly label: string;
  readonly summary: string;
  readonly targets: readonly SemanticPlaybackKind[];
}

export const ENGINE_TARGETS = ['godot', 'unity', 'unreal'] as const;
export type EngineTarget = typeof ENGINE_TARGETS[number];

export const PLAYBACK_KINDS: readonly SemanticPlaybackKind[] = ['Animation', 'Audio', 'Vfx'];

export const SEMANTIC_EVENT_OPTIONS: readonly SemanticEventOption[] = [
  event('movement.jump_started', 'Jump started', 'A kinematic actor consumed a jump request.', ['Animation', 'Audio', 'Vfx']),
  event('movement.landed', 'Landed', 'A kinematic actor returned to the ground.', ['Animation', 'Audio', 'Vfx']),
  event('interaction.interacted', 'Interacted', 'An actor performed an interaction intent.', ['Animation', 'Audio', 'Vfx']),
  event('interaction.accepted', 'Interaction accepted', 'A target accepted an actor interaction.', ['Animation', 'Audio', 'Vfx']),
  event('inventory.pickup_accepted', 'Pickup accepted', 'An item entered an inventory.', ['Animation', 'Audio', 'Vfx']),
  event('inventory.equipped', 'Equipped', 'An actor equipped an inventory item.', ['Animation', 'Audio', 'Vfx']),
  event('inventory.dropped', 'Dropped', 'An actor dropped an inventory item.', ['Animation', 'Audio', 'Vfx']),
  event('combat.attack_started', 'Attack started', 'An actor started a generic attack action.', ['Animation', 'Audio', 'Vfx']),
  event('combat.hit_confirmed', 'Hit confirmed', 'Combat rules confirmed a hit.', ['Animation', 'Audio', 'Vfx']),
  event('combat.blocked', 'Blocked', 'Combat rules blocked a hit.', ['Animation', 'Audio', 'Vfx']),
  event('combat.parried', 'Parried', 'Combat rules parried or countered a hit.', ['Animation', 'Audio', 'Vfx']),
  event('combat.killed', 'Defeated', 'An entity was defeated by combat rules.', ['Animation', 'Audio', 'Vfx']),
  event('animation.command_requested', 'Animation requested', 'Runtime requested semantic animation playback.', ['Animation']),
  event('animation.playback_started', 'Animation started', 'Engine reported animation playback started.', ['Animation']),
  event('animation.playback_completed', 'Animation completed', 'Engine reported animation playback completed.', ['Animation']),
  event('audio.playback_requested', 'Audio requested', 'Runtime requested semantic audio playback.', ['Audio']),
  event('audio.playback_completed', 'Audio completed', 'Engine reported audio playback completed.', ['Audio']),
  event('vfx.playback_requested', 'VFX requested', 'Runtime requested semantic VFX playback.', ['Vfx']),
  event('vfx.playback_completed', 'VFX completed', 'Engine reported VFX playback completed.', ['Vfx']),
];

export const PLAYBACK_KIND_ASSET_TYPES: Record<SemanticPlaybackKind, readonly string[]> = {
  Animation: ['AnimationClip', 'AnimationController', 'ANIMATION_CLIP', 'ANIMATION_CONTROLLER'],
  Audio: ['AudioClip', 'AudioMusic', 'AUDIO_CLIP', 'AUDIO_MUSIC'],
  Vfx: ['Particle', 'PARTICLE'],
};

export function eventsForPlaybackKind(kind: SemanticPlaybackKind): readonly SemanticEventOption[] {
  return SEMANTIC_EVENT_OPTIONS.filter((item) => item.targets.includes(kind));
}

export function isAssetCompatibleWithPlaybackKind(asset: AssetRef, kind: SemanticPlaybackKind): boolean {
  const rawType = asset.asset_type?.trim();
  if (!rawType) {
    return false;
  }
  return PLAYBACK_KIND_ASSET_TYPES[kind].includes(rawType);
}

export function rustAssetType(assetType: string | undefined, kind: SemanticPlaybackKind): string {
  const raw = (assetType || '').trim();
  switch (raw) {
    case 'ANIMATION_CLIP': return 'AnimationClip';
    case 'ANIMATION_CONTROLLER': return 'AnimationController';
    case 'AUDIO_CLIP': return 'AudioClip';
    case 'AUDIO_MUSIC': return 'AudioMusic';
    case 'PARTICLE': return 'Particle';
    default:
      if (raw) return raw;
      if (kind === 'Animation') return 'AnimationClip';
      if (kind === 'Audio') return 'AudioClip';
      return 'Particle';
  }
}

export function rustAssetStatus(status: AssetRef['status'] | string | undefined): string {
  switch ((status || '').toLowerCase()) {
    case 'linked': return 'Linked';
    case 'missing': return 'Missing';
    case 'unresolved': return 'Unresolved';
    default: return 'Placeholder';
  }
}

export function defaultSemanticAction(kind: SemanticPlaybackKind): string {
  if (kind === 'Vfx') return 'spawn';
  return 'play';
}

export function defaultBindingId(eventName: string, kind: SemanticPlaybackKind, assetId: string): string {
  const base = `bind_${eventName}_${kind}_${assetId}`
    .replace(/[^A-Za-z0-9_]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
  return base.slice(0, 96) || 'bind_semantic_asset';
}

function event(
  name: string,
  label: string,
  summary: string,
  targets: readonly SemanticPlaybackKind[],
): SemanticEventOption {
  return { name, label, summary, targets };
}
