/**
 * cgs.ts — Canonical Game Schema type definitions
 *
 * TypeScript mirror of the Python CGS dataclasses in packages/core.
 * These types are the source of truth for all UI components.
 * Must stay in sync with the Python schema — any field addition on
 * the backend requires a corresponding addition here.
 *
 * IMPORTANT: These types are read-only from the UI perspective.
 * All mutations go through PIL → builder_server → PILPipeline.
 * Direct CGS manipulation from the UI is a contract violation.
 */

// ── Primitives & enumerations ────────────────────────────────────────────────

export type ControlType =
  | 'Human'
  | 'AiProxy'
  | 'NetworkAuthority'
  | 'Replay';

export type ActorType =
  | 'PlayerCharacter'
  | 'Enemy'
  | 'NPC'
  | 'Projectile'
  | 'Obstacle'
  | 'Collectible'
  | 'Environment'
  | 'Trigger'
  | 'Camera'
  | string;  // extensible — game-specific types allowed

export type ExecutionPhase =
  | 'Input'
  | 'Simulation'
  | 'PostSimulation'
  | 'Render';

export type RiskLevel = 'low' | 'medium' | 'high';

export type SchemaDeltaType =
  | 'value_mutation'
  | 'structural_add'
  | 'structural_remove'
  | 'structural_modify';

export type VersionBump = 'patch' | 'minor' | 'major';

// ── Component field values ────────────────────────────────────────────────────

/**
 * Recursive type for component default values.
 * Mirrors Python's Any in component defaults, but safely typed.
 */
export type CGSFieldValue =
  | number
  | string
  | boolean
  | null
  | CGSFieldValue[]
  | { [key: string]: CGSFieldValue };

export type CGSComponentDefaults = Record<string, CGSFieldValue>;

// ── Core schema nodes ─────────────────────────────────────────────────────────

export interface CGSComponent {
  /** UCL component type ID — e.g. 5 = COMP_VELOCITY_V1 */
  readonly type_id:  number;
  /** Human name — e.g. "COMP_VELOCITY_V1" */
  readonly name:     string;
  /** Default field values at schema definition time */
  readonly defaults: CGSComponentDefaults;
}

export interface CGSComponentSchema extends CGSComponent {
  /** Provenance label for schema-only tables, e.g. "generated" or "plugin" */
  readonly source?: string;
}

export interface CGSActor {
  readonly id:           string;
  readonly actor_type:   ActorType;
  readonly control_type: ControlType;
  readonly components:   CGSComponent[];
}

export interface CGSSystem {
  readonly id:            string;
  readonly phase:         ExecutionPhase;
  /** Component type_ids this system reads (read-only access) */
  readonly reads:         readonly number[];
  /** Component type_ids this system writes (via MutationGate) */
  readonly writes:        readonly number[];
  readonly depends_on:    readonly string[];
  readonly deterministic: boolean;
  readonly runtime_executor?: Record<string, CGSFieldValue>;
}

export interface CGSRule {
  readonly id:        string;
  readonly condition: string;   // e.g. "current <= 0"
  readonly effect:    string;   // e.g. "game_over()"
  readonly priority:  number;
  readonly is_active: boolean;
}

export interface CGSMode {
  readonly id:         string;
  readonly is_default: boolean;
  readonly actors:     CGSActor[];
  readonly systems:    CGSSystem[];
  readonly rules:      CGSRule[];
}

export interface CGSMetadata {
  readonly name:           string;
  readonly cgs_hash:       string;
  readonly version:        string;
  readonly schema_version: string;
  readonly description?:   string;
}

/** The complete Canonical Game Schema — root document */
export interface CGS {
  readonly metadata:       CGSMetadata;
  readonly component_schemas?: CGSComponentSchema[];
  readonly global_systems: CGSSystem[];
  readonly modes:          CGSMode[];
}

// ── Version snapshot (from HistoryManager) ────────────────────────────────────

export interface CGSSnapshot {
  readonly cgs_hash:       string;
  readonly schema_version: string;
  readonly turn_index:     number;
  readonly mutation_count: number;
  readonly timestamp:      number;   // Unix epoch ms
  readonly summary?:       string;
  readonly version_bump?:  VersionBump;
  readonly risk_level?:    RiskLevel;
}

// ── Asset references ──────────────────────────────────────────────────────────

export type AssetLinkStatus = 'linked' | 'placeholder' | 'missing';

export interface AssetRef {
  readonly placeholder_id: string;  // e.g. "zombie_mesh"
  readonly asset_path?:    string;  // local path once linked
  readonly status:         AssetLinkStatus;
  readonly component_name: string;  // which component holds this ref
  readonly actor_id:       string;
}

// ── Derived / computed types ──────────────────────────────────────────────────

/** An actor with its parent mode context attached */
export interface LocatedActor {
  readonly actor:  CGSActor;
  readonly modeId: string;
}

/** A system with its context (global vs mode-specific) */
export interface LocatedSystem {
  readonly system: CGSSystem;
  readonly modeId: string | 'global';
}

/** Minimal node representation for graph rendering */
export type GraphNodeKind = 'mode' | 'actor' | 'component' | 'system' | 'rule';

export interface CGSGraphNode {
  readonly id:         string;
  readonly kind:       GraphNodeKind;
  readonly label:      string;
  readonly phase?:     ExecutionPhase;  // system nodes only
  readonly typeId?:    number;          // component nodes only
  readonly modeId?:    string;
  /** Derived: component count for actors, reads+writes for systems */
  readonly weight:     number;
}

export type GraphEdgeKind = 'contains' | 'has' | 'reads' | 'writes' | 'depends_on' | 'triggers';

export interface CGSGraphEdge {
  readonly source: string;   // node id
  readonly target: string;   // node id
  readonly kind:   GraphEdgeKind;
}

export interface CGSGraph {
  readonly nodes: CGSGraphNode[];
  readonly edges: CGSGraphEdge[];
}

// ── Utility functions ─────────────────────────────────────────────────────────

export function findActor(cgs: CGS, actorId: string): LocatedActor | null {
  for (const mode of cgs.modes) {
    const actor = mode.actors.find(a => a.id === actorId);
    if (actor) return { actor, modeId: mode.id };
  }
  return null;
}

export function findSystem(cgs: CGS, systemId: string): LocatedSystem | null {
  const global = cgs.global_systems.find(s => s.id === systemId);
  if (global) return { system: global, modeId: 'global' };
  for (const mode of cgs.modes) {
    const sys = mode.systems.find(s => s.id === systemId);
    if (sys) return { system: sys, modeId: mode.id };
  }
  return null;
}

export function allActors(cgs: CGS): LocatedActor[] {
  return cgs.modes.flatMap(mode =>
    mode.actors.map(actor => ({ actor, modeId: mode.id }))
  );
}

export function allSystems(cgs: CGS): LocatedSystem[] {
  return [
    ...cgs.global_systems.map(system => ({ system, modeId: 'global' as const })),
    ...cgs.modes.flatMap(mode =>
      mode.systems.map(system => ({ system, modeId: mode.id }))
    ),
  ];
}

export function findComponentByTypeId(
  cgs: CGS,
  typeId: number,
): CGSComponent | null {
  for (const { actor } of allActors(cgs)) {
    const comp = actor.components.find(c => c.type_id === typeId);
    if (comp) return comp;
  }
  return null;
}

export function defaultMode(cgs: CGS): CGSMode | null {
  return cgs.modes.find(m => m.is_default) ?? cgs.modes[0] ?? null;
}

/** Systems that read a given component type_id */
export function readersOf(cgs: CGS, typeId: number): LocatedSystem[] {
  return allSystems(cgs).filter(({ system }) =>
    (system.reads as readonly number[]).includes(typeId)
  );
}

/** Systems that write a given component type_id */
export function writersOf(cgs: CGS, typeId: number): LocatedSystem[] {
  return allSystems(cgs).filter(({ system }) =>
    (system.writes as readonly number[]).includes(typeId)
  );
}

/** Build a graph representation of the whole CGS for force-directed layout */
export function buildCGSGraph(cgs: CGS): CGSGraph {
  const nodes: CGSGraphNode[] = [];
  const edges: CGSGraphEdge[] = [];

  for (const mode of cgs.modes) {
    nodes.push({
      id: `mode:${mode.id}`, kind: 'mode',
      label: mode.id, modeId: mode.id, weight: 3,
    });

    for (const actor of mode.actors) {
      const actorNodeId = `actor:${mode.id}:${actor.id}`;
      nodes.push({
        id: actorNodeId, kind: 'actor',
        label: actor.id, modeId: mode.id,
        weight: Math.max(1, actor.components.length),
      });
      edges.push({
        source: `mode:${mode.id}`, target: actorNodeId, kind: 'contains',
      });

      for (const comp of actor.components) {
        const compNodeId = `comp:${comp.type_id}`;
        if (!nodes.find(n => n.id === compNodeId)) {
          nodes.push({
            id: compNodeId, kind: 'component',
            label: comp.name, typeId: comp.type_id, weight: 1,
          });
        }
        edges.push({ source: actorNodeId, target: compNodeId, kind: 'has' });
      }
    }

    for (const sys of mode.systems) {
      const sysNodeId = `sys:${mode.id}:${sys.id}`;
      nodes.push({
        id: sysNodeId, kind: 'system',
        label: sys.id, phase: sys.phase, modeId: mode.id,
        weight: sys.reads.length + sys.writes.length,
      });
      for (const typeId of sys.reads) {
        edges.push({
          source: sysNodeId, target: `comp:${typeId}`, kind: 'reads',
        });
      }
      for (const typeId of sys.writes) {
        edges.push({
          source: sysNodeId, target: `comp:${typeId}`, kind: 'writes',
        });
      }
      for (const dep of sys.depends_on) {
        // depends_on links will be resolved after all systems are indexed
        edges.push({
          source: sysNodeId,
          target: `sys:${mode.id}:${dep}`,
          kind: 'depends_on',
        });
      }
    }

    for (const rule of mode.rules) {
      nodes.push({
        id: `rule:${mode.id}:${rule.id}`, kind: 'rule',
        label: rule.id, modeId: mode.id, weight: 1,
      });
    }
  }

  for (const sys of cgs.global_systems) {
    const sysNodeId = `sys:global:${sys.id}`;
    nodes.push({
      id: sysNodeId, kind: 'system',
      label: sys.id, phase: sys.phase, modeId: 'global',
      weight: sys.reads.length + sys.writes.length,
    });
  }

  return { nodes, edges };
}

/** Empty CGS sentinel — used before first server response */
export const EMPTY_CGS: CGS = {
  metadata: {
    name: 'Loading…',
    cgs_hash: '',
    version: '0.0.0',
    schema_version: '0.0.0',
  },
  global_systems: [],
  modes: [],
};
