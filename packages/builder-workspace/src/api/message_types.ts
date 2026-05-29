/**
 * message_types.ts — WebSocket message type contracts
 *
 * Every WebSocket message between the browser and builder_server.py
 * is typed here. The server (Python) mirrors these types in
 * ws_message_router.py. When adding a new message type, add it here
 * AND in the Python router.
 *
 * Protocol: JSON over WebSocket. Every message has a `type` field.
 * Message envelope: { type: string, payload: object, session_id: string }
 *
 * Direction notation:
 *   C→S = browser (client) sends to server
 *   S→C = server sends to browser
 */

import type { CGS, CGSSnapshot } from '../types/cgs';
import type { PILResult, PassUpdate, SessionTelemetry, AssistanceMode } from '../types/pil';

// ── Client → Server ───────────────────────────────────────────────────────────

/** C→S: Submit a prompt for PIL processing */
export interface PilProcessMessage {
  type:       'pil_process';
  prompt:     string;
  cgs_hash:   string;
  mode:       AssistanceMode;
  session_id: string;
}

/** C→S: Submit an answer to a clarification question */
export interface PilAnswerMessage {
  type:               'pil_answer';
  clarification_id:   string;
  answer:             string;
  session_id:         string;
}

/** C→S: Confirm applying the pending mutation transaction */
export interface PilApplyMessage {
  type:       'pil_apply';
  session_id: string;
}

/** C→S: Discard the pending mutation transaction */
export interface PilDiscardMessage {
  type:       'pil_discard';
  session_id: string;
}

/** C→S: Request the current CGS (on reconnect) */
export interface CgsRequestMessage {
  type:         'cgs_request';
  session_id:   string;
  project_path: string;
}

/** C→S: Switch assistance mode */
export interface ModeChangeMessage {
  type:       'mode_change';
  mode:       AssistanceMode;
  session_id: string;
}

/** C→S: Link a file path to an asset placeholder */
export interface AssetLinkMessage {
  type:           'asset_link';
  placeholder_id: string;
  asset_path:     string;
  actor_id:       string;
  component_name: string;
  session_id:     string;
}

/** C→S: Rollback CGS to a specific hash */
export interface CgsRollbackMessage {
  type:          'cgs_rollback';
  target_hash:   string;
  session_id:    string;
}

/** C→S: Ping keepalive */
export interface PingMessage {
  type:       'ping';
  session_id: string;
}

/** C→S: Switch the active LLM provider/model for the session */
export interface ModelChangeMessage {
  type:       'model_change';
  provider:   string;   // "auto" | "ollama" | "anthropic"
  model:      string;   // model name e.g. "auto", "llama3.2", "llama3.1"
  session_id: string;
}

export type ClientMessage =
  | PilProcessMessage
  | PilAnswerMessage
  | PilApplyMessage
  | PilDiscardMessage
  | CgsRequestMessage
  | ModeChangeMessage
  | ModelChangeMessage
  | AssetLinkMessage
  | CgsRollbackMessage
  | PingMessage;

// ── Server → Client ───────────────────────────────────────────────────────────

/** S→C: Session initialized — first message after connection */
export interface SessionInitMessage {
  type:       'session_init';
  session_id: string;
  cgs:        CGS;
  hash:       string;
  snapshots:  CGSSnapshot[];
  version:    string;
}

/**
 * S→C: Streamed per-pass update during PIL processing.
 * Sent before (status='running') and after (status='done'/'failed') each pass.
 */
export interface PilPassUpdateMessage {
  type:   'pil_pass_update';
  update: PassUpdate;
}

/** S→C: PIL processing completed — full result */
export interface PilResultMessage {
  type:   'pil_result';
  result: PILResult;
}

/**
 * S→C: CGS was updated (mutation committed or rollback applied).
 * Includes new snapshot for version timeline.
 */
export interface CgsUpdateMessage {
  type:     'cgs_update';
  cgs:      CGS;
  hash:     string;
  snapshot: CGSSnapshot;
  /** Node IDs to highlight in the graph for 2s */
  affected_node_ids: string[];
}

/**
 * S→C: Clarification answer accepted — next question or null if complete.
 * null means PIL will be re-invoked with resolved parameters.
 */
export interface PilAnswerAckMessage {
  type:          'pil_answer_ack';
  accepted:      boolean;
  error?:        string;
  next_question: import('../types/pil').ClarificationQuestion | null;
  complete:      boolean;
}

/**
 * S→C: Engine runtime tick data.
 * Phase 14: not sent (engine not connected).
 * Phase 15+: sent every N ticks from the engine adapter.
 */
export interface EngineTickMessage {
  type:           'engine_tick';
  tick:           number;
  fps:            number;
  world_hash:     string;
  ms_per_tick:    number;
  entity_count:   number;
  system_timings: Record<string, number>;   // system_id → ms
  is_deterministic: boolean;
}

/** S→C: Engine adapter connected */
export interface EngineConnectedMessage {
  type:           'engine_connected';
  adapter_type:   'unity' | 'godot' | 'unreal' | 'webgl';
  engine_version: string;
}

/** S→C: Engine adapter disconnected */
export interface EngineDisconnectedMessage {
  type:   'engine_disconnected';
  reason: string;
}

/** S→C: Session telemetry snapshot (sent after each PIL call) */
export interface TelemetryUpdateMessage {
  type:      'telemetry_update';
  telemetry: SessionTelemetry;
}

/** S→C: Error from server (not a PIL error — a server-level error) */
export interface ServerErrorMessage {
  type:    'server_error';
  code:    string;
  message: string;
}

/** S→C: Pong response to ping */
export interface PongMessage {
  type:       'pong';
  server_time: number;  // Unix epoch ms
}

export type ServerMessage =
  | SessionInitMessage
  | PilPassUpdateMessage
  | PilResultMessage
  | CgsUpdateMessage
  | PilAnswerAckMessage
  | EngineTickMessage
  | EngineConnectedMessage
  | EngineDisconnectedMessage
  | TelemetryUpdateMessage
  | ServerErrorMessage
  | PongMessage;

// ── Type guards ───────────────────────────────────────────────────────────────

export const isSessionInit        = (m: ServerMessage): m is SessionInitMessage        => m.type === 'session_init';
export const isPilPassUpdate      = (m: ServerMessage): m is PilPassUpdateMessage      => m.type === 'pil_pass_update';
export const isPilResult          = (m: ServerMessage): m is PilResultMessage          => m.type === 'pil_result';
export const isCgsUpdate          = (m: ServerMessage): m is CgsUpdateMessage          => m.type === 'cgs_update';
export const isPilAnswerAck       = (m: ServerMessage): m is PilAnswerAckMessage       => m.type === 'pil_answer_ack';
export const isEngineTick         = (m: ServerMessage): m is EngineTickMessage         => m.type === 'engine_tick';
export const isEngineConnected    = (m: ServerMessage): m is EngineConnectedMessage    => m.type === 'engine_connected';
export const isEngineDisconnected = (m: ServerMessage): m is EngineDisconnectedMessage => m.type === 'engine_disconnected';
export const isTelemetryUpdate    = (m: ServerMessage): m is TelemetryUpdateMessage    => m.type === 'telemetry_update';
export const isServerError        = (m: ServerMessage): m is ServerErrorMessage        => m.type === 'server_error';

// ── Message factory helpers ───────────────────────────────────────────────────

export function makePilProcess(
  prompt: string, hash: string, mode: AssistanceMode, sessionId: string,
): PilProcessMessage {
  return { type: 'pil_process', prompt, cgs_hash: hash, mode, session_id: sessionId };
}

export function makePilAnswer(
  clarificationId: string, answer: string, sessionId: string,
): PilAnswerMessage {
  return { type: 'pil_answer', clarification_id: clarificationId, answer, session_id: sessionId };
}

export function makePilApply(sessionId: string): PilApplyMessage {
  return { type: 'pil_apply', session_id: sessionId };
}

export function makePilDiscard(sessionId: string): PilDiscardMessage {
  return { type: 'pil_discard', session_id: sessionId };
}

export function makeAssetLink(
  placeholderId: string, assetPath: string,
  actorId: string, componentName: string, sessionId: string,
): AssetLinkMessage {
  return {
    type: 'asset_link', placeholder_id: placeholderId,
    asset_path: assetPath, actor_id: actorId,
    component_name: componentName, session_id: sessionId,
  };
}
