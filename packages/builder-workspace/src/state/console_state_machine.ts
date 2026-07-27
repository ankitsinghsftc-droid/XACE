/**
 * console_state_machine.ts — Builder Console State Machine
 *
 * Models the lifecycle of a single prompt → result interaction.
 * Every center-panel view is driven by this state machine.
 *
 * States:
 *   Idle              → prompt bar is focused, no active mutation
 *   Processing        → PIL running, streaming pass updates
 *   PreviewPending    → mutation result received, user must decide
 *   ClarificationFlow → PIL needs more info, showing question cards
 *   BlockedView       → safety guard blocked the mutation
 *   DiagnosticView    → explanation/debug result returned
 *   ErrorView         → unexpected error
 *
 * Transitions are the only public API for state changes.
 * Components never write state directly — they call transitions.
 *
 * Pattern: push-based observable. Subscribe to get called on every
 * state change. Unsubscribe via the returned cleanup function.
 */

import type {
  PILResult,
  MutationResult,
  ClarificationResult,
  BlockedResult,
  DiagnosticResult,
  PassUpdate,
  SessionTelemetry,
  ClarificationQuestion,
  PromptApplyFeedback,
} from '../types/pil';
import { emptyTelemetry, addCall } from '../types/pil';
import type { CgsUpdateMessage, ServerErrorMessage } from '../api/message_types';

// ── State definitions ─────────────────────────────────────────────────────────

export type ConsoleStateName =
  | 'Idle'
  | 'Processing'
  | 'PreviewPending'
  | 'ApplyingMutation'
  | 'ClarificationFlow'
  | 'BlockedView'
  | 'DiagnosticView'
  | 'ErrorView';

interface StateBase {
  readonly name: ConsoleStateName;
}

export interface IdleState extends StateBase {
  readonly name:           'Idle';
  /** Pre-filled prompt text from "Revise" or "Implement fix" actions */
  readonly prefillPrompt?: string;
  /** Last mutation summary for idle display */
  readonly lastSummary?:   string;
}

export interface ProcessingState extends StateBase {
  readonly name:       'Processing';
  readonly prompt:     string;
  readonly passUpdates: PassUpdate[];
  readonly telemetry:  SessionTelemetry;
  /** Whether this is a re-run after clarification */
  readonly isRetry:    boolean;
}

export interface PreviewPendingState extends StateBase {
  readonly name:   'PreviewPending';
  readonly result: MutationResult;
  readonly prompt: string;
}

export interface ApplyingMutationState extends StateBase {
  readonly name:      'ApplyingMutation';
  readonly result:    MutationResult;
  readonly prompt:    string;
  readonly summary:   string;
  readonly startedAt: number;
}

export interface ClarificationFlowState extends StateBase {
  readonly name:               'ClarificationFlow';
  readonly result:             ClarificationResult;
  readonly prompt:             string;
  readonly answeredCount:      number;
  readonly currentQuestion:    ClarificationQuestion | null;
}

export interface BlockedViewState extends StateBase {
  readonly name:   'BlockedView';
  readonly result: BlockedResult;
  readonly prompt: string;
}

export interface DiagnosticViewState extends StateBase {
  readonly name:   'DiagnosticView';
  readonly result: DiagnosticResult;
  readonly prompt: string;
}

export interface ErrorViewState extends StateBase {
  readonly name:   'ErrorView';
  readonly reason: string;
  readonly prompt: string;
  readonly code?: string;
  readonly stage?: string;
  readonly transactionId?: string;
  readonly applyFeedback?: PromptApplyFeedback;
}

export type ConsoleState =
  | IdleState
  | ProcessingState
  | PreviewPendingState
  | ApplyingMutationState
  | ClarificationFlowState
  | BlockedViewState
  | DiagnosticViewState
  | ErrorViewState;

// ── Type guards ───────────────────────────────────────────────────────────────

export const isIdle              = (s: ConsoleState): s is IdleState              => s.name === 'Idle';
export const isProcessing        = (s: ConsoleState): s is ProcessingState        => s.name === 'Processing';
export const isPreviewPending    = (s: ConsoleState): s is PreviewPendingState    => s.name === 'PreviewPending';
export const isApplyingMutation  = (s: ConsoleState): s is ApplyingMutationState  => s.name === 'ApplyingMutation';
export const isClarificationFlow = (s: ConsoleState): s is ClarificationFlowState => s.name === 'ClarificationFlow';
export const isBlockedView       = (s: ConsoleState): s is BlockedViewState       => s.name === 'BlockedView';
export const isDiagnosticView    = (s: ConsoleState): s is DiagnosticViewState    => s.name === 'DiagnosticView';
export const isErrorView         = (s: ConsoleState): s is ErrorViewState         => s.name === 'ErrorView';

// ── Event types ───────────────────────────────────────────────────────────────

export type ConsoleEvent =
  | { type: 'state_changed';   state: ConsoleState }
  | { type: 'pass_updated';    update: PassUpdate }
  | { type: 'result_received'; result: PILResult }
  | { type: 'mutation_applied'; summary: string }
  | { type: 'mutation_discarded' }
  | { type: 'session_reset' };

export type ConsoleEventType = ConsoleEvent['type'];
type ListenerMap = {
  [K in ConsoleEventType]: Set<(event: Extract<ConsoleEvent, { type: K }>) => void>;
};

// ── State Machine ─────────────────────────────────────────────────────────────

export class ConsoleSM {
  private _state: ConsoleState = { name: 'Idle' };
  private readonly _listeners: ListenerMap = {
    state_changed:    new Set(),
    pass_updated:     new Set(),
    result_received:  new Set(),
    mutation_applied: new Set(),
    mutation_discarded: new Set(),
    session_reset:    new Set(),
  };

  // ── Read ──────────────────────────────────────────────────────────────────

  get state(): ConsoleState {
    return this._state;
  }

  get stateName(): ConsoleStateName {
    return this._state.name;
  }

  // ── Subscribe ─────────────────────────────────────────────────────────────

  on<T extends ConsoleEventType>(
    type: T,
    fn:   (event: Extract<ConsoleEvent, { type: T }>) => void,
  ): () => void {
    const set = this._listeners[type] as Set<typeof fn>;
    set.add(fn);
    return () => set.delete(fn);
  }

  /** Convenience: subscribe to every state change */
  subscribe(fn: (state: ConsoleState) => void): () => void {
    return this.on('state_changed', (ev) => fn(ev.state));
  }

  // ── Transitions ───────────────────────────────────────────────────────────

  /**
   * User submitted a prompt.
   * Valid from: Idle, PreviewPending (revise), DiagnosticView (implement fix).
   */
  submitPrompt(prompt: string, isRetry = false): void {
    const allowed: ConsoleStateName[] = ['Idle', 'PreviewPending', 'DiagnosticView', 'ErrorView'];
    if (!allowed.includes(this._state.name)) {
      console.warn(`[SM] submitPrompt rejected in state ${this._state.name}`);
      return;
    }
    this._set({
      name:        'Processing',
      prompt:      prompt.trim(),
      passUpdates: [],
      telemetry:   emptyTelemetry(),
      isRetry,
    });
  }

  /**
   * Server streamed a pass update.
   * Valid only during Processing.
   */
  receivePassUpdate(update: PassUpdate): void {
    if (!isProcessing(this._state)) return;

    const next: ProcessingState = {
      ...this._state,
      passUpdates: [...this._state.passUpdates, update],
      telemetry:   update.status === 'done'
        ? addCall(this._state.telemetry, update)
        : this._state.telemetry,
    };
    this._set(next);
    this._emit({ type: 'pass_updated', update });
  }

  /**
   * Server returned a complete PIL result.
   * Valid from: Processing.
   */
  receivePILResult(result: PILResult): void {
    if (!isProcessing(this._state)) {
      console.warn(`[SM] receivePILResult ignored in state ${this._state.name}`);
      return;
    }

    const prompt = this._state.prompt;
    this._emit({ type: 'result_received', result });

    switch (result.kind) {
      case 'mutation':
        this._set({ name: 'PreviewPending', result, prompt });
        break;

      case 'clarification':
        this._set({
          name:            'ClarificationFlow',
          result,
          prompt,
          answeredCount:   0,
          currentQuestion: result.questions[0] ?? null,
        });
        break;

      case 'blocked':
        this._set({ name: 'BlockedView', result, prompt });
        break;

      case 'diagnostic':
        this._set({ name: 'DiagnosticView', result, prompt });
        break;

      case 'tier_s':
        // TIER_S goes straight to idle — GDE applied it deterministically
        this._emit({ type: 'mutation_applied', summary: 'Applied (deterministic path)' });
        this._set({ name: 'Idle', lastSummary: 'Applied via deterministic path.' });
        break;

      case 'error':
        this._set({ name: 'ErrorView', reason: result.reason, prompt });
        break;
    }
  }

  /**
   * User clicked Apply.
   * Valid from: PreviewPending.
   */
  applyMutation(): void {
    if (!isPreviewPending(this._state)) return;
    const summary = this._state.result.transaction.mutation_summary;
    this._set({
      name: 'ApplyingMutation',
      result: this._state.result,
      prompt: this._state.prompt,
      summary,
      startedAt: Date.now(),
    });
  }

  /**
   * Server confirmed the apply through cgs_update.
   * Valid from: ApplyingMutation.
   */
  completeApply(_message: CgsUpdateMessage): void {
    if (!isApplyingMutation(this._state)) return;
    const summary = this._state.summary;
    this._emit({ type: 'mutation_applied', summary });
    this._set({ name: 'Idle', lastSummary: summary });
  }

  /**
   * Server rejected an apply with structured validation feedback.
   */
  receiveServerError(message: ServerErrorMessage): void {
    const prompt =
      isApplyingMutation(this._state) || isPreviewPending(this._state) || isProcessing(this._state)
        ? this._state.prompt
        : '';
    this._set({
      name: 'ErrorView',
      reason: message.message,
      prompt,
      code: message.code,
      stage: message.stage,
      transactionId: message.transaction_id,
      applyFeedback: message.apply_feedback,
    });
  }

  /**
   * User clicked Discard.
   * Valid from: PreviewPending.
   */
  discardMutation(): void {
    if (!isPreviewPending(this._state)) return;
    this._emit({ type: 'mutation_discarded' });
    this._set({ name: 'Idle' });
  }

  /**
   * User clicked Revise.
   * Valid from: PreviewPending — returns to Idle with prompt pre-filled.
   */
  reviseMutation(): void {
    if (!isPreviewPending(this._state)) return;
    this._set({
      name:          'Idle',
      prefillPrompt: this._state.prompt,
    });
  }

  /**
   * Server confirmed a clarification answer was accepted.
   * Valid from: ClarificationFlow.
   */
  advanceClarification(nextQuestion: ClarificationQuestion | null): void {
    if (!isClarificationFlow(this._state)) return;
    if (nextQuestion === null) {
      // All questions answered — re-submit
      const prompt = this._state.prompt;
      this._set({
        name:        'Processing',
        prompt,
        passUpdates: [],
        telemetry:   emptyTelemetry(),
        isRetry:     true,
      });
    } else {
      this._set({
        ...this._state,
        answeredCount:   this._state.answeredCount + 1,
        currentQuestion: nextQuestion,
      });
    }
  }

  /**
   * Classifier-level clarifications record scope before a fresh prompt.
   * They do not auto-generate a mutation from the ambiguous wording.
   */
  finishPromptClarification(prefillPrompt: string): void {
    if (!isClarificationFlow(this._state)) return;
    this._set({
      name:          'Idle',
      prefillPrompt: prefillPrompt || this._state.prompt,
    });
  }

  /**
   * User dismissed the diagnostic view.
   * Valid from: DiagnosticView.
   */
  dismissDiagnostic(): void {
    if (!isDiagnosticView(this._state)) return;
    this._set({ name: 'Idle' });
  }

  /**
   * User wants to implement the diagnostic's suggested fix.
   * Valid from: DiagnosticView (when result.suggestion exists).
   */
  implementDiagnosticFix(prefillPrompt: string): void {
    if (!isDiagnosticView(this._state)) return;
    this._set({ name: 'Idle', prefillPrompt });
  }

  /**
   * User dismissed blocked or error view.
   * Valid from: BlockedView, ErrorView.
   */
  dismiss(): void {
    const allowed: ConsoleStateName[] = ['BlockedView', 'ErrorView', 'DiagnosticView'];
    if (!allowed.includes(this._state.name)) return;
    this._set({ name: 'Idle' });
  }

  /**
   * User wants to retry after an error.
   * Valid from: ErrorView.
   */
  retry(): void {
    if (!isErrorView(this._state)) return;
    const prompt = this._state.prompt;
    this._set({
      name:        'Processing',
      prompt,
      passUpdates: [],
      telemetry:   emptyTelemetry(),
      isRetry:     true,
    });
  }

  /**
   * Hard reset — returns to Idle regardless of current state.
   * Use sparingly (session end, reconnect).
   */
  reset(): void {
    this._emit({ type: 'session_reset' });
    this._set({ name: 'Idle' });
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  private _set(next: ConsoleState): void {
    this._state = next;
    this._emit({ type: 'state_changed', state: next });
  }

  private _emit<T extends ConsoleEventType>(
    event: Extract<ConsoleEvent, { type: T }>,
  ): void {
    const listeners = this._listeners[event.type] as Set<(e: typeof event) => void>;
    listeners.forEach(fn => fn(event));
  }
}

/** Shared singleton — import this everywhere */
export const consoleSM = new ConsoleSM();
