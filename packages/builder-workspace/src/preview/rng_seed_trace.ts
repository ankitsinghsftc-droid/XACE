/**
 * Source-free RNG seed trace for deterministic debugger inspection.
 *
 * Runtime/proof tools can submit explicit runtime_rng_trace payloads that make
 * every deterministic RNG call visible by tick, system, seed, stream position,
 * and result. Legacy runtime_debug_trace.rng_calls are also normalized into the
 * same panel when present, but they are marked incomplete if seed/result fields
 * are absent.
 */

import type {
  RuntimeDebugRngCallTrace,
  RuntimeDebugTraceMessage,
  RuntimeRngTraceCall,
  RuntimeRngTraceMessage,
  RuntimeRngTraceViolation,
} from '../api/message_types';

export type RngSeedTraceSource = 'runtime_rng_trace' | 'runtime_debug_trace.rng_calls';

export interface RngSeedTraceCall {
  readonly tick: number;
  readonly systemId: string;
  readonly seed: string;
  readonly streamId: string;
  readonly streamPosition: number | null;
  readonly result: string;
  readonly callIndex: number;
  readonly deterministic: boolean;
  readonly source: RngSeedTraceSource;
}

export interface RngSeedTraceViolationRecord {
  readonly tick: number;
  readonly systemId: string;
  readonly reason: string;
  readonly source: string;
  readonly blocked: boolean;
}

export interface RngSeedReplayEvidence {
  readonly replayId: string;
  readonly firstHash: string;
  readonly secondHash: string;
  readonly identical: boolean;
}

export interface RngSeedTraceReport {
  readonly tick: number;
  readonly calls: readonly RngSeedTraceCall[];
  readonly violations: readonly RngSeedTraceViolationRecord[];
  readonly replay: readonly RngSeedReplayEvidence[];
  readonly deterministicCallCount: number;
  readonly visibleDeterministicCallCount: number;
  readonly retainedCallCount: number;
  readonly illegalBlocked: boolean;
  readonly legalReplayIdentical: boolean;
  readonly missingFields: readonly string[];
  readonly complete: boolean;
}

const MAX_RNG_TRACE_CALLS = 256;
const MAX_RNG_TRACE_VIOLATIONS = 64;
const MAX_RNG_REPLAY_EVIDENCE = 32;

export class RngSeedTraceEngine {
  private readonly retainedCalls: RngSeedTraceCall[] = [];
  private readonly retainedViolations: RngSeedTraceViolationRecord[] = [];
  private readonly retainedReplay: RngSeedReplayEvidence[] = [];
  private report: RngSeedTraceReport | null = null;

  ingestRuntimeRngTrace(message: RuntimeRngTraceMessage): RngSeedTraceReport {
    const calls = (message.calls ?? []).map((call, index) => normalizeRuntimeRngTraceCall(message.tick, call, index));
    const violations = (message.violations ?? []).map((violation) => normalizeRuntimeRngTraceViolation(message.tick, violation));
    const replay = message.replay ? [normalizeRuntimeReplayEvidence(message.replay)] : [];
    this.retainedCalls.push(...calls);
    this.retainedViolations.push(...violations);
    this.retainedReplay.push(...replay);
    trim(this.retainedCalls, MAX_RNG_TRACE_CALLS);
    trim(this.retainedViolations, MAX_RNG_TRACE_VIOLATIONS);
    trim(this.retainedReplay, MAX_RNG_REPLAY_EVIDENCE);
    this.report = buildReport(message.tick, calls, violations, replay, this.retainedCalls.length);
    return this.report;
  }

  ingestRuntimeDebugTrace(message: RuntimeDebugTraceMessage): RngSeedTraceReport | null {
    const calls = (message.rng_calls ?? []).map((call, index) => normalizeRuntimeDebugRngCall(message.tick, call, index));
    if (calls.length === 0) return this.report;
    this.retainedCalls.push(...calls);
    trim(this.retainedCalls, MAX_RNG_TRACE_CALLS);
    this.report = buildReport(message.tick, calls, [], [], this.retainedCalls.length);
    return this.report;
  }

  calls(): RngSeedTraceCall[] {
    return [...this.retainedCalls];
  }

  violations(): RngSeedTraceViolationRecord[] {
    return [...this.retainedViolations];
  }

  replayEvidence(): RngSeedReplayEvidence[] {
    return [...this.retainedReplay];
  }

  latestReport(): RngSeedTraceReport | null {
    return this.report;
  }
}

export function summarizeRngSeedTraceReport(report: RngSeedTraceReport): string {
  const visible = `${report.visibleDeterministicCallCount}/${report.deterministicCallCount}`;
  const replay = report.legalReplayIdentical ? 'legal replay identical' : 'legal replay not yet proven';
  const illegal = report.illegalBlocked ? 'illegal RNG blocked' : 'illegal RNG block not yet proven';
  return `#${report.tick} RNG trace ${visible} deterministic calls visible; ${illegal}; ${replay}`;
}

export function validateRngSeedTraceCall(call: RngSeedTraceCall): string[] {
  const missing: string[] = [];
  if (!Number.isFinite(call.tick) || call.tick < 0) missing.push('tick');
  if (!call.systemId) missing.push('system');
  if (!call.seed) missing.push('seed');
  if (call.streamPosition === null || !Number.isFinite(call.streamPosition) || call.streamPosition < 0) missing.push('stream_position');
  if (!call.result) missing.push('result');
  return missing;
}

export function runtimeDebugRngCallsToSeedTrace(message: RuntimeDebugTraceMessage): RngSeedTraceCall[] {
  return (message.rng_calls ?? []).map((call, index) => normalizeRuntimeDebugRngCall(message.tick, call, index));
}

function buildReport(
  tick: number,
  calls: readonly RngSeedTraceCall[],
  violations: readonly RngSeedTraceViolationRecord[],
  replay: readonly RngSeedReplayEvidence[],
  retainedCallCount: number,
): RngSeedTraceReport {
  const deterministicCalls = calls.filter((call) => call.deterministic);
  const missingFields = deterministicCalls.flatMap((call) =>
    validateRngSeedTraceCall(call).map((field) => `#${call.tick}:${call.systemId || '<missing-system>'}:${field}`),
  );
  const visibleDeterministicCallCount = deterministicCalls.filter((call) => validateRngSeedTraceCall(call).length === 0).length;
  const legalReplayIdentical = replay.some((item) => item.identical && item.firstHash.length > 0 && item.firstHash === item.secondHash);
  const illegalBlocked = violations.some((violation) => violation.blocked);
  return {
    tick: finiteTick(tick),
    calls,
    violations,
    replay,
    deterministicCallCount: deterministicCalls.length,
    visibleDeterministicCallCount,
    retainedCallCount,
    illegalBlocked,
    legalReplayIdentical,
    missingFields,
    complete: deterministicCalls.length > 0 && missingFields.length === 0 && illegalBlocked && legalReplayIdentical,
  };
}

function normalizeRuntimeRngTraceCall(tick: number, call: RuntimeRngTraceCall, index: number): RngSeedTraceCall {
  return {
    tick: finiteTick(call.tick ?? tick),
    systemId: call.system_id ?? '',
    seed: fieldValue(call.seed),
    streamId: call.stream_id ?? call.system_id ?? '',
    streamPosition: finitePosition(call.stream_position),
    result: fieldValue(call.result),
    callIndex: finiteIndex(call.call_index ?? index),
    deterministic: call.deterministic ?? true,
    source: 'runtime_rng_trace',
  };
}

function normalizeRuntimeDebugRngCall(tick: number, call: RuntimeDebugRngCallTrace, index: number): RngSeedTraceCall {
  return {
    tick: finiteTick(call.tick ?? tick),
    systemId: call.system_id ?? '',
    seed: fieldValue(call.seed),
    streamId: call.stream_id ?? call.system_id ?? '',
    streamPosition: finitePosition(call.stream_position),
    result: fieldValue(call.result ?? call.value),
    callIndex: finiteIndex(call.call_index ?? index),
    deterministic: call.deterministic ?? true,
    source: 'runtime_debug_trace.rng_calls',
  };
}

function normalizeRuntimeRngTraceViolation(tick: number, violation: RuntimeRngTraceViolation): RngSeedTraceViolationRecord {
  return {
    tick: finiteTick(violation.tick ?? tick),
    systemId: violation.system_id ?? '',
    reason: violation.reason ?? 'illegal deterministic RNG access',
    source: violation.source ?? 'runtime_rng_trace.violations',
    blocked: violation.blocked !== false,
  };
}

function normalizeRuntimeReplayEvidence(replay: RuntimeRngTraceMessage['replay']): RngSeedReplayEvidence {
  return {
    replayId: replay?.replay_id ?? 'runtime_rng_replay',
    firstHash: replay?.first_hash ?? '',
    secondHash: replay?.second_hash ?? '',
    identical: replay?.identical === true,
  };
}

function finiteTick(value: number): number {
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
}

function finiteIndex(value: number): number {
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
}

function finitePosition(value: number | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
}

function fieldValue(value: string | number | boolean | null | undefined): string {
  if (value === undefined || value === null) return '';
  return String(value);
}

function trim<T>(items: T[], limit: number): void {
  if (items.length > limit) items.splice(0, items.length - limit);
}
