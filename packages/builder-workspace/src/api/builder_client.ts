/**
 * builder_client.ts — WebSocket client for the XACE builder
 *
 * Responsibilities:
 *   1. Connect to builder_server.py WebSocket endpoint
 *   2. Auto-reconnect with exponential backoff (max 30s)
 *   3. Queue outbound messages while disconnected, flush on reconnect
 *   4. Dispatch incoming messages to typed subscribers
 *   5. Generate and track the session_id
 *   6. Forward PIL pass updates to ConsoleSM in real-time
 *   7. Update CGSStore on cgs_update messages
 *   8. Forward PIL results to ConsoleSM
 *
 * All PIL results are dispatched through ConsoleSM.receivePILResult()
 * so the state machine is the only place that reads result fields.
 *
 * All CGS updates are dispatched through cgsStore.setCGS()
 * so the store is the single source of truth.
 */

import type { ClientMessage, ServerMessage } from './message_types';
import {
  isSessionInit, isPilPassUpdate, isPilResult,
  isCgsUpdate, isPilAnswerAck, isEngineTick,
  isEngineConnected, isEngineDisconnected,
  isTelemetryUpdate, isServerError,
} from './message_types';
import { consoleSM } from '../state/console_state_machine';
import { cgsStore } from '../state/cgs_store';
import { uiStore } from '../state/ui_store';

// ── Connection state ──────────────────────────────────────────────────────────

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface BuilderClientOptions {
  /** WebSocket URL, e.g. 'ws://localhost:8765/ws' */
  url:             string;
  /** Project identifier sent in messages */
  projectPath?:    string;
  /** Initial reconnect delay in ms */
  reconnectBase?:  number;
  /** Maximum reconnect delay in ms */
  reconnectMax?:   number;
  /** Ping interval in ms (0 = disabled) */
  pingInterval?:   number;
}

const DEFAULT_OPTS: Required<Omit<BuilderClientOptions, 'url'>> = {
  projectPath:   './project',
  reconnectBase: 1000,
  reconnectMax:  30_000,
  pingInterval:  20_000,
};

// ── Subscriber types ──────────────────────────────────────────────────────────

type ConnectionStateListener = (state: ConnectionState) => void;
type EngineTickListener = (
  tick: number, fps: number, worldHash: string, msPerTick: number,
) => void;

// ── Builder Client ────────────────────────────────────────────────────────────

export class BuilderClient {
  private readonly _opts: Required<BuilderClientOptions>;
  private readonly _sessionId: string;

  private _ws:               WebSocket | null  = null;
  private _connState:        ConnectionState   = 'disconnected';
  private _reconnectDelay:   number;
  private _reconnectTimer:   ReturnType<typeof setTimeout> | null = null;
  private _pingTimer:        ReturnType<typeof setInterval> | null = null;
  private _messageQueue:     ClientMessage[]   = [];
  private _intentionallyClosed = false;

  private _connStateListeners: Set<ConnectionStateListener> = new Set();
  private _engineTickListeners: Set<EngineTickListener>     = new Set();
  private _rawListeners: Set<(msg: ServerMessage) => void>  = new Set();

  constructor(opts: BuilderClientOptions) {
    this._opts          = { ...DEFAULT_OPTS, ...opts };
    this._sessionId     = this._generateSessionId();
    this._reconnectDelay = this._opts.reconnectBase;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  get sessionId():    string          { return this._sessionId; }
  get connectionState(): ConnectionState { return this._connState; }
  get isConnected():  boolean          { return this._connState === 'connected'; }

  /** Start connecting */
  connect(): void {
    this._intentionallyClosed = false;
    this._openSocket();
  }

  /** Gracefully close */
  disconnect(): void {
    this._intentionallyClosed = true;
    this._clearTimers();
    this._ws?.close(1000, 'Client disconnecting');
    this._setConnState('disconnected');
  }

  /**
   * Send a typed client message.
   * If not connected, queues the message (except pings).
   */
  send(message: ClientMessage): void {
    const enriched = { ...message, session_id: this._sessionId };

    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(enriched));
    } else if (message.type !== 'ping') {
      this._messageQueue.push(enriched as ClientMessage);
    }
  }

  // ── Subscriptions ─────────────────────────────────────────────────────────

  onConnectionState(fn: ConnectionStateListener): () => void {
    this._connStateListeners.add(fn);
    fn(this._connState);
    return () => this._connStateListeners.delete(fn);
  }

  onEngineTick(fn: EngineTickListener): () => void {
    this._engineTickListeners.add(fn);
    return () => this._engineTickListeners.delete(fn);
  }

  /** Low-level: receive every server message (for debugging) */
  onRawMessage(fn: (msg: ServerMessage) => void): () => void {
    this._rawListeners.add(fn);
    return () => this._rawListeners.delete(fn);
  }

  // ── Socket lifecycle ──────────────────────────────────────────────────────

  private _openSocket(): void {
    if (this._ws && this._ws.readyState <= WebSocket.OPEN) return;

    const url = `${this._opts.url}/${this._sessionId}`;
    this._setConnState(this._connState === 'disconnected' ? 'connecting' : 'reconnecting');

    try {
      this._ws = new WebSocket(url);
    } catch (err) {
      console.error('[WS] Failed to create WebSocket:', err);
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen    = this._onOpen.bind(this);
    this._ws.onmessage = this._onMessage.bind(this);
    this._ws.onerror   = this._onError.bind(this);
    this._ws.onclose   = this._onClose.bind(this);
  }

  private _onOpen(): void {
    this._setConnState('connected');
    this._reconnectDelay = this._opts.reconnectBase;

    // Flush queued messages
    const queued = [...this._messageQueue];
    this._messageQueue = [];
    queued.forEach(msg => this.send(msg));

    // Request current CGS state
    this.send({
      type:         'cgs_request',
      session_id:   this._sessionId,
      project_path: this._opts.projectPath,
    });

    // Start ping keepalive
    if (this._opts.pingInterval > 0) {
      this._pingTimer = setInterval(() => {
        this.send({ type: 'ping', session_id: this._sessionId });
      }, this._opts.pingInterval);
    }
  }

  private _onMessage(ev: MessageEvent): void {
    let msg: ServerMessage;
    try {
      msg = JSON.parse(ev.data as string) as ServerMessage;
    } catch (err) {
      console.error('[WS] Failed to parse message:', err, ev.data);
      return;
    }

    // Dispatch to raw listeners (debug)
    this._rawListeners.forEach(fn => fn(msg));

    // Dispatch to typed handlers
    this._dispatch(msg);
  }

  private _onError(ev: Event): void {
    console.error('[WS] Socket error:', ev);
  }

  private _onClose(ev: CloseEvent): void {
    this._clearPingTimer();
    if (this._intentionallyClosed) {
      this._setConnState('disconnected');
      return;
    }
    console.warn(`[WS] Closed (code=${ev.code}). Reconnecting in ${this._reconnectDelay}ms…`);
    this._setConnState('reconnecting');
    this._scheduleReconnect();
  }

  // ── Message dispatch ──────────────────────────────────────────────────────

  private _dispatch(msg: ServerMessage): void {
    if (isSessionInit(msg)) {
      cgsStore.initialize(msg.cgs, msg.hash, msg.snapshots);
      return;
    }

    if (isPilPassUpdate(msg)) {
      consoleSM.receivePassUpdate(msg.update);
      return;
    }

    if (isPilResult(msg)) {
      consoleSM.receivePILResult(msg.result);
      return;
    }

    if (isCgsUpdate(msg)) {
      cgsStore.setCGS(msg.cgs, msg.hash, msg.snapshot);
      cgsStore.setHighlightedNodes(msg.affected_node_ids);
      // If the update is from an auto-commit, notify SM
      if (consoleSM.stateName === 'Processing') {
        // The PIL already returned a result — this is the GDE confirmation
      }
      return;
    }

    if (isPilAnswerAck(msg)) {
      if (!msg.accepted) {
        console.warn('[WS] PIL answer rejected:', msg.error);
        return;
      }
      consoleSM.advanceClarification(msg.next_question);
      return;
    }

    if (isEngineTick(msg)) {
      this._engineTickListeners.forEach(fn =>
        fn(msg.tick, msg.fps, msg.world_hash, msg.ms_per_tick)
      );
      return;
    }

    if (isEngineConnected(msg)) {
      console.info(`[WS] Engine connected: ${msg.adapter_type} ${msg.engine_version}`);
      return;
    }

    if (isEngineDisconnected(msg)) {
      console.info(`[WS] Engine disconnected: ${msg.reason}`);
      return;
    }

    if (isTelemetryUpdate(msg)) {
      // Telemetry panel subscribes directly via raw listener
      return;
    }

    if (isServerError(msg)) {
      console.error(`[WS] Server error [${msg.code}]: ${msg.message}`);
      return;
    }
  }

  // ── Reconnect logic ───────────────────────────────────────────────────────

  private _scheduleReconnect(): void {
    if (this._intentionallyClosed) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectDelay = Math.min(
        this._reconnectDelay * 2,
        this._opts.reconnectMax,
      );
      this._openSocket();
    }, this._reconnectDelay);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  private _setConnState(state: ConnectionState): void {
    if (state === this._connState) return;
    this._connState = state;
    this._connStateListeners.forEach(fn => fn(state));
  }

  private _clearTimers(): void {
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer);  this._reconnectTimer = null; }
    this._clearPingTimer();
  }

  private _clearPingTimer(): void {
    if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }
  }

  private _generateSessionId(): string {
    return [
      Date.now().toString(36),
      Math.random().toString(36).slice(2, 8),
    ].join('-');
  }
}

/** Shared singleton — created in app.ts, exported for components */
export let builderClient: BuilderClient;

export function initBuilderClient(opts: BuilderClientOptions): BuilderClient {
  builderClient = new BuilderClient(opts);
  return builderClient;
}