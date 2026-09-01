/**
 * Resilient WebSocket client for the XACE builder workspace.
 */

import type {
  AgentEventMessage,
  AgentStatusMessage,
  ClientMessage,
  EngineEditAckMessage,
  EngineTickMessage,
  RuntimeBridgeHashRecord,
  RuntimeBridgeStatus,
  ServerMessage,
} from './message_types';
import {
  BUILDER_PROTOCOL_VERSION,
  isCgsUpdate,
  isEngineConnected,
  isEngineDisconnected,
  isEngineEditAck,
  isEngineTick,
  isAgentEvent,
  isAgentStatus,
  isPilAnswerAck,
  isPilPassUpdate,
  isPilResult,
  isRuntimeControlAck,
  isServerError,
  isServerMessage,
  isSessionInit,
  isTelemetryUpdate,
  isTerminalOutput,
} from './message_types';
import { consoleSM } from '../state/console_state_machine';
import { agentEventStore } from '../state/agent_event_store';
import { cgsStore } from '../state/cgs_store';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface BuilderClientOptions {
  readonly url: string;
  readonly projectPath?: string;
  readonly reconnectBase?: number;
  readonly reconnectMax?: number;
  readonly pingInterval?: number;
  readonly queueLimit?: number;
}

export interface RuntimeStatus {
  readonly connected: boolean;
  readonly adapterType: string;
  readonly engineVersion: string;
  readonly lastTick: EngineTickMessage | null;
  readonly lastError: string;
  readonly controlTick: number;
  readonly aliveCount: number;
  readonly pendingEngineInputs: number;
  readonly pendingEngineFeedback: number;
  readonly engineSnapshotsSent: number;
  readonly engineInputPacketsReceived: number;
  readonly engineFeedbackPayloadsReceived: number;
  readonly engineFeedbackMessagesReceived: number;
  readonly engineMalformedMessages: number;
  readonly engineDroppedInputs: number;
  readonly engineAdapterSequence: number;
  readonly registeredSystems: number;
  readonly phaseCount: number;
  readonly paused: boolean;
  readonly stepBudget: number;
  readonly lastEngineFeedbackProcessed: number;
  readonly lastEngineFeedbackInvalid: number;
  readonly lastEngineFeedbackErrors: number;
  readonly latestWorldHash: string;
  readonly hashLog: readonly RuntimeBridgeHashRecord[];
}

export interface ProviderUxState {
  readonly schema: string;
  readonly state: string;
  readonly code: string;
  readonly label: string;
  readonly message: string;
  readonly action: string;
  readonly severity: string;
}

export interface PromptProviderStatus {
  readonly checked: boolean;
  readonly ready: boolean;
  readonly provider: string;
  readonly model: string;
  readonly message: string;
  readonly action: string;
  readonly ux_state?: ProviderUxState | null;
}

export interface PromptCapabilityExample {
  readonly id: string;
  readonly prompt: string;
  readonly expected_builder_route: string;
  readonly notes: string;
}

export interface PromptCapabilityCategory {
  readonly id: string;
  readonly label: string;
  readonly builder_decision: string;
  readonly builder_result_kind: string;
  readonly provider_call_policy: string;
  readonly mutation_policy: string;
  readonly product_wording: string;
  readonly builder_copy: string;
  readonly requirements: readonly string[];
  readonly examples: readonly PromptCapabilityExample[];
}

export interface PromptCapabilityMatrix {
  readonly schema: 'xace.prompt_capability_matrix.v1';
  readonly version: number;
  readonly updated: string;
  readonly owner_task: number;
  readonly source_of_truth: string;
  readonly matrix_hash: string;
  readonly matrix_path: string;
  readonly category_order: readonly string[];
  readonly categories: readonly PromptCapabilityCategory[];
}

const DEFAULT_OPTIONS: Required<Omit<BuilderClientOptions, 'url'>> = {
  projectPath: './project',
  reconnectBase: 1000,
  reconnectMax: 30_000,
  pingInterval: 20_000,
  queueLimit: 250,
};

type ConnectionStateListener = (state: ConnectionState) => void;
type EngineTickListener = (
  tick: number,
  fps: number,
  worldHash: string,
  msPerTick: number,
  message: EngineTickMessage,
) => void;
type RuntimeStatusListener = (status: RuntimeStatus) => void;
type PromptProviderStatusListener = (status: PromptProviderStatus) => void;
type ServerMessageListener = (message: ServerMessage) => void;
type AgentEventListener = (message: AgentEventMessage) => void;
type AgentStatusListener = (message: AgentStatusMessage) => void;
type EngineEditAckListener = (message: EngineEditAckMessage) => void;

export class BuilderClient {
  private readonly opts: Required<BuilderClientOptions>;
  private readonly sessionIdValue: string;

  private ws: WebSocket | null = null;
  private connState: ConnectionState = 'disconnected';
  private reconnectDelay: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private messageQueue: ClientMessage[] = [];
  private intentionallyClosed = false;
  private runtimeStatusRequestInFlight = false;

  private runtimeStatusValue: RuntimeStatus = {
    connected: false,
    adapterType: '',
    engineVersion: '',
    lastTick: null,
    lastError: '',
    controlTick: 0,
    aliveCount: 0,
    pendingEngineInputs: 0,
    pendingEngineFeedback: 0,
    engineSnapshotsSent: 0,
    engineInputPacketsReceived: 0,
    engineFeedbackPayloadsReceived: 0,
    engineFeedbackMessagesReceived: 0,
    engineMalformedMessages: 0,
    engineDroppedInputs: 0,
    engineAdapterSequence: 0,
    registeredSystems: 0,
    phaseCount: 0,
    paused: false,
    stepBudget: 0,
    lastEngineFeedbackProcessed: 0,
    lastEngineFeedbackInvalid: 0,
    lastEngineFeedbackErrors: 0,
    latestWorldHash: '',
    hashLog: [],
  };
  private providerStatusValue: PromptProviderStatus = {
    checked: false,
    ready: false,
    provider: '',
    model: '',
    message: 'Checking provider setup...',
    action: '',
  };

  private readonly connStateListeners = new Set<ConnectionStateListener>();
  private readonly engineTickListeners = new Set<EngineTickListener>();
  private readonly runtimeStatusListeners = new Set<RuntimeStatusListener>();
  private readonly providerStatusListeners = new Set<PromptProviderStatusListener>();
  private readonly rawListeners = new Set<ServerMessageListener>();
  private readonly agentEventListeners = new Set<AgentEventListener>();
  private readonly agentStatusListeners = new Set<AgentStatusListener>();
  private readonly engineEditAckListeners = new Set<EngineEditAckListener>();

  constructor(options: BuilderClientOptions) {
    this.opts = { ...DEFAULT_OPTIONS, ...options };
    this.sessionIdValue = createSessionId();
    this.reconnectDelay = this.opts.reconnectBase;
  }

  get sessionId(): string {
    return this.sessionIdValue;
  }

  get connectionState(): ConnectionState {
    return this.connState;
  }

  get isConnected(): boolean {
    return this.connState === 'connected';
  }

  get runtimeStatus(): RuntimeStatus {
    return this.runtimeStatusValue;
  }

  get providerStatus(): PromptProviderStatus {
    return this.providerStatusValue;
  }

  connect(): void {
    this.intentionallyClosed = false;
    this.openSocket();
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.clearTimers();
    this.ws?.close(1000, 'Client disconnecting');
    this.ws = null;
    this.setConnectionState('disconnected');
  }

  send(message: ClientMessage): void {
    const enriched = this.enrichMessage(message);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(enriched));
      return;
    }
    if (message.type === 'ping') {
      return;
    }
    this.enqueue(enriched);
  }

  requestRuntimeStatus(): void {
    if (this.runtimeStatusRequestInFlight || !this.isConnected) {
      return;
    }
    this.runtimeStatusRequestInFlight = true;
    this.send({
      type: 'runtime_control',
      action: 'snapshot',
      session_id: this.sessionIdValue,
    });
  }

  onConnectionState(listener: ConnectionStateListener): () => void {
    this.connStateListeners.add(listener);
    listener(this.connState);
    return () => this.connStateListeners.delete(listener);
  }

  onEngineTick(listener: EngineTickListener): () => void {
    this.engineTickListeners.add(listener);
    return () => this.engineTickListeners.delete(listener);
  }

  onRuntimeStatus(listener: RuntimeStatusListener): () => void {
    this.runtimeStatusListeners.add(listener);
    listener(this.runtimeStatusValue);
    return () => this.runtimeStatusListeners.delete(listener);
  }

  onProviderStatus(listener: PromptProviderStatusListener): () => void {
    this.providerStatusListeners.add(listener);
    listener(this.providerStatusValue);
    return () => this.providerStatusListeners.delete(listener);
  }

  updateProviderStatus(partial: Partial<PromptProviderStatus>): void {
    this.providerStatusValue = { ...this.providerStatusValue, ...partial };
    this.providerStatusListeners.forEach((listener) => listener(this.providerStatusValue));
  }

  async fetchPromptCapabilityMatrix(): Promise<PromptCapabilityMatrix> {
    const response = await fetch('/api/prompt/capability-matrix');
    if (!response.ok) {
      throw new Error(`Prompt capability matrix request failed: ${response.status}`);
    }
    return response.json() as Promise<PromptCapabilityMatrix>;
  }

  onRawMessage(listener: ServerMessageListener): () => void {
    this.rawListeners.add(listener);
    return () => this.rawListeners.delete(listener);
  }

  onEngineEditAck(listener: EngineEditAckListener): () => void {
    this.engineEditAckListeners.add(listener);
    return () => this.engineEditAckListeners.delete(listener);
  }

  onAgentEvent(listener: AgentEventListener): () => void {
    this.agentEventListeners.add(listener);
    return () => this.agentEventListeners.delete(listener);
  }

  onAgentStatus(listener: AgentStatusListener): () => void {
    this.agentStatusListeners.add(listener);
    const current = agentEventStore.select().status;
    if (current) {
      listener(current);
    }
    return () => this.agentStatusListeners.delete(listener);
  }

  private openSocket(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) {
      return;
    }

    const url = `${this.opts.url.replace(/\/$/, '')}/${this.sessionIdValue}`;
    this.setConnectionState(this.connState === 'disconnected' ? 'connecting' : 'reconnecting');

    try {
      this.ws = new WebSocket(url);
    } catch (error) {
      this.updateRuntimeStatus({ lastError: String(error) });
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => this.handleOpen();
    this.ws.onmessage = (event) => this.handleMessage(event);
    this.ws.onerror = () => {
      this.updateRuntimeStatus({ lastError: 'websocket error' });
    };
    this.ws.onclose = () => this.handleClose();
  }

  private handleOpen(): void {
    this.setConnectionState('connected');
    this.reconnectDelay = this.opts.reconnectBase;
    this.flushQueue();
    this.send({
      type: 'cgs_request',
      session_id: this.sessionIdValue,
      project_path: this.opts.projectPath,
    });
    if (this.opts.pingInterval > 0) {
      this.clearPingTimer();
      this.pingTimer = setInterval(() => {
        this.send({ type: 'ping', session_id: this.sessionIdValue });
      }, this.opts.pingInterval);
    }
  }

  private handleMessage(event: MessageEvent): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(String(event.data));
    } catch (error) {
      this.updateRuntimeStatus({ lastError: `invalid JSON from server: ${String(error)}` });
      return;
    }
    if (!isServerMessage(parsed)) {
      this.updateRuntimeStatus({ lastError: 'server message missing type' });
      return;
    }
    const message = parsed;
    this.rawListeners.forEach((listener) => listener(message));
    this.dispatch(message);
  }

  private handleClose(): void {
    this.clearPingTimer();
    this.runtimeStatusRequestInFlight = false;
    this.updateRuntimeStatus({ connected: false });
    if (this.intentionallyClosed) {
      this.setConnectionState('disconnected');
      return;
    }
    this.setConnectionState('reconnecting');
    this.scheduleReconnect();
  }

  private dispatch(message: ServerMessage): void {
    if (isSessionInit(message)) {
      cgsStore.initialize(message.cgs, message.hash, message.snapshots);
      return;
    }
    if (isPilPassUpdate(message)) {
      consoleSM.receivePassUpdate(message.update);
      return;
    }
    if (isPilResult(message)) {
      consoleSM.receivePILResult(message.result);
      return;
    }
    if (isCgsUpdate(message)) {
      cgsStore.setCGS(message.cgs, message.hash, message.snapshot);
      cgsStore.setHighlightedNodes(message.affected_node_ids);
      consoleSM.completeApply(message);
      return;
    }
    if (isPilAnswerAck(message)) {
      if (message.accepted) {
        if (message.requires_reprompt) {
          consoleSM.finishPromptClarification(message.resolved_prompt ?? '');
        } else {
          consoleSM.advanceClarification(message.next_question);
        }
      } else {
        this.updateRuntimeStatus({ lastError: message.error ?? 'clarification rejected' });
      }
      return;
    }
    if (isEngineTick(message)) {
      this.updateRuntimeStatus({ connected: true, lastTick: message, lastError: '' });
      this.engineTickListeners.forEach((listener) => {
        listener(message.tick, message.fps, message.world_hash, message.ms_per_tick, message);
      });
      return;
    }
    if (isEngineConnected(message)) {
      this.updateRuntimeStatus({
        connected: true,
        adapterType: message.adapter_type,
        engineVersion: message.engine_version,
        lastError: '',
      });
      return;
    }
    if (isEngineDisconnected(message)) {
      this.updateRuntimeStatus({ connected: false, lastError: message.reason });
      return;
    }
    if (isEngineEditAck(message)) {
      this.applyRuntimeBridgeStatus(message.status);
      this.engineEditAckListeners.forEach((listener) => listener(message));
      if (!message.accepted) {
        this.updateRuntimeStatus({ lastError: message.reason ?? 'engine edit rejected' });
      }
      return;
    }
    if (isRuntimeControlAck(message)) {
      this.runtimeStatusRequestInFlight = false;
      this.applyRuntimeBridgeStatus(message.status);
      if (!message.accepted) {
        this.updateRuntimeStatus({ lastError: message.reason ?? 'runtime command rejected' });
      } else {
        this.updateRuntimeStatus({ lastError: '' });
      }
      return;
    }
    if (isAgentStatus(message)) {
      agentEventStore.receiveStatus(message);
      this.agentStatusListeners.forEach((listener) => listener(message));
      return;
    }
    if (isAgentEvent(message)) {
      agentEventStore.receiveEvent(message);
      this.agentEventListeners.forEach((listener) => listener(message));
      return;
    }
    if (isTerminalOutput(message)) {
      window.dispatchEvent(new CustomEvent('xace:terminal-output', { detail: message }));
      return;
    }
    if (isTelemetryUpdate(message)) {
      return;
    }
    if (isServerError(message)) {
      this.runtimeStatusRequestInFlight = false;
      const action = message.action ? ` ${message.action}` : '';
      this.updateRuntimeStatus({ lastError: `${message.code}: ${message.message}${action}` });
      if (message.apply_feedback) {
        consoleSM.receiveServerError(message);
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.intentionallyClosed || this.reconnectTimer) {
      return;
    }
    const delay = this.reconnectDelay;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.opts.reconnectMax);
      this.openSocket();
    }, delay);
  }

  private flushQueue(): void {
    const queued = this.messageQueue;
    this.messageQueue = [];
    queued.forEach((message) => this.send(message));
  }

  private enqueue(message: ClientMessage): void {
    this.messageQueue.push(message);
    if (this.messageQueue.length > this.opts.queueLimit) {
      this.messageQueue.splice(0, this.messageQueue.length - this.opts.queueLimit);
    }
  }

  private enrichMessage(message: ClientMessage): ClientMessage {
    return {
      ...message,
      session_id: this.sessionIdValue,
      protocol_version: BUILDER_PROTOCOL_VERSION,
    } as ClientMessage;
  }

  private setConnectionState(state: ConnectionState): void {
    if (state === this.connState) {
      return;
    }
    this.connState = state;
    this.connStateListeners.forEach((listener) => listener(state));
  }

  private updateRuntimeStatus(partial: Partial<RuntimeStatus>): void {
    this.runtimeStatusValue = { ...this.runtimeStatusValue, ...partial };
    this.runtimeStatusListeners.forEach((listener) => listener(this.runtimeStatusValue));
  }

  private applyRuntimeBridgeStatus(status: RuntimeBridgeStatus | undefined): void {
    if (!status) {
      return;
    }
    this.updateRuntimeStatus({
      connected: true,
      adapterType: typeof status.adapter_type === 'string' ? status.adapter_type : this.runtimeStatusValue.adapterType,
        controlTick: safeNumber(status.tick, this.runtimeStatusValue.controlTick),
      aliveCount: safeNumber(status.alive_count, this.runtimeStatusValue.aliveCount),
      pendingEngineInputs: safeNumber(status.pending_engine_inputs, 0),
      pendingEngineFeedback: safeNumber(status.pending_engine_feedback, 0),
      engineSnapshotsSent: safeNumber(status.engine_snapshots_sent, 0),
      engineInputPacketsReceived: safeNumber(status.engine_input_packets_received, 0),
      engineFeedbackPayloadsReceived: safeNumber(status.engine_feedback_payloads_received, 0),
      engineFeedbackMessagesReceived: safeNumber(status.engine_feedback_messages_received, 0),
      engineMalformedMessages: safeNumber(status.engine_malformed_messages, 0),
      engineDroppedInputs: safeNumber(status.engine_dropped_inputs, 0),
      engineAdapterSequence: safeNumber(status.engine_adapter_sequence, this.runtimeStatusValue.engineAdapterSequence),
      registeredSystems: safeNumber(status.registered_systems, 0),
      phaseCount: safeNumber(status.phase_count, 0),
      paused: Boolean(status.paused),
      stepBudget: safeNumber(status.step_budget, 0),
      lastEngineFeedbackProcessed: safeNumber(status.last_engine_feedback_processed, 0),
      lastEngineFeedbackInvalid: safeNumber(status.last_engine_feedback_invalid, 0),
      lastEngineFeedbackErrors: safeNumber(status.last_engine_feedback_errors, 0),
      latestWorldHash: typeof status.latest_world_hash === 'string' ? status.latest_world_hash : '',
      hashLog: Array.isArray(status.hash_log) ? status.hash_log : [],
    });
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.clearPingTimer();
  }

  private clearPingTimer(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}

export let builderClient: BuilderClient;

export function initBuilderClient(options: BuilderClientOptions): BuilderClient {
  builderClient = new BuilderClient(options);
  return builderClient;
}

function createSessionId(): string {
  const timestamp = Date.now().toString(36);
  const bytes = new Uint8Array(6);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  const suffix = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${timestamp}-${suffix}`;
}

function safeNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}
