/**
 * Deterministic tick debugger for the live builder preview.
 *
 * The debugger is intentionally protocol-driven: it renders runtime control
 * ACKs, engine tick snapshots, and status hash logs without asking a builder
 * to inspect generated source.
 */

import type { BuilderClient, RuntimeStatus } from '../api/builder_client';
import type {
  EngineTickMessage,
  RuntimeBridgeStatus,
  RuntimeControlAction,
  RuntimeEntityState,
  RuntimeGameEvent,
  RuntimeTickSnapshot,
  ServerMessage,
} from '../api/message_types';
import { makeRuntimeControl } from '../api/message_types';
import type { CGSStore } from '../state/cgs_store';
import type { UIStore } from '../state/ui_store';
import type { BreakpointHit, ConditionalBreakpoint } from './conditional_breakpoints';
import {
  ConditionalBreakpointEngine,
  eventBreakpointCandidates,
  hashMismatchBreakpointCandidate,
  mutationBreakpointCandidate,
  runtimeDebugTraceBreakpointCandidates,
  snapshotBreakpointCandidates,
} from './conditional_breakpoints';
import type { CausalityReport } from './causality_graph';
import { CausalityGraphEngine, summarizeCausalityReport } from './causality_graph';
import { RngSeedTraceEngine, summarizeRngSeedTraceReport } from './rng_seed_trace';

const MIN_TIME_TRAVEL_TICKS = 1000;
const MAX_HISTORY = MIN_TIME_TRAVEL_TICKS;
const MAX_EVENTS = 24;
const MAX_SNAPSHOTS = 96;
const MAX_MUTATIONS = 160;
const MAX_EVENT_TRACE = 96;
const MAX_HASH_MISMATCHES = 32;
const MAX_DIFF_ROWS = 28;

const STYLES = `
.xb-dbg { flex: 1; overflow-y: auto; padding: 8px 9px; display: flex; flex-direction: column; gap: 7px; min-height: 0; }
.xb-dbg-tick { font-family: var(--font-mono); font-size: 16px; color: var(--cyan); letter-spacing: .04em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-dbg-ctrls { display: flex; gap: 4px; flex-wrap: wrap; }
.xb-dbg-btn { font-size: 9.5px; padding: 3px 8px; border: 1px solid var(--bd); background: transparent; color: var(--txt2); border-radius: 3px; cursor: pointer; font-family: inherit; transition: all 100ms; }
.xb-dbg-btn:hover { border-color: var(--bdh); color: var(--txt); }
.xb-dbg-btn.active { border-color: rgba(0,212,255,.35); color: var(--cyan); background: var(--cynd); }
.xb-dbg-scrubber { height: 8px; background: rgba(255,255,255,.03); border: 1px solid var(--bd); border-radius: 3px; overflow: hidden; position: relative; }
.xb-dbg-scrub-fill { height: 100%; background: linear-gradient(90deg, rgba(0,212,255,.18), rgba(168,85,247,.18)); border-radius: 3px; }
.xb-dbg-sect { font-size: 8.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--txt2); }
.xb-dbg-box { font-family: var(--font-mono); font-size: 9px; color: var(--txt2); background: rgba(0,0,0,.2); border: 1px solid rgba(255,255,255,.05); padding: 6px; border-radius: 4px; line-height: 1.7; max-height: 132px; overflow-y: auto; overflow-x: hidden; }
.xb-dbg-hash { color: var(--grn); word-break: break-all; }
.xb-dbg-good { color: var(--grn); }
.xb-dbg-warn { color: var(--amb); }
.xb-dbg-bad { color: var(--red); }
.xb-dbg-link { display: block; width: 100%; text-align: left; border: 0; background: transparent; color: inherit; font: inherit; padding: 1px 0; cursor: pointer; }
.xb-dbg-link:hover, .xb-dbg-link.active { color: var(--cyan); }
`;

interface DebuggerDeps { cgsStore: CGSStore; uiStore: UIStore; client: BuilderClient; }

interface TickRecord { readonly tick: number; readonly worldHash: string; readonly msPerTick: number; readonly deterministic: boolean; readonly entityCount: number; readonly eventCount: number; readonly spawnedCount: number; readonly destroyedCount: number; }
type SnapshotSource = 'engine_tick' | 'runtime_control_snapshot';
interface SnapshotRecord { readonly key: string; readonly tick: number; readonly timestampMs: number; readonly source: SnapshotSource; readonly worldHash: string; readonly entities: readonly RuntimeEntityState[]; readonly spawnedIds: readonly number[]; readonly destroyedIds: readonly number[]; readonly events: readonly RuntimeGameEvent[]; }
interface TimeTravelRecord { readonly tick: number; readonly worldHash: string; readonly source: 'engine_tick' | 'runtime_status.hash_log' | 'snapshot'; readonly snapshotKey?: string; }
interface DebugEvent { readonly tick: number; readonly level: 'info' | 'warn' | 'error'; readonly text: string; }
interface EventTraceRecord { readonly tick: number; readonly eventType: string; readonly entityId: number; readonly data: string; }
interface MutationRecord { readonly tick: number; readonly kind: 'spawn' | 'destroy' | 'component' | 'event'; readonly entityId: string; readonly component: string; readonly detail: string; }
interface StateDiffRow { readonly kind: 'entity_added' | 'entity_removed' | 'component_added' | 'component_removed' | 'component_changed' | 'metadata_changed'; readonly entityId: number; readonly component: string; readonly before: string; readonly after: string; }
interface HashMismatchRecord { readonly key: string; readonly tick: number; readonly expectedHash: string; readonly actualHash: string; readonly source: string; }
type TimeTravelAction = 'reverse_step' | 'forward_step' | 'live';

export class TickDebugger {
  private readonly deps: DebuggerDeps;
  private readonly history: TickRecord[] = [];
  private readonly events: DebugEvent[] = [];
  private readonly snapshots: SnapshotRecord[] = [];
  private readonly mutationHistory: MutationRecord[] = [];
  private readonly eventTrace: EventTraceRecord[] = [];
  private readonly hashMismatches: HashMismatchRecord[] = [];
  private readonly breakpointEngine = new ConditionalBreakpointEngine();
  private readonly causalityGraph = new CausalityGraphEngine();
  private readonly rngSeedTrace = new RngSeedTraceEngine();
  private readonly observedHashesByTick = new Map<number, string>();
  private readonly seenMutationKeys = new Set<string>();
  private readonly seenEventKeys = new Set<string>();
  private readonly unsubs: Array<() => void> = [];
  private root: HTMLElement | null = null;
  private tick = 0;
  private requestedMode: 'play' | 'pause' = 'play';
  private lastHash = '';
  private runtimeStatus: RuntimeStatus | null = null;
  private selectedSnapshotKey = '';
  private selectedTimelineTick: number | null = null;
  private followLiveTimeline = true;
  private breakpointPaused = false;

  constructor(deps: DebuggerDeps) { this.deps = deps; injectStyles(); }

  mount(container: HTMLElement): void {
    this.root = document.createElement('div');
    this.root.className = 'xb-dbg';
    container.appendChild(this.root);
    this.unsubs.push(this.deps.cgsStore.select((state) => state.hash, (hash) => { this.lastHash = hash || this.lastHash; this.render(); }));
    this.unsubs.push(this.deps.client.onEngineTick((tick, _fps, worldHash, msPerTick, message) => {
      this.acceptTick({ tick, worldHash, msPerTick, deterministic: message.is_deterministic, entityCount: message.entity_count, eventCount: message.events?.length ?? 0, spawnedCount: message.spawned_ids?.length ?? 0, destroyedCount: message.destroyed_ids?.length ?? 0 }, message);
    }));
    this.unsubs.push(this.deps.client.onRawMessage((message) => this.acceptServerMessage(message)));
    this.unsubs.push(this.deps.client.onRuntimeStatus((status) => { this.runtimeStatus = status; if (status.controlTick > this.tick) this.tick = status.controlTick; this.recordStatusHashLog(status); this.render(); }));
    this.render();
  }

  unmount(): void { this.unsubs.splice(0).forEach((unsub) => unsub()); this.root?.remove(); this.root = null; }

  private acceptTick(record: TickRecord, message: EngineTickMessage): void {
    this.tick = record.tick;
    this.lastHash = record.worldHash || this.lastHash;
    this.history.push(record);
    trim(this.history, MAX_HISTORY);
    if (this.followLiveTimeline) this.selectedTimelineTick = null;
    this.rememberHash(record.tick, record.worldHash, 'engine_tick');
    if (!record.deterministic) { this.pushEvent('error', `determinism breach at tick ${record.tick}`); this.pushHashMismatch(record.tick, 'deterministic=true', 'deterministic=false', 'engine_tick.is_deterministic'); }
    const snapshot = snapshotFromEngineTick(message);
    if (snapshot) this.recordSnapshot(snapshot);
    else if (message.events?.length) this.recordGameEvents(record.tick, message.events);
    this.recordStatusHashLog(this.deps.client.runtimeStatus);
    this.render();
  }

  private acceptServerMessage(message: ServerMessage): void {
    if (message.type === 'runtime_control_ack') {
      if (message.status) { this.runtimeStatus = statusFromBridge(message.status, this.deps.client.runtimeStatus); this.recordStatusHashLog(this.runtimeStatus); }
      if (message.snapshot) this.recordSnapshot(snapshotFromRuntimeControlAck(message.snapshot, this.runtimeStatus));
      this.pushEvent(message.accepted ? 'info' : 'warn', `${message.action} ${message.accepted ? 'accepted' : message.reason ?? 'rejected'}`);
      this.render();
      return;
    }
    if (message.type === 'runtime_debug_trace') { this.rngSeedTrace.ingestRuntimeDebugTrace(message); this.applyBreakpointHits(this.breakpointEngine.evaluateCandidates(runtimeDebugTraceBreakpointCandidates(message))); this.render(); return; }
    if (message.type === 'runtime_causality_trace') { const report = this.causalityGraph.ingestTrace(message); this.pushEvent(report.complete ? 'info' : 'warn', `causality ${report.traceId} ${report.complete ? 'complete' : 'incomplete'}`); this.render(); return; }
    if (message.type === 'runtime_rng_trace') { const report = this.rngSeedTrace.ingestRuntimeRngTrace(message); this.pushEvent(report.complete ? 'info' : 'warn', `rng seed trace ${report.visibleDeterministicCallCount}/${report.deterministicCallCount} visible at tick ${report.tick}`); this.render(); return; }
    if (message.type === 'server_error') { this.pushEvent('error', `${message.code}: ${message.message}`); this.render(); return; }
    if (message.type === 'engine_disconnected') { this.pushEvent('warn', `engine disconnected: ${message.reason}`); this.render(); }
  }

  private render(): void {
    if (!this.root) return;
    const latest = this.history[this.history.length - 1] ?? null;
    const status = this.runtimeStatus ?? this.deps.client.runtimeStatus;
    const hash = latest?.worldHash || this.lastHash || status.latestWorldHash || '0'.repeat(64);
    const pct = this.history.length <= 1 ? 0 : (this.history.length / MAX_HISTORY) * 100;
    const deterministic = latest?.deterministic ?? true;
    const feedbackIssues = status.lastEngineFeedbackInvalid + status.lastEngineFeedbackErrors;
    const selectedSnapshot = this.currentSnapshot();
    const timeline = this.timelineRecords(status);
    const selectedTimeline = this.currentTimelineRecord(timeline);

    this.root.innerHTML = `
      <div class="xb-dbg-sect">Tick debugger</div>
      <div class="xb-dbg-tick">${this.tick.toLocaleString()}</div>
      <div class="xb-dbg-ctrls">
        <button class="xb-dbg-btn ${this.requestedMode === 'play' ? 'active' : ''}" data-action="play">Play</button>
        <button class="xb-dbg-btn ${this.requestedMode === 'pause' ? 'active' : ''}" data-action="pause">Pause</button>
        <button class="xb-dbg-btn" data-action="step">Step</button>
        <button class="xb-dbg-btn" data-action="snapshot">Snapshot</button>
        <button class="xb-dbg-btn" data-action="reset">Reset</button>
        <button class="xb-dbg-btn" data-action="reload_cgs">Reload CGS</button>
      </div>
      <div class="xb-dbg-scrubber" aria-label="Timeline"><div class="xb-dbg-scrub-fill" style="width:${Math.min(100, pct).toFixed(2)}%"></div></div>
      <div class="xb-dbg-sect">Source-free trace</div>
      <div class="xb-dbg-box">runtime protocol payloads only: tick snapshots, control ACKs, hash_log records, runtime_debug_trace diagnostics, runtime_causality_trace graphs, and runtime_rng_trace seed/result records</div>
      <div class="xb-dbg-sect">Determinism</div>
      <div class="xb-dbg-box ${deterministic ? '' : 'xb-dbg-bad'}">${deterministic ? 'locked' : 'breach detected'}</div>
      <div class="xb-dbg-sect">World hash</div>
      <div class="xb-dbg-box xb-dbg-hash">${escapeHtml(hash)}</div>
      <div class="xb-dbg-sect">Runtime bridge</div>
      <div class="xb-dbg-box">state: <span class="${status.paused ? 'xb-dbg-warn' : ''}">${status.paused ? 'paused' : 'running'}</span><br>alive: ${status.aliveCount.toLocaleString()} | phases: ${status.phaseCount.toLocaleString()} | systems: ${status.registeredSystems.toLocaleString()}<br>pending input: ${status.pendingEngineInputs.toLocaleString()} | pending feedback: ${status.pendingEngineFeedback.toLocaleString()}<br>feedback handled: ${status.lastEngineFeedbackProcessed.toLocaleString()} | issues: <span class="${feedbackIssues > 0 ? 'xb-dbg-bad' : ''}">${feedbackIssues.toLocaleString()}</span><br>hash log: ${status.hashLog.length.toLocaleString()} | snapshots: ${this.snapshots.length.toLocaleString()} | selected: ${selectedSnapshot ? `#${selectedSnapshot.tick}` : 'none'}</div>
      <div class="xb-dbg-sect">Timeline</div><div class="xb-dbg-box">${this.renderTimeline(status, selectedTimeline)}</div>
      <div class="xb-dbg-sect">Time travel</div><div class="xb-dbg-box">${this.renderTimeTravelNavigation(timeline, selectedTimeline)}</div>
      <div class="xb-dbg-sect">Conditional breakpoints</div><div class="xb-dbg-box">${this.renderConditionalBreakpoints()}</div>
      <div class="xb-dbg-sect">Causality graph</div><div class="xb-dbg-box">${this.renderCausalityGraph()}</div>
      <div class="xb-dbg-sect">RNG seed trace</div><div class="xb-dbg-box">${this.renderRngSeedTrace()}</div>
      <div class="xb-dbg-sect">Snapshot list</div><div class="xb-dbg-box">${this.renderSnapshotList()}</div>
      <div class="xb-dbg-sect">State diff</div><div class="xb-dbg-box">${this.renderStateDiff()}</div>
      <div class="xb-dbg-sect">Mutation history</div><div class="xb-dbg-box">${this.renderMutationHistory()}</div>
      <div class="xb-dbg-sect">Event trace</div><div class="xb-dbg-box">${this.renderEventTrace()}</div>
      <div class="xb-dbg-sect">Hash mismatches</div><div class="xb-dbg-box">${this.renderHashMismatches()}</div>
      <div class="xb-dbg-sect">Control events</div><div class="xb-dbg-box">${this.renderEvents()}</div>`;

    this.root.querySelectorAll<HTMLButtonElement>('[data-action]').forEach((button) => { button.addEventListener('click', () => this.sendControl(button.dataset['action'] as RuntimeControlAction)); });
    this.root.querySelectorAll<HTMLButtonElement>('[data-nav]').forEach((button) => { button.addEventListener('click', () => this.navigateTimeline(button.dataset['nav'] as TimeTravelAction)); });
    this.root.querySelectorAll<HTMLButtonElement>('[data-breakpoint-id]').forEach((button) => { button.addEventListener('click', () => { const id = button.dataset['breakpointId']; if (id) this.toggleBreakpoint(id); }); });
    this.root.querySelectorAll<HTMLButtonElement>('[data-snapshot-key]').forEach((button) => { button.addEventListener('click', () => { const key = button.dataset['snapshotKey']; if (key) { this.selectedSnapshotKey = key; const snapshot = this.snapshots.find((item) => item.key === key); if (snapshot) { this.followLiveTimeline = false; this.selectedTimelineTick = snapshot.tick; } this.render(); } }); });
  }

  private renderTimeline(status: RuntimeStatus, selected: TimeTravelRecord | null): string {
    if (this.history.length === 0 && status.hashLog.length === 0) return 'No timeline ticks received.';
    const statusRows = status.hashLog.slice(-12).map((item): TickRecord => ({ tick: item.tick, worldHash: item.world_hash, msPerTick: 0, deterministic: true, entityCount: 0, eventCount: 0, spawnedCount: 0, destroyedCount: 0 }));
    const rows = this.history.length > 0 ? this.history.slice(-12) : statusRows;
    return rows.map((item) => { const mismatch = this.hashMismatches.some((record) => record.tick === item.tick); const selectedMarker = selected?.tick === item.tick ? 'selected ' : ''; const cls = !item.deterministic || mismatch ? ' class="xb-dbg-bad"' : selected?.tick === item.tick ? ' class="xb-dbg-good"' : ''; const timing = item.msPerTick > 0 ? `${item.msPerTick.toFixed(2)}ms` : 'status'; const counts = item.entityCount > 0 || item.eventCount > 0 ? ` e:${item.entityCount} ev:${item.eventCount} +${item.spawnedCount}/-${item.destroyedCount}` : ''; return `<span${cls}>${selectedMarker}#${item.tick} ${timing} ${mismatch ? 'mismatch' : item.deterministic ? 'ok' : 'breach'} ${escapeHtml(shortHash(item.worldHash))}${counts}</span>`; }).join('<br>');
  }

  private renderTimeTravelNavigation(timeline: readonly TimeTravelRecord[], selected: TimeTravelRecord | null): string {
    if (timeline.length === 0 || !selected) return 'No time-travel hash timeline available yet.';
    const index = timeline.findIndex((record) => record.tick === selected.tick);
    const snapshot = this.snapshotForTick(selected.tick);
    const hashMatchesSnapshot = !snapshot?.worldHash || snapshot.worldHash === selected.worldHash;
    const retainedSpan = timeline.length >= MIN_TIME_TRAVEL_TICKS ? `<span class="xb-dbg-good">${MIN_TIME_TRAVEL_TICKS.toLocaleString()} tick window retained</span>` : `<span class="xb-dbg-warn">${timeline.length.toLocaleString()}/${MIN_TIME_TRAVEL_TICKS.toLocaleString()} tick window retained</span>`;
    const matchText = hashMatchesSnapshot ? 'Matching hash' : 'Hash mismatch against selected snapshot';
    const matchClass = hashMatchesSnapshot ? 'xb-dbg-good' : 'xb-dbg-bad';
    return `<div class="xb-dbg-ctrls"><button class="xb-dbg-btn" data-nav="reverse_step">Reverse step</button><button class="xb-dbg-btn" data-nav="forward_step">Forward step</button><button class="xb-dbg-btn ${this.followLiveTimeline ? 'active' : ''}" data-nav="live">Live tick</button></div>selected #${selected.tick} (${index + 1}/${timeline.length}) ${escapeHtml(selected.source)}<br>hash: <span class="xb-dbg-hash">${escapeHtml(selected.worldHash)}</span><br><span class="${matchClass}">${matchText}</span> | ${retainedSpan}`;
  }

  private renderSnapshotList(): string {
    if (this.snapshots.length === 0) return 'No runtime snapshots yet. Click Snapshot or wait for engine tick payloads.';
    const current = this.currentSnapshot();
    return this.snapshots.slice(-10).reverse().map((snapshot) => { const active = snapshot.key === current?.key ? ' active' : ''; const mismatch = this.hashMismatches.some((record) => record.tick === snapshot.tick); const cls = mismatch ? 'xb-dbg-bad' : 'xb-dbg-good'; return `<button class="xb-dbg-link${active}" data-snapshot-key="${escapeAttribute(snapshot.key)}">#${snapshot.tick} ${escapeHtml(snapshot.source)} <span class="${cls}">${escapeHtml(shortHash(snapshot.worldHash))}</span> entities:${snapshot.entities.length} events:${snapshot.events.length} +${snapshot.spawnedIds.length}/-${snapshot.destroyedIds.length}</button>`; }).join('');
  }

  private renderStateDiff(): string {
    const current = this.currentSnapshot();
    if (!current) return 'No snapshots available for state diff.';
    const index = this.snapshots.findIndex((snapshot) => snapshot.key === current.key);
    const previous = index > 0 ? this.snapshots[index - 1] ?? null : null;
    if (!previous) return `Baseline snapshot #${current.tick}: ${current.entities.length.toLocaleString()} entities, ${current.events.length.toLocaleString()} events.`;
    const rows = buildStateDiff(previous, current);
    if (rows.length === 0) return `No state diff between #${previous.tick} and #${current.tick}.`;
    return rows.slice(0, MAX_DIFF_ROWS).map((row) => { const component = row.component ? ` ${escapeHtml(row.component)}` : ''; return `<span>#${previous.tick}->#${current.tick} ${escapeHtml(row.kind)} entity:${row.entityId}${component} ${escapeHtml(row.before)} => ${escapeHtml(row.after)}</span>`; }).join('<br>');
  }

  private renderMutationHistory(): string { if (this.mutationHistory.length === 0) return 'No mutations derived from snapshots yet.'; return this.mutationHistory.slice(-14).map((mutation) => { const cls = mutation.kind === 'destroy' ? 'xb-dbg-warn' : mutation.kind === 'component' ? 'xb-dbg-good' : ''; const component = mutation.component ? ` ${escapeHtml(mutation.component)}` : ''; return `<span class="${cls}">#${mutation.tick} ${escapeHtml(mutation.kind)} entity:${escapeHtml(mutation.entityId)}${component} ${escapeHtml(mutation.detail)}</span>`; }).join('<br>'); }
  private renderEventTrace(): string { if (this.eventTrace.length === 0) return 'No runtime event trace yet.'; return this.eventTrace.slice(-14).map((event) => `<span>#${event.tick} ${escapeHtml(event.eventType)} entity:${event.entityId} ${escapeHtml(event.data)}</span>`).join('<br>'); }
  private renderHashMismatches(): string { if (this.hashMismatches.length === 0) return '<span class="xb-dbg-good">No hash mismatches detected.</span>'; return this.hashMismatches.slice(-10).map((record) => `<span class="xb-dbg-bad">#${record.tick} ${escapeHtml(record.source)} expected:${escapeHtml(shortHash(record.expectedHash))} actual:${escapeHtml(shortHash(record.actualHash))}</span>`).join('<br>'); }
  private renderConditionalBreakpoints(): string {
    const breakpoints = this.breakpointEngine.breakpoints();
    const hits = this.breakpointEngine.hits();
    const armed = breakpoints.filter((breakpoint) => breakpoint.enabled).length;
    const header = `${this.breakpointPaused ? '<span class="xb-dbg-warn">paused on breakpoint</span><br>' : ''}${armed}/${breakpoints.length} armed | hits: ${hits.length.toLocaleString()}`;
    const rows = breakpoints.map((breakpoint) => { const cls = breakpoint.enabled ? 'active' : ''; const state = breakpoint.enabled ? 'armed' : 'off'; return `<button class="xb-dbg-btn ${cls}" data-breakpoint-id="${escapeAttribute(breakpoint.id)}">${escapeHtml(state)}</button> ${escapeHtml(breakpoint.label)} <span class="xb-dbg-good">${escapeHtml(formatBreakpointCondition(breakpoint))}</span><br><span>${escapeHtml(breakpoint.description)}</span>`; }).join('<br>');
    const hitRows = hits.length === 0 ? 'No breakpoint hits yet.' : hits.slice(-8).map((hit) => `<span class="xb-dbg-warn">#${hit.tick} ${escapeHtml(hit.label)} ${escapeHtml(hit.detail)} [${escapeHtml(hit.source)}]</span>`).join('<br>');
    return `${header}<br>${rows}<br><br>${hitRows}`;
  }
  private renderCausalityGraph(): string {
    const report = this.causalityGraph.latestReport();
    if (!report) return 'No causality graph yet. Waiting for runtime_causality_trace with prompt, mutation, system, event, RNG, feedback, network, and state-change nodes.';
    const coverage = renderCausalityCoverage(report);
    const diagnostics = report.diagnostics.length === 0 ? '<span class="xb-dbg-good">graph valid</span>' : report.diagnostics.map((item) => `<span class="xb-dbg-bad">${escapeHtml(item)}</span>`).join('<br>');
    const chain = report.causeChain.length === 0 ? 'No ancestor chain for selected state change.' : report.causeChain.map((node) => `<span class="${causalityNodeClass(node.kind)}">#${node.tick} ${escapeHtml(node.kind)} ${escapeHtml(node.label)} ${escapeHtml(node.detail)}</span>`).join('<br>');
    return `${escapeHtml(summarizeCausalityReport(report))}<br>${coverage}<br>edges: ${report.causeEdges.length.toLocaleString()} | ${diagnostics}<br>${chain}`;
  }
  private renderRngSeedTrace(): string {
    const report = this.rngSeedTrace.latestReport();
    const calls = this.rngSeedTrace.calls().slice(-10);
    if (!report && calls.length === 0) return 'No RNG seed trace yet. Waiting for runtime_rng_trace with tick, system, seed, stream position, result, replay, and violation evidence.';
    const complete = report?.complete ? '<span class="xb-dbg-good">complete: deterministic RNG calls visible and replay/illegal-RNG evidence retained</span>' : '<span class="xb-dbg-warn">incomplete: waiting for full seed/result, replay, or illegal-RNG block evidence</span>';
    const summary = report ? escapeHtml(summarizeRngSeedTraceReport(report)) : 'RNG seed trace retained calls only.';
    const missing = report && report.missingFields.length > 0 ? `<br><span class="xb-dbg-bad">missing: ${escapeHtml(report.missingFields.slice(0, 8).join(', '))}</span>` : '';
    const rows = calls.length === 0 ? 'No retained RNG calls yet.' : calls.map((call) => { const visible = call.deterministic && call.seed && call.streamPosition !== null && call.result; const cls = !call.deterministic ? 'xb-dbg-bad' : visible ? 'xb-dbg-good' : 'xb-dbg-warn'; const position = call.streamPosition === null ? '<missing>' : call.streamPosition.toLocaleString(); return `<span class="${cls}">#${call.tick} ${escapeHtml(call.systemId || '<missing-system>')} seed:${escapeHtml(call.seed || '<missing>')} stream:${escapeHtml(call.streamId || '<default>')} pos:${escapeHtml(position)} result:${escapeHtml(call.result || '<missing>')} [${escapeHtml(call.source)}]</span>`; }).join('<br>');
    const violations = this.rngSeedTrace.violations().slice(-4);
    const violationRows = violations.length === 0 ? '' : `<br><br>violations:<br>${violations.map((violation) => `<span class="${violation.blocked ? 'xb-dbg-good' : 'xb-dbg-bad'}">#${violation.tick} ${escapeHtml(violation.systemId || '<unknown-system>')} ${violation.blocked ? 'blocked' : 'unblocked'} ${escapeHtml(violation.reason)} [${escapeHtml(violation.source)}]</span>`).join('<br>')}`;
    const replay = this.rngSeedTrace.replayEvidence().slice(-2);
    const replayRows = replay.length === 0 ? '' : `<br><br>replay:<br>${replay.map((item) => `<span class="${item.identical && item.firstHash === item.secondHash ? 'xb-dbg-good' : 'xb-dbg-bad'}">${escapeHtml(item.replayId)} identical:${String(item.identical)} ${escapeHtml(shortHash(item.firstHash))} / ${escapeHtml(shortHash(item.secondHash))}</span>`).join('<br>')}`;
    return `${summary}<br>${complete}${missing}<br>retained calls: ${(report?.retainedCallCount ?? calls.length).toLocaleString()}<br>${rows}${violationRows}${replayRows}`;
  }
  private renderEvents(): string { if (this.events.length === 0) return 'No control events yet.'; return this.events.slice(-8).map((event) => { const cls = event.level === 'error' ? 'xb-dbg-bad' : event.level === 'warn' ? 'xb-dbg-warn' : ''; return `<span class="${cls}">#${event.tick} ${escapeHtml(event.text)}</span>`; }).join('<br>'); }

  private sendControl(action: RuntimeControlAction): void { if (action === 'play' || action === 'pause') this.requestedMode = action; if (action === 'play' || action === 'step') this.breakpointPaused = false; this.deps.client.send(makeRuntimeControl(action, this.deps.client.sessionId, this.tick)); this.pushEvent('info', `sent ${action}`); this.render(); }

  private toggleBreakpoint(id: string): void { const current = this.breakpointEngine.breakpoints().find((breakpoint) => breakpoint.id === id); const updated = this.breakpointEngine.setBreakpointEnabled(id, !current?.enabled); if (!updated) return; this.pushEvent('info', `${updated.enabled ? 'armed' : 'disabled'} breakpoint ${updated.label}`); this.render(); }

  private applyBreakpointHits(hits: readonly BreakpointHit[]): void { if (hits.length === 0) return; const latest = hits[hits.length - 1]; if (!latest) return; this.breakpointPaused = true; this.requestedMode = 'pause'; this.tick = latest.tick; hits.forEach((hit) => this.pushEvent('warn', `breakpoint ${hit.label} hit at tick ${hit.tick}`)); this.deps.client.send(makeRuntimeControl('pause', this.deps.client.sessionId, latest.tick)); }

  private navigateTimeline(action: TimeTravelAction): void {
    const timeline = this.timelineRecords(this.runtimeStatus ?? this.deps.client.runtimeStatus);
    if (timeline.length === 0) { this.pushEvent('warn', `time-travel ${action} unavailable: no hash timeline`); this.render(); return; }
    if (action === 'live') { this.followLiveTimeline = true; this.selectedTimelineTick = null; this.selectSnapshotForTick(timeline[timeline.length - 1]?.tick); this.pushEvent('info', 'time-travel returned to live tick'); this.render(); return; }
    const current = this.currentTimelineRecord(timeline);
    const currentIndex = current ? timeline.findIndex((record) => record.tick === current.tick) : timeline.length - 1;
    const nextIndex = action === 'reverse_step' ? Math.max(0, currentIndex - 1) : Math.min(timeline.length - 1, currentIndex + 1);
    const target = timeline[nextIndex];
    if (!target) return;
    this.followLiveTimeline = false;
    this.selectedTimelineTick = target.tick;
    this.selectSnapshotForTick(target.tick);
    this.pushEvent('info', `${action} to tick ${target.tick}`);
    this.render();
  }

  private recordSnapshot(snapshot: SnapshotRecord): void { const previous = this.snapshots[this.snapshots.length - 1] ?? null; this.snapshots.push(snapshot); trim(this.snapshots, MAX_SNAPSHOTS); if (this.followLiveTimeline || this.selectedTimelineTick === snapshot.tick) this.selectedSnapshotKey = snapshot.key; this.rememberHash(snapshot.tick, snapshot.worldHash, snapshot.source); this.recordSnapshotMutations(previous, snapshot); this.recordGameEvents(snapshot.tick, snapshot.events); this.applyBreakpointHits(this.breakpointEngine.evaluateCandidates(snapshotBreakpointCandidates(snapshot, previous))); }
  private recordSnapshotMutations(previous: SnapshotRecord | null, current: SnapshotRecord): void {
    current.spawnedIds.forEach((id) => this.pushMutation({ tick: current.tick, kind: 'spawn', entityId: String(id), component: '', detail: 'spawned_id from runtime snapshot' }));
    current.destroyedIds.forEach((id) => this.pushMutation({ tick: current.tick, kind: 'destroy', entityId: String(id), component: '', detail: 'destroyed_id from runtime snapshot' }));
    if (!previous) { current.entities.slice(0, MAX_DIFF_ROWS).forEach((entity) => this.pushMutation({ tick: current.tick, kind: 'spawn', entityId: String(entity.id), component: '', detail: 'baseline entity visible in first snapshot' })); return; }
    buildStateDiff(previous, current).forEach((row) => { if (row.kind === 'entity_added') { this.pushMutation({ tick: current.tick, kind: 'spawn', entityId: String(row.entityId), component: '', detail: row.after }); return; } if (row.kind === 'entity_removed') { this.pushMutation({ tick: current.tick, kind: 'destroy', entityId: String(row.entityId), component: '', detail: row.before }); return; } this.pushMutation({ tick: current.tick, kind: 'component', entityId: String(row.entityId), component: row.component, detail: `${row.kind}: ${truncate(row.before)} -> ${truncate(row.after)}` }); });
  }
  private recordGameEvents(tick: number, events: readonly RuntimeGameEvent[]): void { this.applyBreakpointHits(this.breakpointEngine.evaluateCandidates(eventBreakpointCandidates(tick, events))); events.forEach((event, index) => { const data = stableJson(event.data ?? {}); const key = `${tick}:${index}:${event.event_type}:${event.entity_id}:${data}`; if (this.seenEventKeys.has(key)) return; this.seenEventKeys.add(key); this.eventTrace.push({ tick, eventType: event.event_type, entityId: event.entity_id, data: truncate(data) }); trim(this.eventTrace, MAX_EVENT_TRACE); this.pushMutation({ tick, kind: 'event', entityId: String(event.entity_id), component: '', detail: `${event.event_type} ${truncate(data)}` }); }); }
  private recordStatusHashLog(status: RuntimeStatus): void { status.hashLog.forEach((record) => this.rememberHash(record.tick, record.world_hash, 'runtime_status.hash_log')); }
  private rememberHash(tick: number, worldHash: string, source: string): void { if (!worldHash) return; const expected = this.observedHashesByTick.get(tick); if (expected && expected !== worldHash) { this.pushHashMismatch(tick, expected, worldHash, source); return; } this.observedHashesByTick.set(tick, worldHash); }
  private pushHashMismatch(tick: number, expectedHash: string, actualHash: string, source: string): void { const key = `${tick}:${expectedHash}:${actualHash}:${source}`; if (this.hashMismatches.some((record) => record.key === key)) return; const record = { key, tick, expectedHash, actualHash, source }; this.hashMismatches.push(record); trim(this.hashMismatches, MAX_HASH_MISMATCHES); this.applyBreakpointHits(this.breakpointEngine.evaluateCandidate(hashMismatchBreakpointCandidate(record))); }
  private pushMutation(mutation: MutationRecord): void { const key = `${mutation.tick}:${mutation.kind}:${mutation.entityId}:${mutation.component}:${mutation.detail}`; if (this.seenMutationKeys.has(key)) return; this.seenMutationKeys.add(key); this.mutationHistory.push(mutation); trim(this.mutationHistory, MAX_MUTATIONS); this.applyBreakpointHits(this.breakpointEngine.evaluateCandidate(mutationBreakpointCandidate(mutation))); }
  private pushEvent(level: DebugEvent['level'], text: string): void { this.events.push({ tick: this.tick, level, text }); trim(this.events, MAX_EVENTS); }
  private timelineRecords(status: RuntimeStatus): TimeTravelRecord[] { const byTick = new Map<number, TimeTravelRecord>(); status.hashLog.forEach((record) => byTick.set(record.tick, { tick: record.tick, worldHash: record.world_hash, source: 'runtime_status.hash_log' })); this.history.forEach((record) => byTick.set(record.tick, { tick: record.tick, worldHash: record.worldHash, source: 'engine_tick' })); this.snapshots.forEach((snapshot) => { if (snapshot.worldHash) byTick.set(snapshot.tick, { tick: snapshot.tick, worldHash: snapshot.worldHash, source: 'snapshot', snapshotKey: snapshot.key }); }); return Array.from(byTick.values()).sort((left, right) => left.tick - right.tick).slice(-MIN_TIME_TRAVEL_TICKS); }
  private currentTimelineRecord(timeline: readonly TimeTravelRecord[]): TimeTravelRecord | null { if (timeline.length === 0) return null; if (this.followLiveTimeline || this.selectedTimelineTick === null) return timeline[timeline.length - 1] ?? null; return timeline.find((record) => record.tick === this.selectedTimelineTick) ?? nearestTimelineRecord(timeline, this.selectedTimelineTick) ?? timeline[timeline.length - 1] ?? null; }
  private currentSnapshot(): SnapshotRecord | null { if (this.snapshots.length === 0) return null; const selected = this.snapshots.find((snapshot) => snapshot.key === this.selectedSnapshotKey); if (selected) return selected; if (this.selectedTimelineTick !== null) return this.snapshotForTick(this.selectedTimelineTick); return this.snapshots[this.snapshots.length - 1] ?? null; }
  private snapshotForTick(tick: number): SnapshotRecord | null { return this.snapshots.find((snapshot) => snapshot.tick === tick) ?? null; }
  private selectSnapshotForTick(tick: number | undefined): void { if (tick === undefined) return; const snapshot = this.snapshotForTick(tick); if (snapshot) this.selectedSnapshotKey = snapshot.key; }
}

function snapshotFromEngineTick(message: EngineTickMessage): SnapshotRecord | null { const hasSnapshotPayload = Boolean(message.entities || message.spawned_ids || message.destroyed_ids || message.events); if (!hasSnapshotPayload) return null; return makeSnapshotRecord({ tick: message.tick, timestampMs: Math.round(message.tick * Math.max(0, message.ms_per_tick)), source: 'engine_tick', worldHash: message.world_hash, entities: message.entities ?? [], spawnedIds: message.spawned_ids ?? [], destroyedIds: message.destroyed_ids ?? [], events: message.events ?? [] }); }
function snapshotFromRuntimeControlAck(snapshot: RuntimeTickSnapshot, status: RuntimeStatus | null): SnapshotRecord { const statusHash = status?.hashLog.find((record) => record.tick === snapshot.tick)?.world_hash; return makeSnapshotRecord({ tick: snapshot.tick, timestampMs: snapshot.timestamp_ms, source: 'runtime_control_snapshot', worldHash: statusHash || status?.latestWorldHash || '', entities: snapshot.entities, spawnedIds: snapshot.spawned_ids ?? [], destroyedIds: snapshot.destroyed_ids ?? [], events: snapshot.events ?? [] }); }
function makeSnapshotRecord(input: Omit<SnapshotRecord, 'key'>): SnapshotRecord { const key = [input.source, input.tick, input.timestampMs, input.worldHash, input.entities.length, input.spawnedIds.length, input.destroyedIds.length, input.events.length].join(':'); return { ...input, key }; }
function buildStateDiff(previous: SnapshotRecord, current: SnapshotRecord): StateDiffRow[] { const previousEntities = entityMap(previous.entities); const currentEntities = entityMap(current.entities); const ids = Array.from(new Set([...previousEntities.keys(), ...currentEntities.keys()])).sort((a, b) => a - b); const rows: StateDiffRow[] = []; ids.forEach((id) => { const before = previousEntities.get(id); const after = currentEntities.get(id); if (!before && after) { rows.push({ kind: 'entity_added', entityId: id, component: '', before: '<missing>', after: entitySummary(after) }); return; } if (before && !after) { rows.push({ kind: 'entity_removed', entityId: id, component: '', before: entitySummary(before), after: '<missing>' }); return; } if (!before || !after) return; if ((before.actor_id ?? '') !== (after.actor_id ?? '')) rows.push({ kind: 'metadata_changed', entityId: id, component: 'actor_id', before: before.actor_id ?? '', after: after.actor_id ?? '' }); Array.from(new Set([...Object.keys(before.components), ...Object.keys(after.components)])).sort().forEach((component) => { const oldValue = before.components[component]; const newValue = after.components[component]; if (oldValue === newValue) return; rows.push({ kind: oldValue === undefined ? 'component_added' : newValue === undefined ? 'component_removed' : 'component_changed', entityId: id, component, before: truncate(oldValue ?? '<missing>'), after: truncate(newValue ?? '<missing>') }); }); }); return rows; }
function entityMap(entities: readonly RuntimeEntityState[]): Map<number, RuntimeEntityState> { const map = new Map<number, RuntimeEntityState>(); entities.forEach((entity) => map.set(entity.id, entity)); return map; }
function entitySummary(entity: RuntimeEntityState): string { return `actor:${entity.actor_id ?? ''} components:${Object.keys(entity.components).sort().join(',')}`; }
function statusFromBridge(status: RuntimeBridgeStatus, fallback: RuntimeStatus): RuntimeStatus { return { ...fallback, connected: true, adapterType: typeof status.adapter_type === 'string' ? status.adapter_type : fallback.adapterType, controlTick: status.tick, aliveCount: status.alive_count, pendingEngineInputs: status.pending_engine_inputs, pendingEngineFeedback: status.pending_engine_feedback ?? fallback.pendingEngineFeedback, engineSnapshotsSent: status.engine_snapshots_sent ?? fallback.engineSnapshotsSent, engineInputPacketsReceived: status.engine_input_packets_received ?? fallback.engineInputPacketsReceived, engineFeedbackPayloadsReceived: status.engine_feedback_payloads_received ?? fallback.engineFeedbackPayloadsReceived, engineFeedbackMessagesReceived: status.engine_feedback_messages_received ?? fallback.engineFeedbackMessagesReceived, engineMalformedMessages: status.engine_malformed_messages ?? fallback.engineMalformedMessages, engineDroppedInputs: status.engine_dropped_inputs ?? fallback.engineDroppedInputs, engineAdapterSequence: typeof status.engine_adapter_sequence === 'number' ? status.engine_adapter_sequence : fallback.engineAdapterSequence, registeredSystems: status.registered_systems, phaseCount: status.phase_count, paused: Boolean(status.paused), stepBudget: status.step_budget ?? fallback.stepBudget, lastEngineFeedbackProcessed: status.last_engine_feedback_processed ?? fallback.lastEngineFeedbackProcessed, lastEngineFeedbackInvalid: status.last_engine_feedback_invalid ?? fallback.lastEngineFeedbackInvalid, lastEngineFeedbackErrors: status.last_engine_feedback_errors ?? fallback.lastEngineFeedbackErrors, latestWorldHash: status.latest_world_hash ?? fallback.latestWorldHash, hashLog: status.hash_log ?? fallback.hashLog }; }
function formatBreakpointCondition(breakpoint: ConditionalBreakpoint): string { const field = breakpoint.field ? `${breakpoint.field} ` : ''; const value = breakpoint.value ? ` ${breakpoint.value}` : ''; return `${field}${breakpoint.operator}${value}`.trim(); }
function renderCausalityCoverage(report: CausalityReport): string { return Object.entries(report.coverage).map(([kind, ok]) => `<span class="${ok ? 'xb-dbg-good' : 'xb-dbg-bad'}">${escapeHtml(kind)}:${ok ? 'yes' : 'missing'}</span>`).join(' | '); }
function causalityNodeClass(kind: string): string { if (kind === 'state_change') return 'xb-dbg-warn'; if (kind === 'event' || kind === 'rng_call' || kind === 'system') return 'xb-dbg-good'; return ''; }
function nearestTimelineRecord(timeline: readonly TimeTravelRecord[], tick: number): TimeTravelRecord | null { let nearest: TimeTravelRecord | null = null; for (const record of timeline) { if (record.tick <= tick) { nearest = record; continue; } return nearest ?? record; } return nearest; }
function stableJson(value: unknown): string { try { return JSON.stringify(sortJson(value)); } catch { return String(value); } }
function sortJson(value: unknown): unknown { if (Array.isArray(value)) return value.map((item) => sortJson(item)); if (value && typeof value === 'object') { const sorted: Record<string, unknown> = {}; Object.keys(value as Record<string, unknown>).sort().forEach((key) => { sorted[key] = sortJson((value as Record<string, unknown>)[key]); }); return sorted; } return value; }
function shortHash(value: string): string { if (!value) return '<none>'; return value.length > 18 ? value.slice(0, 18) : value; }
function truncate(value: string): string { return value.length > 72 ? `${value.slice(0, 69)}...` : value; }
function trim<T>(items: T[], limit: number): void { if (items.length > limit) items.splice(0, items.length - limit); }
function injectStyles(): void { if (document.getElementById('xb-dbg-styles')) return; const style = document.createElement('style'); style.id = 'xb-dbg-styles'; style.textContent = STYLES; document.head.appendChild(style); }
function escapeHtml(value: string): string { const div = document.createElement('div'); div.textContent = value; return div.innerHTML; }
function escapeAttribute(value: string): string { return escapeHtml(value).replace(/"/g, '&quot;'); }
