/**
 * Source-free causality graph for debugger state-change explanations.
 *
 * Runtime/proof tools can submit an explicit runtime_causality_trace payload.
 * The graph engine validates the DAG, keeps bounded retained traces, and
 * reports which prompt, mutation, system, event, RNG call, feedback, and
 * network packet nodes caused a selected state change.
 */

import type {
  RuntimeCausalityEdge,
  RuntimeCausalityNode,
  RuntimeCausalityNodeKind,
  RuntimeCausalityTraceMessage,
} from '../api/message_types';

export const CAUSALITY_NODE_KIND_ORDER = [
  'prompt',
  'mutation',
  'network_packet',
  'feedback',
  'system',
  'rng_call',
  'event',
  'state_change',
] as const;

export const REQUIRED_STATE_CHANGE_CAUSE_KINDS = [
  'prompt',
  'mutation',
  'system',
  'event',
  'rng_call',
  'feedback',
  'network_packet',
] as const;

export interface CausalityNode {
  readonly id: string;
  readonly kind: RuntimeCausalityNodeKind;
  readonly tick: number;
  readonly label: string;
  readonly detail: string;
  readonly fields: Readonly<Record<string, string>>;
}

export interface CausalityEdge {
  readonly from: string;
  readonly to: string;
  readonly relation: string;
}

export interface CausalityTrace {
  readonly traceId: string;
  readonly tick: number;
  readonly summary: string;
  readonly stateChangeNodeId: string;
  readonly nodes: readonly CausalityNode[];
  readonly edges: readonly CausalityEdge[];
}

export interface CausalityReport {
  readonly traceId: string;
  readonly tick: number;
  readonly summary: string;
  readonly stateChange: CausalityNode | null;
  readonly causeChain: readonly CausalityNode[];
  readonly causeEdges: readonly CausalityEdge[];
  readonly coverage: Readonly<Record<(typeof REQUIRED_STATE_CHANGE_CAUSE_KINDS)[number], boolean>>;
  readonly missingCauseKinds: readonly string[];
  readonly diagnostics: readonly string[];
  readonly complete: boolean;
}

const MAX_CAUSALITY_TRACES = 64;
const NODE_KIND_SET = new Set<string>(CAUSALITY_NODE_KIND_ORDER);

export class CausalityGraphEngine {
  private readonly retainedTraces: CausalityTrace[] = [];
  private readonly reportsByTraceId = new Map<string, CausalityReport>();

  ingestTrace(message: RuntimeCausalityTraceMessage): CausalityReport {
    const trace = normalizeRuntimeCausalityTrace(message);
    const report = reportStateChangeCause(trace, trace.stateChangeNodeId);
    const index = this.retainedTraces.findIndex((item) => item.traceId === trace.traceId);
    if (index >= 0) this.retainedTraces.splice(index, 1);
    this.retainedTraces.push(trace);
    trim(this.retainedTraces, MAX_CAUSALITY_TRACES);
    this.reportsByTraceId.set(trace.traceId, report);
    return report;
  }

  traces(): CausalityTrace[] {
    return [...this.retainedTraces];
  }

  reports(): CausalityReport[] {
    return this.retainedTraces
      .map((trace) => this.reportsByTraceId.get(trace.traceId))
      .filter((report): report is CausalityReport => Boolean(report));
  }

  latestReport(): CausalityReport | null {
    const trace = this.retainedTraces[this.retainedTraces.length - 1] ?? null;
    return trace ? this.reportsByTraceId.get(trace.traceId) ?? null : null;
  }

  reportForStateChange(traceId: string, stateChangeNodeId: string): CausalityReport | null {
    const trace = this.retainedTraces.find((item) => item.traceId === traceId);
    return trace ? reportStateChangeCause(trace, stateChangeNodeId) : null;
  }
}

export function normalizeRuntimeCausalityTrace(message: RuntimeCausalityTraceMessage): CausalityTrace {
  const nodes = (message.nodes ?? []).map(normalizeRuntimeCausalityNode);
  const edges = (message.edges ?? []).map(normalizeRuntimeCausalityEdge);
  return {
    traceId: message.trace_id || `trace-${message.tick}`,
    tick: finiteTick(message.tick),
    summary: message.summary ?? '',
    stateChangeNodeId: message.state_change_node_id ?? '',
    nodes,
    edges,
  };
}

export function reportStateChangeCause(
  trace: CausalityTrace,
  stateChangeNodeId: string = trace.stateChangeNodeId,
): CausalityReport {
  const diagnostics = validateTraceShape(trace);
  const nodeById = new Map(trace.nodes.map((node) => [node.id, node]));
  const target = nodeById.get(stateChangeNodeId) ?? null;
  if (!target) {
    const coverage = emptyCoverage();
    return {
      traceId: trace.traceId,
      tick: trace.tick,
      summary: trace.summary,
      stateChange: null,
      causeChain: [],
      causeEdges: [],
      coverage,
      missingCauseKinds: [...REQUIRED_STATE_CHANGE_CAUSE_KINDS],
      diagnostics: [...diagnostics, `state_change node '${stateChangeNodeId}' is missing`],
      complete: false,
    };
  }

  const ancestorIds = ancestorNodeIds(trace.edges, target.id);
  ancestorIds.add(target.id);
  const causeNodes = topoSortReachable(trace.nodes, trace.edges, ancestorIds);
  const causeEdges = trace.edges.filter((edge) => ancestorIds.has(edge.from) && ancestorIds.has(edge.to));
  const coverage = emptyCoverage();
  for (const node of causeNodes) {
    if (isRequiredCauseKind(node.kind)) coverage[node.kind] = true;
  }
  const missingCauseKinds = REQUIRED_STATE_CHANGE_CAUSE_KINDS.filter((kind) => !coverage[kind]);
  const complete =
    target.kind === 'state_change' &&
    missingCauseKinds.length === 0 &&
    diagnostics.length === 0 &&
    causeNodes.some((node) => node.id === target.id);
  return {
    traceId: trace.traceId,
    tick: trace.tick,
    summary: trace.summary,
    stateChange: target,
    causeChain: causeNodes,
    causeEdges,
    coverage,
    missingCauseKinds,
    diagnostics,
    complete,
  };
}

export function summarizeCausalityReport(report: CausalityReport): string {
  const target = report.stateChange ? `${report.stateChange.label} ${report.stateChange.detail}`.trim() : '<missing state change>';
  const missing = report.missingCauseKinds.length ? ` missing:${report.missingCauseKinds.join(',')}` : '';
  return `#${report.tick} ${report.complete ? 'complete' : 'incomplete'} ${target}${missing}`;
}

function normalizeRuntimeCausalityNode(node: RuntimeCausalityNode): CausalityNode {
  const kind = NODE_KIND_SET.has(node.kind) ? node.kind : 'state_change';
  return {
    id: node.id,
    kind,
    tick: finiteTick(node.tick ?? 0),
    label: node.label || node.id,
    detail: node.detail ?? '',
    fields: normalizeFields(node.fields ?? {}),
  };
}

function normalizeRuntimeCausalityEdge(edge: RuntimeCausalityEdge): CausalityEdge {
  return {
    from: edge.from,
    to: edge.to,
    relation: edge.relation || 'caused',
  };
}

function validateTraceShape(trace: CausalityTrace): string[] {
  const diagnostics: string[] = [];
  const seen = new Set<string>();
  for (const node of trace.nodes) {
    if (!node.id) diagnostics.push('node id is empty');
    if (seen.has(node.id)) diagnostics.push(`duplicate node id '${node.id}'`);
    seen.add(node.id);
    if (!NODE_KIND_SET.has(node.kind)) diagnostics.push(`unsupported node kind '${node.kind}'`);
  }
  for (const edge of trace.edges) {
    if (!seen.has(edge.from)) diagnostics.push(`edge from '${edge.from}' is missing`);
    if (!seen.has(edge.to)) diagnostics.push(`edge to '${edge.to}' is missing`);
  }
  if (hasCycle(trace.nodes, trace.edges)) diagnostics.push('causality graph contains a cycle');
  return diagnostics;
}

function ancestorNodeIds(edges: readonly CausalityEdge[], nodeId: string): Set<string> {
  const incoming = new Map<string, string[]>();
  edges.forEach((edge) => {
    const list = incoming.get(edge.to) ?? [];
    list.push(edge.from);
    incoming.set(edge.to, list);
  });
  const result = new Set<string>();
  const stack = [...(incoming.get(nodeId) ?? [])];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || result.has(current)) continue;
    result.add(current);
    stack.push(...(incoming.get(current) ?? []));
  }
  return result;
}

function topoSortReachable(
  nodes: readonly CausalityNode[],
  edges: readonly CausalityEdge[],
  reachableIds: ReadonlySet<string>,
): CausalityNode[] {
  const nodeById = new Map(nodes.filter((node) => reachableIds.has(node.id)).map((node) => [node.id, node]));
  const indegree = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  nodeById.forEach((_node, id) => indegree.set(id, 0));
  edges.forEach((edge) => {
    if (!nodeById.has(edge.from) || !nodeById.has(edge.to)) return;
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge.to]);
    indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1);
  });
  const ready = Array.from(indegree.entries())
    .filter(([, degree]) => degree === 0)
    .map(([id]) => id)
    .sort((left, right) => compareNodes(nodeById.get(left), nodeById.get(right)));
  const ordered: CausalityNode[] = [];
  while (ready.length > 0) {
    const current = ready.shift();
    if (!current) continue;
    const node = nodeById.get(current);
    if (node) ordered.push(node);
    for (const next of outgoing.get(current) ?? []) {
      indegree.set(next, (indegree.get(next) ?? 0) - 1);
      if ((indegree.get(next) ?? 0) === 0) {
        ready.push(next);
        ready.sort((left, right) => compareNodes(nodeById.get(left), nodeById.get(right)));
      }
    }
  }
  if (ordered.length !== nodeById.size) {
    return Array.from(nodeById.values()).sort(compareNodes);
  }
  return ordered;
}

function hasCycle(nodes: readonly CausalityNode[], edges: readonly CausalityEdge[]): boolean {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const indegree = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  nodeIds.forEach((id) => indegree.set(id, 0));
  edges.forEach((edge) => {
    if (!nodeIds.has(edge.from) || !nodeIds.has(edge.to)) return;
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge.to]);
    indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1);
  });
  const ready = Array.from(indegree.entries()).filter(([, degree]) => degree === 0).map(([id]) => id);
  let visited = 0;
  while (ready.length > 0) {
    const current = ready.shift();
    if (!current) continue;
    visited += 1;
    for (const next of outgoing.get(current) ?? []) {
      indegree.set(next, (indegree.get(next) ?? 0) - 1);
      if ((indegree.get(next) ?? 0) === 0) ready.push(next);
    }
  }
  return visited !== nodeIds.size;
}

function compareNodes(left: CausalityNode | undefined, right: CausalityNode | undefined): number {
  if (!left || !right) return left ? -1 : right ? 1 : 0;
  const tickCompare = left.tick - right.tick;
  if (tickCompare !== 0) return tickCompare;
  const kindCompare = CAUSALITY_NODE_KIND_ORDER.indexOf(left.kind) - CAUSALITY_NODE_KIND_ORDER.indexOf(right.kind);
  if (kindCompare !== 0) return kindCompare;
  return left.id.localeCompare(right.id);
}

function emptyCoverage(): Record<(typeof REQUIRED_STATE_CHANGE_CAUSE_KINDS)[number], boolean> {
  return {
    prompt: false,
    mutation: false,
    system: false,
    event: false,
    rng_call: false,
    feedback: false,
    network_packet: false,
  };
}

function isRequiredCauseKind(kind: RuntimeCausalityNodeKind): kind is (typeof REQUIRED_STATE_CHANGE_CAUSE_KINDS)[number] {
  return (REQUIRED_STATE_CHANGE_CAUSE_KINDS as readonly string[]).includes(kind);
}

function normalizeFields(fields: Record<string, unknown>): Record<string, string> {
  const normalized: Record<string, string> = {};
  Object.keys(fields).sort().forEach((key) => {
    normalized[key] = stringifyField(fields[key]);
  });
  return normalized;
}

function stringifyField(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function finiteTick(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0;
}

function trim<T>(items: T[], limit: number): void {
  if (items.length > limit) items.splice(0, items.length - limit);
}
