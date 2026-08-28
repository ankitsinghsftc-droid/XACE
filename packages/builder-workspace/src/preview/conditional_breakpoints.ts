/**
 * Source-free conditional breakpoint evaluation for the live tick debugger.
 *
 * The evaluator consumes protocol/debugger records only. It does not inspect
 * generated source, so the same conditions work for engine ticks, runtime
 * control snapshots, replay/debug traces, and retained synthetic proofs.
 */

import type {
  RuntimeDebugTraceMessage,
  RuntimeEntityState,
  RuntimeGameEvent,
} from '../api/message_types';

export const BREAKPOINT_KIND_ORDER = [
  'entity_state',
  'component_value',
  'event_type',
  'mutation_type',
  'system_id',
  'rng_call',
  'hash_mismatch',
  'network_desync',
] as const;

export type BreakpointKind = (typeof BREAKPOINT_KIND_ORDER)[number];
export type BreakpointOperator = 'exists' | 'equals' | 'contains' | 'changed';

export interface ConditionalBreakpoint {
  readonly id: string;
  readonly label: string;
  readonly kind: BreakpointKind;
  readonly enabled: boolean;
  readonly operator: BreakpointOperator;
  readonly field?: string;
  readonly value?: string;
  readonly description: string;
}

export interface BreakpointCandidate {
  readonly tick: number;
  readonly kind: BreakpointKind;
  readonly source: string;
  readonly detail: string;
  readonly fields: Readonly<Record<string, string>>;
}

export interface BreakpointHit extends BreakpointCandidate {
  readonly key: string;
  readonly breakpointId: string;
  readonly label: string;
}

export interface SnapshotBreakpointInput {
  readonly tick: number;
  readonly source: string;
  readonly entities: readonly RuntimeEntityState[];
  readonly spawnedIds: readonly number[];
  readonly destroyedIds: readonly number[];
  readonly events: readonly RuntimeGameEvent[];
}

export interface MutationBreakpointInput {
  readonly tick: number;
  readonly kind: string;
  readonly entityId: string;
  readonly component: string;
  readonly detail: string;
}

export interface HashMismatchBreakpointInput {
  readonly tick: number;
  readonly expectedHash: string;
  readonly actualHash: string;
  readonly source: string;
}

const MAX_BREAKPOINT_HITS = 96;

export class ConditionalBreakpointEngine {
  private readonly conditions = new Map<string, ConditionalBreakpoint>();
  private readonly seenHitKeys = new Set<string>();
  private readonly hitHistory: BreakpointHit[] = [];

  constructor(breakpoints: readonly ConditionalBreakpoint[] = defaultConditionalBreakpoints()) {
    breakpoints.forEach((breakpoint) => this.conditions.set(breakpoint.id, breakpoint));
  }

  breakpoints(): ConditionalBreakpoint[] {
    return BREAKPOINT_KIND_ORDER.flatMap((kind) =>
      Array.from(this.conditions.values()).filter((breakpoint) => breakpoint.kind === kind),
    );
  }

  hits(): BreakpointHit[] {
    return [...this.hitHistory];
  }

  setBreakpointEnabled(id: string, enabled: boolean): ConditionalBreakpoint | null {
    const current = this.conditions.get(id);
    if (!current) return null;
    const updated = { ...current, enabled };
    this.conditions.set(id, updated);
    return updated;
  }

  evaluateCandidate(candidate: BreakpointCandidate): BreakpointHit[] {
    const hits: BreakpointHit[] = [];
    for (const breakpoint of this.conditions.values()) {
      if (!breakpoint.enabled || breakpoint.kind !== candidate.kind) continue;
      if (!breakpointMatchesCandidate(breakpoint, candidate)) continue;
      const key = `${breakpoint.id}:${candidate.tick}:${candidate.kind}:${candidateFingerprint(candidate)}`;
      if (this.seenHitKeys.has(key)) continue;
      this.seenHitKeys.add(key);
      const hit: BreakpointHit = {
        ...candidate,
        key,
        breakpointId: breakpoint.id,
        label: breakpoint.label,
      };
      this.hitHistory.push(hit);
      trim(this.hitHistory, MAX_BREAKPOINT_HITS);
      hits.push(hit);
    }
    return hits;
  }

  evaluateCandidates(candidates: readonly BreakpointCandidate[]): BreakpointHit[] {
    return candidates.flatMap((candidate) => this.evaluateCandidate(candidate));
  }
}

export function defaultConditionalBreakpoints(): ConditionalBreakpoint[] {
  return [
    {
      id: 'bp-entity-state',
      label: 'Entity state',
      kind: 'entity_state',
      enabled: false,
      operator: 'changed',
      field: 'state',
      description: 'Break when an entity is spawned, destroyed, appears, or changes identity metadata.',
    },
    {
      id: 'bp-component-value',
      label: 'Component value',
      kind: 'component_value',
      enabled: false,
      operator: 'changed',
      field: 'value',
      description: 'Break when a component value appears, disappears, or changes.',
    },
    {
      id: 'bp-event-type',
      label: 'Event type',
      kind: 'event_type',
      enabled: false,
      operator: 'exists',
      field: 'event_type',
      description: 'Break when a runtime event type is observed.',
    },
    {
      id: 'bp-mutation-type',
      label: 'Mutation type',
      kind: 'mutation_type',
      enabled: false,
      operator: 'exists',
      field: 'mutation_type',
      description: 'Break when a snapshot-derived mutation type is observed.',
    },
    {
      id: 'bp-system-id',
      label: 'System ID',
      kind: 'system_id',
      enabled: false,
      operator: 'exists',
      field: 'system_id',
      description: 'Break when a runtime debug trace reports an executed or candidate system.',
    },
    {
      id: 'bp-rng-call',
      label: 'RNG call',
      kind: 'rng_call',
      enabled: false,
      operator: 'exists',
      field: 'system_id',
      description: 'Break when a runtime debug trace reports a deterministic RNG call.',
    },
    {
      id: 'bp-hash-mismatch',
      label: 'Hash mismatch',
      kind: 'hash_mismatch',
      enabled: false,
      operator: 'exists',
      field: 'actual_hash',
      description: 'Break when two observed hashes disagree for the same tick.',
    },
    {
      id: 'bp-network-desync',
      label: 'Network desync',
      kind: 'network_desync',
      enabled: false,
      operator: 'exists',
      field: 'peer_id',
      description: 'Break when runtime/network diagnostics report a divergent peer.',
    },
  ];
}

export function snapshotBreakpointCandidates(
  current: SnapshotBreakpointInput,
  previous: SnapshotBreakpointInput | null,
): BreakpointCandidate[] {
  const candidates: BreakpointCandidate[] = [];
  const previousEntities = entityMap(previous?.entities ?? []);
  const currentEntities = entityMap(current.entities);

  current.spawnedIds.forEach((id) => {
    const entity = currentEntities.get(id);
    candidates.push(entityStateCandidate(current.tick, current.source, id, 'spawned', entity));
  });
  current.destroyedIds.forEach((id) => {
    const entity = previousEntities.get(id);
    candidates.push(entityStateCandidate(current.tick, current.source, id, 'destroyed', entity));
  });

  if (!previous) {
    current.entities.forEach((entity) => {
      candidates.push(entityStateCandidate(current.tick, current.source, entity.id, 'visible', entity));
      Object.entries(entity.components).forEach(([component, value]) => {
        candidates.push(componentCandidate(current.tick, current.source, entity, component, '<missing>', value));
      });
    });
    return candidates;
  }

  current.entities.forEach((entity) => {
    const before = previousEntities.get(entity.id);
    if (!before) {
      candidates.push(entityStateCandidate(current.tick, current.source, entity.id, 'spawned', entity));
      Object.entries(entity.components).forEach(([component, value]) => {
        candidates.push(componentCandidate(current.tick, current.source, entity, component, '<missing>', value));
      });
      return;
    }
    if ((before.actor_id ?? '') !== (entity.actor_id ?? '')) {
      candidates.push(entityStateCandidate(current.tick, current.source, entity.id, 'metadata_changed', entity, before.actor_id ?? ''));
    }
    Array.from(new Set([...Object.keys(before.components), ...Object.keys(entity.components)])).sort().forEach((component) => {
      const oldValue = before.components[component] ?? '<missing>';
      const newValue = entity.components[component] ?? '<missing>';
      if (oldValue === newValue) return;
      candidates.push(componentCandidate(current.tick, current.source, entity, component, oldValue, newValue));
    });
  });

  for (const [id, entity] of previousEntities) {
    if (!currentEntities.has(id)) candidates.push(entityStateCandidate(current.tick, current.source, id, 'destroyed', entity));
  }

  return candidates;
}

export function eventBreakpointCandidates(
  tick: number,
  events: readonly RuntimeGameEvent[],
): BreakpointCandidate[] {
  return events.map((event, index) => ({
    tick,
    kind: 'event_type',
    source: 'runtime_event_trace',
    detail: `${event.event_type} entity:${event.entity_id}`,
    fields: {
      event_type: event.event_type,
      entity_id: String(event.entity_id),
      index: String(index),
      data: stableJson(event.data ?? {}),
    },
  }));
}

export function mutationBreakpointCandidate(mutation: MutationBreakpointInput): BreakpointCandidate {
  return {
    tick: mutation.tick,
    kind: 'mutation_type',
    source: 'snapshot_mutation_history',
    detail: `${mutation.kind} entity:${mutation.entityId} ${mutation.component} ${mutation.detail}`.trim(),
    fields: {
      mutation_type: mutation.kind,
      entity_id: mutation.entityId,
      component: mutation.component,
      detail: mutation.detail,
    },
  };
}

export function hashMismatchBreakpointCandidate(record: HashMismatchBreakpointInput): BreakpointCandidate {
  return {
    tick: record.tick,
    kind: 'hash_mismatch',
    source: record.source,
    detail: `expected:${record.expectedHash} actual:${record.actualHash}`,
    fields: {
      expected_hash: record.expectedHash,
      actual_hash: record.actualHash,
      source: record.source,
    },
  };
}

export function runtimeDebugTraceBreakpointCandidates(message: RuntimeDebugTraceMessage): BreakpointCandidate[] {
  const candidates: BreakpointCandidate[] = [];
  (message.systems ?? []).forEach((system, index) => {
    candidates.push({
      tick: message.tick,
      kind: 'system_id',
      source: 'runtime_debug_trace.systems',
      detail: `${system.system_id} ${system.phase ?? ''}`.trim(),
      fields: {
        system_id: system.system_id,
        phase: system.phase ?? '',
        index: String(index),
      },
    });
  });
  (message.rng_calls ?? []).forEach((rng, index) => {
    const result = rng.result ?? rng.value;
    candidates.push({
      tick: message.tick,
      kind: 'rng_call',
      source: 'runtime_debug_trace.rng_calls',
      detail: `${rng.system_id} seed:${String(rng.seed ?? '')} stream:${rng.stream_id ?? ''} result:${String(result ?? '')}`,
      fields: {
        system_id: rng.system_id,
        seed: String(rng.seed ?? ''),
        stream_id: rng.stream_id ?? '',
        stream_position: String(rng.stream_position ?? ''),
        call_index: String(rng.call_index ?? index),
        result: String(result ?? ''),
        value: String(result ?? ''),
        deterministic: String(rng.deterministic ?? true),
      },
    });
  });
  (message.network_desyncs ?? []).forEach((desync, index) => {
    candidates.push({
      tick: message.tick,
      kind: 'network_desync',
      source: 'runtime_debug_trace.network_desyncs',
      detail: `peer:${String(desync.peer_id ?? '')} ${desync.reason ?? ''}`.trim(),
      fields: {
        peer_id: String(desync.peer_id ?? ''),
        expected_hash: desync.expected_hash ?? '',
        actual_hash: desync.actual_hash ?? '',
        reason: desync.reason ?? '',
        index: String(index),
      },
    });
  });
  return candidates;
}

function breakpointMatchesCandidate(breakpoint: ConditionalBreakpoint, candidate: BreakpointCandidate): boolean {
  if (breakpoint.operator === 'exists') return true;
  const fieldValue = valueForBreakpointField(breakpoint, candidate);
  const target = breakpoint.value ?? '';
  if (breakpoint.operator === 'equals') return normalize(fieldValue) === normalize(target);
  if (breakpoint.operator === 'contains') return normalize(fieldValue).includes(normalize(target));
  if (breakpoint.operator === 'changed') {
    const before = candidate.fields['before'] ?? '';
    const after = candidate.fields['after'] ?? candidate.fields['value'] ?? '';
    return before !== after || fieldValue.length > 0;
  }
  return false;
}

function valueForBreakpointField(breakpoint: ConditionalBreakpoint, candidate: BreakpointCandidate): string {
  if (breakpoint.field && candidate.fields[breakpoint.field] !== undefined) {
    return candidate.fields[breakpoint.field] ?? '';
  }
  return `${candidate.detail} ${Object.values(candidate.fields).join(' ')}`;
}

function entityStateCandidate(
  tick: number,
  source: string,
  entityId: number,
  state: string,
  entity: RuntimeEntityState | undefined,
  beforeActorId = '',
): BreakpointCandidate {
  return {
    tick,
    kind: 'entity_state',
    source,
    detail: `entity:${entityId} ${state}`,
    fields: {
      entity_id: String(entityId),
      actor_id: entity?.actor_id ?? '',
      before_actor_id: beforeActorId,
      after_actor_id: entity?.actor_id ?? '',
      state,
    },
  };
}

function componentCandidate(
  tick: number,
  source: string,
  entity: RuntimeEntityState,
  component: string,
  before: string,
  after: string,
): BreakpointCandidate {
  return {
    tick,
    kind: 'component_value',
    source,
    detail: `entity:${entity.id} ${component} ${before} -> ${after}`,
    fields: {
      entity_id: String(entity.id),
      actor_id: entity.actor_id ?? '',
      component,
      before,
      after,
      value: after,
    },
  };
}

function entityMap(entities: readonly RuntimeEntityState[]): Map<number, RuntimeEntityState> {
  const map = new Map<number, RuntimeEntityState>();
  entities.forEach((entity) => map.set(entity.id, entity));
  return map;
}

function candidateFingerprint(candidate: BreakpointCandidate): string {
  return Object.keys(candidate.fields)
    .sort()
    .map((key) => `${key}=${candidate.fields[key]}`)
    .join('|');
}

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(sortJson(value));
  } catch {
    return String(value);
  }
}

function sortJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => sortJson(item));
  if (value && typeof value === 'object') {
    const sorted: Record<string, unknown> = {};
    Object.keys(value as Record<string, unknown>).sort().forEach((key) => {
      sorted[key] = sortJson((value as Record<string, unknown>)[key]);
    });
    return sorted;
  }
  return value;
}

function trim<T>(items: T[], limit: number): void {
  if (items.length > limit) items.splice(0, items.length - limit);
}
