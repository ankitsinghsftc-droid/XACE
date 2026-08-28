import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();

function read(path) {
  return readFileSync(join(root, path), 'utf8');
}

function assertContains(file, needle, label) {
  const text = read(file);
  if (!text.includes(needle)) {
    throw new Error(`${label}: expected ${file} to contain ${JSON.stringify(needle)}`);
  }
}

function assertOrder(file, first, second, label) {
  const text = read(file);
  const firstIndex = text.indexOf(first);
  const secondIndex = text.indexOf(second);
  if (firstIndex < 0 || secondIndex < 0 || firstIndex >= secondIndex) {
    throw new Error(`${label}: expected ${JSON.stringify(first)} before ${JSON.stringify(second)} in ${file}`);
  }
}

function assertClientMessageUnion() {
  const file = 'src/api/message_types.ts';
  for (const type of [
    "type: 'pil_process'",
    "type: 'pil_answer'",
    "type: 'pil_apply'",
    "type: 'pil_discard'",
    "type: 'cgs_request'",
    "type: 'mode_change'",
    "type: 'model_change'",
    "type: 'runtime_control'",
    "type: 'engine_edit'",
    "type: 'engine_edit_commit'",
    "type: 'terminal_command'",
    "type: 'ping'",
  ]) {
    assertContains(file, type, 'client message contract');
  }
  assertContains(file, 'export const BUILDER_PROTOCOL_VERSION = 1;', 'protocol version contract');
  assertContains(file, 'export type ClientMessage =', 'client message union');
}

function assertBuilderClientProtocol() {
  const file = 'src/api/builder_client.ts';
  assertContains(file, 'protocol_version: BUILDER_PROTOCOL_VERSION', 'protocol enrichment');
  assertContains(file, "if (message.type === 'ping')", 'ping queue exclusion');
  assertContains(file, "type: 'cgs_request'", 'initial CGS request');
  assertContains(file, 'isRuntimeControlAck(message)', 'runtime control dispatch');
  assertContains(file, 'isEngineEditAck(message)', 'engine edit dispatch');
  assertContains(file, 'updateProviderStatus(partial', 'provider readiness publisher');
}

function assertPromptBlocksUnreadyProviders() {
  const file = 'src/canvas/prompt_input.ts';
  assertContains(file, '!this._providerStatus.ready', 'provider readiness guard');
  assertContains(file, "new CustomEvent('xace:open-model-settings')", 'provider settings action');
  assertOrder(file, '!this._providerStatus.ready', 'client.send(makePilProcess(', 'provider guard before prompt send');
}

function assertProviderUxStateCopy() {
  const promptFile = 'src/canvas/prompt_input.ts';
  const selectorFile = 'src/canvas/model_selector.ts';
  const clientFile = 'src/api/builder_client.ts';
  for (const state of [
    'no_key',
    'invalid_key',
    'stale_health_proof',
    'quota_failure',
    'rate_limit',
    'provider_outage',
  ]) {
    assertContains(promptFile, `${state}:`, `provider UX copy for ${state}`);
  }
  assertContains(promptFile, 'status.ux_state?.state', 'provider UX state prompt fallback');
  assertContains(selectorFile, 'readiness?.ux_state', 'provider UX state readiness publish');
  assertContains(selectorFile, "this._appendStatusRow(block, 'State'", 'provider UX state status row');
  assertContains(clientFile, 'export interface ProviderUxState', 'provider UX state client type');
}

function assertProviderTestSavesBeforeTesting() {
  const file = 'src/canvas/model_selector.ts';
  assertOrder(
    file,
    "'/api/provider-settings', this._currentPayload()",
    "'/api/provider-settings/test'",
    'provider settings saved before test call',
  );
  assertContains(file, 'this._client.updateProviderStatus({', 'provider readiness broadcast');
}

function assertTopBarReadinessWiring() {
  const file = 'src/layout/main_layout.ts';
  assertContains(file, 'xb-ready-chip', 'readiness chip UI');
  assertContains(file, 'onProviderStatus', 'provider readiness subscription');
  assertContains(file, 'onRuntimeStatus', 'runtime readiness subscription');
  assertContains(file, 'Project', 'project readiness label');
  assertContains(file, 'Provider', 'provider readiness label');
  assertContains(file, 'Runtime', 'runtime readiness label');
}

function assertMultiplayerLifecycleSmokeWiring() {
  const dashboardFile = 'src/project/project_dashboard.ts';
  const serverFile = 'server/builder_server.py';
  assertContains(dashboardFile, '/api/project/demo/multiplayer/smoke', 'multiplayer smoke endpoint call');
  assertContains(dashboardFile, 'lobby/session lifecycle', 'multiplayer lifecycle UI summary');
  assertContains(dashboardFile, 'interface MultiplayerSmokeStep', 'multiplayer smoke step contract');
  assertContains(serverFile, '"id": "session_lifecycle"', 'multiplayer lifecycle checklist step');
  assertContains(serverFile, '"label": "Lobby/session lifecycle"', 'multiplayer lifecycle checklist label');
  assertContains(serverFile, '"x10_039"', 'multiplayer lifecycle cargo test filter');
  assertContains(dashboardFile, 'compatibility gates', 'multiplayer compatibility UI summary');
  assertContains(serverFile, '"id": "session_compatibility"', 'multiplayer compatibility checklist step');
  assertContains(serverFile, '"label": "Session compatibility gate"', 'multiplayer compatibility checklist label');
  assertContains(serverFile, '"x10_040"', 'multiplayer compatibility cargo test filter');
  assertContains(dashboardFile, 'malicious-input limits', 'multiplayer malicious-input UI summary');
  assertContains(serverFile, '"id": "malicious_input_limits"', 'multiplayer malicious-input checklist step');
  assertContains(serverFile, '"label": "Malicious input limits"', 'multiplayer malicious-input checklist label');
  assertContains(serverFile, '"x10_041"', 'multiplayer malicious-input cargo test filter');
  assertContains(dashboardFile, '/api/project/demo/multiplayer/diagnostics', 'multiplayer diagnostics endpoint call');
  assertContains(dashboardFile, 'Open Network Diagnostics', 'multiplayer diagnostics button');
  assertContains(dashboardFile, 'interface MultiplayerDiagnosticsResponse', 'multiplayer diagnostics response contract');
  assertContains(dashboardFile, 'Multiplayer diagnostics panel', 'multiplayer diagnostics panel title');
  assertContains(dashboardFile, 'peers, ticks, input buffers, latency, rollback count, resync status, packet loss, hash comparisons, and authority owner', 'multiplayer diagnostics required fields copy');
  assertContains(dashboardFile, 'Chaos diagnostics report', 'multiplayer diagnostics chaos report row');
  assertContains(serverFile, '"xace.multiplayer_diagnostics_snapshot.v1"', 'multiplayer diagnostics schema');
  assertContains(serverFile, '"hash_comparisons"', 'multiplayer diagnostics hash comparisons payload');
  assertContains(serverFile, '"authority"', 'multiplayer diagnostics authority payload');
  assertContains(serverFile, '"chaos_report"', 'multiplayer diagnostics chaos report payload');
}

function assertTickDebuggerContract() {
  const file = 'src/preview/tick_debugger.ts';
  for (const label of [
    'Tick debugger',
    'Timeline',
    'Time travel',
    'Conditional breakpoints',
    'Causality graph',
    'RNG seed trace',
    'Snapshot list',
    'State diff',
    'Mutation history',
    'Event trace',
    'Hash mismatches',
    'Source-free trace',
    'Reverse step',
    'Forward step',
    'Live tick',
    'Matching hash',
  ]) {
    assertContains(file, label, `tick debugger visible label ${label}`);
  }
  for (const action of ['data-action="pause"', 'data-action="step"', 'data-action="snapshot"']) {
    assertContains(file, action, `tick debugger control ${action}`);
  }
  for (const nav of ['data-nav="reverse_step"', 'data-nav="forward_step"', 'data-nav="live"']) {
    assertContains(file, nav, `tick debugger time-travel control ${nav}`);
  }
  assertContains(file, 'data-breakpoint-id', 'tick debugger breakpoint toggle control');
  for (const marker of [
    'MIN_TIME_TRAVEL_TICKS = 1000',
    'runtime_control_ack',
    'message.snapshot',
    'snapshotFromEngineTick',
    'snapshotFromRuntimeControlAck',
    'buildStateDiff',
    'renderTimeTravelNavigation',
    'navigateTimeline',
    'timelineRecords',
    'currentTimelineRecord',
    'nearestTimelineRecord',
    'recordSnapshotMutations',
    'recordGameEvents',
    'observedHashesByTick',
    'pushHashMismatch',
    'hash_log',
    'runtime_debug_trace',
    'runtime_causality_trace',
    'runtime_rng_trace',
    'ConditionalBreakpointEngine',
    'CausalityGraphEngine',
    'RngSeedTraceEngine',
    'snapshotBreakpointCandidates',
    'eventBreakpointCandidates',
    'mutationBreakpointCandidate',
    'hashMismatchBreakpointCandidate',
    'runtimeDebugTraceBreakpointCandidates',
    'applyBreakpointHits',
    'renderCausalityGraph',
    'summarizeCausalityReport',
    'renderRngSeedTrace',
    'summarizeRngSeedTraceReport',
  ]) {
    assertContains(file, marker, `tick debugger protocol wiring ${marker}`);
  }
  const breakpointFile = 'src/preview/conditional_breakpoints.ts';
  for (const label of ['Entity state', 'Component value', 'Event type', 'Mutation type', 'System ID', 'RNG call', 'Network desync']) {
    assertContains(breakpointFile, label, `tick debugger breakpoint visible label ${label}`);
  }
  for (const kind of ['entity_state', 'component_value', 'event_type', 'mutation_type', 'system_id', 'rng_call', 'hash_mismatch', 'network_desync']) {
    assertContains(breakpointFile, kind, `tick debugger breakpoint kind ${kind}`);
  }
  assertContains('src/api/message_types.ts', 'RuntimeDebugTraceMessage', 'runtime debug trace protocol message');
  const causalityFile = 'src/preview/causality_graph.ts';
  for (const marker of ['CAUSALITY_NODE_KIND_ORDER', 'REQUIRED_STATE_CHANGE_CAUSE_KINDS', 'CausalityGraphEngine', 'reportStateChangeCause']) {
    assertContains(causalityFile, marker, `tick debugger causality graph marker ${marker}`);
  }
  for (const kind of ['prompt', 'mutation', 'system', 'event', 'rng_call', 'feedback', 'network_packet', 'state_change']) {
    assertContains(causalityFile, kind, `tick debugger causality node kind ${kind}`);
  }
  assertContains('src/api/message_types.ts', 'RuntimeCausalityTraceMessage', 'runtime causality trace protocol message');
  const rngSeedTraceFile = 'src/preview/rng_seed_trace.ts';
  for (const marker of ['RngSeedTraceEngine', 'RuntimeRngTraceMessage', 'runtimeDebugRngCallsToSeedTrace', 'validateRngSeedTraceCall', 'summarizeRngSeedTraceReport']) {
    assertContains(rngSeedTraceFile, marker, `tick debugger RNG seed trace marker ${marker}`);
  }
  for (const marker of ['RuntimeRngTraceMessage', 'RuntimeRngTraceCall', 'RuntimeRngTraceViolation', 'RuntimeRngReplayTrace', 'runtime_rng_trace', 'isRuntimeRngTrace']) {
    assertContains('src/api/message_types.ts', marker, `runtime RNG seed trace protocol message ${marker}`);
  }
}

function assertSemanticBindingUiContract() {
  const panelFile = 'src/panels/semantic_binding_panel.ts';
  const catalogFile = 'src/panels/semantic_binding_catalog.ts';
  const canvasFile = 'src/canvas/builder_canvas.ts';
  const layoutFile = 'src/layout/main_layout.ts';
  const messageFile = 'src/api/message_types.ts';
  const storeFile = 'src/state/cgs_store.ts';
  const serverFile = 'server/ws_message_router.py';
  const statusFile = 'src/panels/semantic_binding_status.ts';

  for (const marker of [
    'Semantic bindings',
    'Map semantic events',
    'Target engines',
    'Add semantic binding',
    'buildBindingRecord',
    'xace_engine_targets',
    'resource_path',
    'asset_path',
    'makeSemanticBindingUpdate',
    'Pre-runtime/handoff status',
    'xb-sbp-status-summary',
  ]) {
    assertContains(panelFile, marker, `semantic binding panel marker ${marker}`);
  }
  for (const marker of ['SemanticBindingStatusRecord', 'evaluateSemanticBindingStatuses', 'semanticBindingStatusSummary', 'statusBlocksLaunch']) {
    assertContains(statusFile, marker, `semantic binding status marker ${marker}`);
  }
  for (const status of ['resolved', 'unresolved', 'unsupported', 'missing', 'fallback']) {
    assertContains(statusFile, status, `semantic binding engine status ${status}`);
    assertContains(panelFile, status, `semantic binding panel status ${status}`);
  }
  for (const kind of ['Animation', 'Audio', 'Vfx']) {
    assertContains(catalogFile, kind, `semantic binding playback kind ${kind}`);
  }
  for (const engine of ['godot', 'unity', 'unreal']) {
    assertContains(catalogFile, engine, `semantic binding engine target ${engine}`);
  }
  for (const eventName of ['interaction.accepted', 'combat.hit_confirmed', 'audio.playback_requested', 'vfx.playback_requested']) {
    assertContains(catalogFile, eventName, `semantic binding event ${eventName}`);
  }
  assertContains(canvasFile, 'SemanticBindingPanel', 'semantic binding panel mounted in Builder canvas');
  assertContains(layoutFile, 'Bindings', 'semantic binding workflow shortcut');
  assertContains(layoutFile, 'xace:open-semantic-bindings', 'semantic binding shortcut event');
  assertContains(messageFile, "type: 'semantic_binding_update'", 'semantic binding client message type');
  assertContains(messageFile, 'makeSemanticBindingUpdate', 'semantic binding message constructor');
  assertContains(storeFile, 'semanticBindings', 'semantic binding CGS store getter');
  assertContains(storeFile, 'collectCgsAssets', 'semantic binding asset source includes top-level assets');
  assertContains(serverFile, 'semantic_binding_update', 'semantic binding server route');
  assertContains(serverFile, '_sanitize_semantic_bindings', 'semantic binding server validation');
}

assertClientMessageUnion();
assertBuilderClientProtocol();
assertPromptBlocksUnreadyProviders();
assertProviderUxStateCopy();
assertProviderTestSavesBeforeTesting();
assertTopBarReadinessWiring();
assertMultiplayerLifecycleSmokeWiring();
assertTickDebuggerContract();
assertSemanticBindingUiContract();

console.log('builder UI contract test PASSED');
