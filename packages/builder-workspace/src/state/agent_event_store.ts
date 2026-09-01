/**
 * Minimal Agent Mode event store.
 *
 * AG-007 intentionally keeps this as a clean functional substrate: compact
 * status, ordered event history, and subscription hooks. The larger XACE 11
 * creation-experience redesign can decide how this should look.
 */

import type { AgentEventMessage, AgentStatusMessage } from '../api/message_types';

export interface AgentEventStoreState {
  readonly status: AgentStatusMessage | null;
  readonly events: readonly AgentEventMessage[];
  readonly lastError: string;
  readonly maxEvents: number;
}

const DEFAULT_MAX_EVENTS = 500;

const INITIAL_STATE: AgentEventStoreState = {
  status: null,
  events: [],
  lastError: '',
  maxEvents: DEFAULT_MAX_EVENTS,
};

type Listener = (state: AgentEventStoreState) => void;

export class AgentEventStore {
  private _state: AgentEventStoreState = INITIAL_STATE;
  private readonly _listeners: Set<Listener> = new Set();

  get state(): AgentEventStoreState {
    return this._state;
  }

  subscribe(listener: Listener): () => void {
    this._listeners.add(listener);
    listener(this._state);
    return () => this._listeners.delete(listener);
  }

  select(): AgentEventStoreState {
    return this._state;
  }

  reset(): void {
    this._update(INITIAL_STATE);
  }

  receiveStatus(status: AgentStatusMessage): void {
    this._update({
      ...this._state,
      status,
      lastError: status.state === 'error' ? status.message : this._state.lastError,
    });
  }

  receiveEvent(event: AgentEventMessage): void {
    const events = [...this._state.events, event].slice(-this._state.maxEvents);
    this._update({
      ...this._state,
      events,
      lastError: event.event_type === 'error' ? event.message : this._state.lastError,
    });
  }

  private _update(next: AgentEventStoreState): void {
    this._state = next;
    this._listeners.forEach((listener) => listener(this._state));
  }
}

export const agentEventStore = new AgentEventStore();

