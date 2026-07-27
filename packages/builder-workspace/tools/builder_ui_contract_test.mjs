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

assertClientMessageUnion();
assertBuilderClientProtocol();
assertPromptBlocksUnreadyProviders();
assertProviderUxStateCopy();
assertProviderTestSavesBeforeTesting();
assertTopBarReadinessWiring();

console.log('builder UI contract test PASSED');
