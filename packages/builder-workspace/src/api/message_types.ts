/**
 * Typed WebSocket protocol for the XACE builder workspace.
 *
 * The server mirrors these message names in ws_message_router.py. Browser
 * components should use these contracts instead of ad-hoc JSON objects so
 * live runtime, engine preview, and PIL state stay in one protocol surface.
 */

import type { CGS, CGSSnapshot } from '../types/cgs';
import type {
  AssistanceMode,
  ClarificationQuestion,
  PILResult,
  PassUpdate,
  PromptApplyFeedback,
  PromptPreviewApproval,
  SessionTelemetry,
} from '../types/pil';

export const BUILDER_PROTOCOL_VERSION = 1;

export type AdapterType = 'unity' | 'godot' | 'unreal' | 'webgl' | 'headless';
export type RuntimeControlAction =
  | 'play'
  | 'pause'
  | 'step'
  | 'reset'
  | 'reload_cgs'
  | 'status'
  | 'snapshot';
export type EngineEditKind =
  | 'select_entity'
  | 'set_component_field'
  | 'focus_entity'
  | 'spawn_preview'
  | 'delete_preview';

export interface MessageEnvelope {
  readonly type: string;
  readonly session_id?: string;
  readonly request_id?: string;
  readonly protocol_version?: number;
}

export interface PilProcessMessage extends MessageEnvelope {
  readonly type: 'pil_process';
  readonly prompt: string;
  readonly cgs_hash: string;
  readonly mode: AssistanceMode;
  readonly session_id: string;
}

export interface PilAnswerMessage extends MessageEnvelope {
  readonly type: 'pil_answer';
  readonly clarification_id: string;
  readonly answer: string;
  readonly session_id: string;
}

export interface PilApplyMessage extends MessageEnvelope {
  readonly type: 'pil_apply';
  readonly session_id: string;
  readonly approval?: PromptPreviewApproval;
  readonly test_mode_override?: boolean;
  readonly test_mode_reason?: string;
  readonly validation_requirements?: Record<string, boolean>;
}

export interface PilDiscardMessage extends MessageEnvelope {
  readonly type: 'pil_discard';
  readonly session_id: string;
}

export interface CgsRequestMessage extends MessageEnvelope {
  readonly type: 'cgs_request';
  readonly session_id: string;
  readonly project_path: string;
}

export interface ModeChangeMessage extends MessageEnvelope {
  readonly type: 'mode_change';
  readonly mode: AssistanceMode;
  readonly session_id: string;
}

export interface ModelChangeMessage extends MessageEnvelope {
  readonly type: 'model_change';
  readonly provider: string;
  readonly model: string;
  readonly session_id: string;
}

export interface AssetLinkMessage extends MessageEnvelope {
  readonly type: 'asset_link';
  readonly placeholder_id: string;
  readonly asset_path: string;
  readonly actor_id: string;
  readonly component_name: string;
  readonly session_id: string;
}

export interface CgsRollbackMessage extends MessageEnvelope {
  readonly type: 'cgs_rollback';
  readonly target_hash: string;
  readonly session_id: string;
}

export interface RuntimeControlMessage extends MessageEnvelope {
  readonly type: 'runtime_control';
  readonly action: RuntimeControlAction;
  readonly tick?: number;
  readonly session_id: string;
}

export interface EngineEditMessage extends MessageEnvelope {
  readonly type: 'engine_edit';
  readonly kind: EngineEditKind;
  readonly entity_id?: string;
  readonly mode_id?: string;
  readonly actor_id?: string;
  readonly component_type_id?: number;
  readonly component_name?: string;
  readonly field_path?: string;
  readonly value?: unknown;
  readonly source?: string;
  readonly session_id: string;
}

export interface EngineEditCommitMessage extends MessageEnvelope {
  readonly type: 'engine_edit_commit';
  readonly mode_id: string;
  readonly actor_id: string;
  readonly component_type_id: number;
  readonly component_name?: string;
  readonly field_path: string;
  readonly value: unknown;
  readonly audit_ts?: number;
  readonly session_id: string;
}

export interface TerminalCommandMessage extends MessageEnvelope {
  readonly type: 'terminal_command';
  readonly command: string;
  readonly session_id: string;
}

export interface PingMessage extends MessageEnvelope {
  readonly type: 'ping';
  readonly session_id: string;
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
  | RuntimeControlMessage
  | EngineEditMessage
  | EngineEditCommitMessage
  | TerminalCommandMessage
  | PingMessage;

export interface SessionInitMessage extends MessageEnvelope {
  readonly type: 'session_init';
  readonly session_id: string;
  readonly cgs: CGS;
  readonly hash: string;
  readonly snapshots: CGSSnapshot[];
  readonly version: string;
}

export interface PilPassUpdateMessage extends MessageEnvelope {
  readonly type: 'pil_pass_update';
  readonly update: PassUpdate;
}

export interface PilResultMessage extends MessageEnvelope {
  readonly type: 'pil_result';
  readonly result: PILResult;
}

export interface CgsUpdateMessage extends MessageEnvelope {
  readonly type: 'cgs_update';
  readonly cgs: CGS;
  readonly hash: string;
  readonly snapshot: CGSSnapshot;
  readonly affected_node_ids: string[];
  readonly sgc_validation?: Record<string, unknown> | null;
  readonly approval?: Record<string, unknown>;
  readonly apply_validation?: Record<string, unknown>;
  readonly apply_feedback?: PromptApplyFeedback;
  readonly transaction_id?: string;
  readonly version_ids?: Record<string, unknown>;
  readonly execution_plan_available?: boolean;
  readonly warnings?: unknown[];
}

export interface PilAnswerAckMessage extends MessageEnvelope {
  readonly type: 'pil_answer_ack';
  readonly accepted: boolean;
  readonly error?: string;
  readonly next_question: ClarificationQuestion | null;
  readonly complete: boolean;
  readonly clarification_result?: Record<string, unknown>;
  readonly requires_reprompt?: boolean;
  readonly resolved_prompt?: string;
}

export interface EngineTickMessage extends MessageEnvelope {
  readonly type: 'engine_tick';
  readonly tick: number;
  readonly fps: number;
  readonly world_hash: string;
  readonly ms_per_tick: number;
  readonly entity_count: number;
  readonly system_timings: Record<string, number>;
  readonly is_deterministic: boolean;
  readonly adapter_type?: AdapterType;
  readonly entities?: RuntimeEntityState[];
  readonly spawned_ids?: number[];
  readonly destroyed_ids?: number[];
  readonly events?: RuntimeGameEvent[];
}

export interface EngineConnectedMessage extends MessageEnvelope {
  readonly type: 'engine_connected';
  readonly adapter_type: AdapterType;
  readonly engine_version: string;
}

export interface EngineDisconnectedMessage extends MessageEnvelope {
  readonly type: 'engine_disconnected';
  readonly reason: string;
}

export interface RuntimeBridgeStatus {
  readonly tick: number;
  readonly alive_count: number;
  readonly engine_connected: boolean;
  readonly adapter_type?: AdapterType | string;
  readonly engine_connections?: RuntimeBridgeEngineConnection[];
  readonly engine_snapshots_sent?: number;
  readonly engine_input_packets_received?: number;
  readonly engine_feedback_payloads_received?: number;
  readonly engine_feedback_messages_received?: number;
  readonly engine_malformed_messages?: number;
  readonly engine_dropped_inputs?: number;
  readonly pending_engine_inputs: number;
  readonly pending_engine_feedback?: number;
  readonly registered_systems: number;
  readonly phase_count: number;
  readonly last_engine_feedback_processed?: number;
  readonly last_engine_feedback_invalid?: number;
  readonly last_engine_feedback_errors?: number;
  readonly latest_world_hash?: string;
  readonly hash_log?: RuntimeBridgeHashRecord[];
  readonly paused?: boolean;
  readonly step_budget?: number;
}

export interface RuntimeBridgeHashRecord {
  readonly tick: number;
  readonly world_hash: string;
}

export interface RuntimeBridgeEngineConnection {
  readonly adapter_type: string;
  readonly connected: boolean;
  readonly snapshots_sent: number;
  readonly input_packets_received: number;
  readonly feedback_payloads_received: number;
  readonly feedback_messages_received: number;
  readonly malformed_messages: number;
  readonly dropped_inputs: number;
  readonly queued_inputs: number;
  readonly queued_feedback: number;
}

export interface EngineEditAckMessage extends MessageEnvelope {
  readonly type: 'engine_edit_ack';
  readonly accepted: boolean;
  readonly reason?: string;
  readonly affected_entity_ids: string[];
  readonly status?: RuntimeBridgeStatus;
  readonly audit?: EngineEditAuditEntry;
}

export interface EngineEditAuditEntry {
  readonly ts: number;
  readonly kind: EngineEditKind | string;
  readonly entity_id: string;
  readonly mode_id?: string;
  readonly actor_id?: string;
  readonly component_type_id?: number | null;
  readonly component_name?: string;
  readonly field_path?: string;
  readonly value?: unknown;
  readonly accepted: boolean;
  readonly reason: string;
  readonly affected_entity_ids?: string[];
  readonly runtime_tick?: number | null;
  readonly source?: string;
}

export interface EngineEditCommitAckMessage extends MessageEnvelope {
  readonly type: 'engine_edit_commit_ack';
  readonly accepted: boolean;
  readonly reason: string;
  readonly cgs_hash?: string;
  readonly audit_ts?: number;
}

export interface RuntimeControlAckMessage extends MessageEnvelope {
  readonly type: 'runtime_control_ack';
  readonly action: RuntimeControlAction;
  readonly accepted: boolean;
  readonly reason?: string;
  readonly status?: RuntimeBridgeStatus;
  readonly snapshot?: RuntimeTickSnapshot;
}

export interface RuntimeEntityState {
  readonly id: number;
  readonly actor_id?: string;
  readonly components: Record<string, string>;
}

export interface RuntimeGameEvent {
  readonly event_type: string;
  readonly entity_id: number;
  readonly data?: Record<string, unknown>;
}

export interface RuntimeTickSnapshot {
  readonly msg_type: 'tick_snapshot';
  readonly tick: number;
  readonly timestamp_ms: number;
  readonly entities: RuntimeEntityState[];
  readonly spawned_ids?: number[];
  readonly destroyed_ids?: number[];
  readonly events?: RuntimeGameEvent[];
}

export interface TerminalOutputMessage extends MessageEnvelope {
  readonly type: 'terminal_output';
  readonly stream: 'stdout' | 'stderr' | 'system';
  readonly text: string;
  readonly exit_code?: number;
}

export interface TelemetryUpdateMessage extends MessageEnvelope {
  readonly type: 'telemetry_update';
  readonly telemetry: SessionTelemetry;
}

export interface ServerErrorMessage extends MessageEnvelope {
  readonly type: 'server_error';
  readonly code: string;
  readonly message: string;
  readonly action?: string;
  readonly sgc_error?: Record<string, unknown>;
  readonly sgc_validation?: Record<string, unknown> | null;
  readonly approval?: Record<string, unknown>;
  readonly stage?: string;
  readonly transaction_id?: string;
  readonly rollback?: Record<string, unknown>;
  readonly apply_feedback?: PromptApplyFeedback;
}

export interface PongMessage extends MessageEnvelope {
  readonly type: 'pong';
  readonly server_time: number;
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
  | EngineEditAckMessage
  | EngineEditCommitAckMessage
  | RuntimeControlAckMessage
  | TerminalOutputMessage
  | TelemetryUpdateMessage
  | ServerErrorMessage
  | PongMessage;

export const isSessionInit = (m: ServerMessage): m is SessionInitMessage => m.type === 'session_init';
export const isPilPassUpdate = (m: ServerMessage): m is PilPassUpdateMessage => m.type === 'pil_pass_update';
export const isPilResult = (m: ServerMessage): m is PilResultMessage => m.type === 'pil_result';
export const isCgsUpdate = (m: ServerMessage): m is CgsUpdateMessage => m.type === 'cgs_update';
export const isPilAnswerAck = (m: ServerMessage): m is PilAnswerAckMessage => m.type === 'pil_answer_ack';
export const isEngineTick = (m: ServerMessage): m is EngineTickMessage => m.type === 'engine_tick';
export const isEngineConnected = (m: ServerMessage): m is EngineConnectedMessage => m.type === 'engine_connected';
export const isEngineDisconnected = (m: ServerMessage): m is EngineDisconnectedMessage => m.type === 'engine_disconnected';
export const isEngineEditAck = (m: ServerMessage): m is EngineEditAckMessage => m.type === 'engine_edit_ack';
export const isEngineEditCommitAck = (m: ServerMessage): m is EngineEditCommitAckMessage => m.type === 'engine_edit_commit_ack';
export const isRuntimeControlAck = (m: ServerMessage): m is RuntimeControlAckMessage => m.type === 'runtime_control_ack';
export const isTerminalOutput = (m: ServerMessage): m is TerminalOutputMessage => m.type === 'terminal_output';
export const isTelemetryUpdate = (m: ServerMessage): m is TelemetryUpdateMessage => m.type === 'telemetry_update';
export const isServerError = (m: ServerMessage): m is ServerErrorMessage => m.type === 'server_error';
export const isPong = (m: ServerMessage): m is PongMessage => m.type === 'pong';

export function isServerMessage(value: unknown): value is ServerMessage {
  return isObject(value) && typeof value.type === 'string';
}

export function makePilProcess(
  prompt: string,
  hash: string,
  mode: AssistanceMode,
  sessionId: string,
): PilProcessMessage {
  return { type: 'pil_process', prompt, cgs_hash: hash, mode, session_id: sessionId };
}

export function makePilAnswer(
  clarificationId: string,
  answer: string,
  sessionId: string,
): PilAnswerMessage {
  return { type: 'pil_answer', clarification_id: clarificationId, answer, session_id: sessionId };
}

export function makePilApply(
  sessionId: string,
  approval?: PromptPreviewApproval,
  validationRequirements?: Record<string, boolean>,
): PilApplyMessage {
  return {
    type: 'pil_apply',
    session_id: sessionId,
    ...(approval ? { approval } : {}),
    ...(validationRequirements ? { validation_requirements: validationRequirements } : {}),
  };
}

export function makePilDiscard(sessionId: string): PilDiscardMessage {
  return { type: 'pil_discard', session_id: sessionId };
}

export function makeAssetLink(
  placeholderId: string,
  assetPath: string,
  actorId: string,
  componentName: string,
  sessionId: string,
): AssetLinkMessage {
  return {
    type: 'asset_link',
    placeholder_id: placeholderId,
    asset_path: assetPath,
    actor_id: actorId,
    component_name: componentName,
    session_id: sessionId,
  };
}

export function makeRuntimeControl(
  action: RuntimeControlAction,
  sessionId: string,
  tick?: number,
): RuntimeControlMessage {
  return { type: 'runtime_control', action, session_id: sessionId, tick };
}

export function makeEngineEdit(
  kind: EngineEditKind,
  sessionId: string,
  fields: Omit<EngineEditMessage, 'type' | 'kind' | 'session_id'> = {},
): EngineEditMessage {
  return { type: 'engine_edit', kind, session_id: sessionId, ...fields };
}

export function makeEngineEditCommit(
  sessionId: string,
  fields: Omit<EngineEditCommitMessage, 'type' | 'session_id'>,
): EngineEditCommitMessage {
  return { type: 'engine_edit_commit', session_id: sessionId, ...fields };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
