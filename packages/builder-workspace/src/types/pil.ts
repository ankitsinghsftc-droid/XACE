/**
 * pil.ts — Prompt Intelligence Layer type definitions
 *
 * TypeScript mirror of the Python PIL dataclasses in packages/prompt-intelligence.
 * Uses discriminated unions so the compiler enforces correct field access
 * for each result kind — prevents "reading .transaction on a blocked result" bugs.
 */

// ── Assistance modes ──────────────────────────────────────────────────────────

export type AssistanceMode =
  | 'FULLY_ASSISTED'
  | 'COLLABORATIVE'
  | 'ADVANCED'
  | 'ARCHITECT_MODE';

/** Display labels for each mode pill in the UI */
export const MODE_LABELS: Record<AssistanceMode, string> = {
  FULLY_ASSISTED: '✦ Guided',
  COLLABORATIVE:  '⟡ Collab',
  ADVANCED:       '⬡ Advanced',
  ARCHITECT_MODE: '▣ Architect',
};

/** Short descriptions shown on mode pill hover */
export const MODE_DESCRIPTIONS: Record<AssistanceMode, string> = {
  FULLY_ASSISTED: 'Plain English, max guidance, auto-commits safe changes',
  COLLABORATIVE:  'Balanced — explains choices, asks when unsure',
  ADVANCED:       'Technical, terse, shows all warnings',
  ARCHITECT_MODE: 'Raw schema paths, full telemetry, no hand-holding',
};

// ── Inference tiers ───────────────────────────────────────────────────────────

export type ComplexityTier = 'TIER_S' | 'TIER_M' | 'TIER_L' | 'TIER_XL';

export const TIER_COLORS: Record<ComplexityTier, string> = {
  TIER_S:  'var(--grn)',
  TIER_M:  'var(--cyan)',
  TIER_L:  'var(--cyan)',
  TIER_XL: 'var(--vlt)',
};

// ── Pipeline pass labels ──────────────────────────────────────────────────────

export type PassLabel =
  | 'pass1_planning'
  | 'pass2_dsl_draft'
  | 'pass3_self_critique'
  | 'pass4_determinism_audit'
  | 'pass5_final_output'
  | 'diagnostic_analysis'
  | 'diagnostic_suggest'
  | 'rust_code_generation_attempt1'
  | 'rust_code_generation_attempt2';

export type PassStatus = 'pending' | 'running' | 'done' | 'failed' | 'retrying';

/** Human-readable descriptions shown in the processing view */
export const PASS_DESCRIPTIONS: Record<string, string> = {
  pass1_planning:                 'Planning mutation strategy',
  pass2_dsl_draft:                'Generating schema delta',
  pass3_self_critique:            'Reviewing correctness',
  pass4_determinism_audit:        'Checking determinism invariants',
  pass5_final_output:             'Finalising output',
  diagnostic_analysis:            'Analysing your question',
  diagnostic_suggest:             'Generating suggested fix',
  rust_code_generation_attempt1:  'Generating system code',
  rust_code_generation_attempt2:  'Correcting generated code',
};

/** Which tier runs each pass (for display) */
export const PASS_TIERS: Partial<Record<PassLabel, ComplexityTier>> = {
  pass1_planning:              'TIER_L',
  pass2_dsl_draft:             'TIER_L',
  pass3_self_critique:         'TIER_M',
  pass4_determinism_audit:     'TIER_M',
  pass5_final_output:          'TIER_M',
  diagnostic_analysis:         'TIER_M',
  diagnostic_suggest:          'TIER_M',
  rust_code_generation_attempt1: 'TIER_XL',
  rust_code_generation_attempt2: 'TIER_XL',
};

// ── Live pass update (streamed per-call during processing) ───────────────────

export interface PassUpdate {
  readonly pass:        PassLabel | string;
  readonly status:      PassStatus;
  readonly tier?:       ComplexityTier;
  readonly tokens?:     number;
  readonly cost_cents?: number;
  readonly cached?:     boolean;
  readonly error?:      string;
}

// ── Mutation operations ───────────────────────────────────────────────────────

export type MutationOpType =
  | 'SET'
  | 'SCALE'
  | 'ADD_ACTOR'
  | 'REMOVE_ACTOR'
  | 'ADD_COMPONENT'
  | 'REMOVE_COMPONENT'
  | 'ADD_SYSTEM'
  | 'REMOVE_SYSTEM'
  | 'ADD_RULE'
  | 'REMOVE_RULE';

export interface MutationOp {
  readonly path:       string;
  readonly op:         MutationOpType;
  readonly value:      unknown;
  readonly type_hint:  string;
  readonly field_name: string;
  readonly actor_id:   string;
  readonly type_id:    number;
}

export interface MutationTransaction {
  readonly operations:        MutationOp[];
  readonly schema_delta_type: string;
  readonly confidence_score:  number;
  readonly risk_level:        'low' | 'medium' | 'high';
  readonly required_recompile: boolean;
  readonly affected_systems:  string[];
  readonly mutation_summary:  string;
}

export interface PromptPreviewApproval {
  readonly schema?: 'xace.prompt_preview_approval.v1';
  readonly preview_id: string;
  readonly approval_token: string;
  readonly approval_source?: string;
  readonly approved_by?: string;
}

export interface PromptDiffPreviewOperation {
  readonly index: number;
  readonly op: string;
  readonly path: string;
  readonly old_value: unknown;
  readonly new_value: unknown;
  readonly preview_value: unknown;
  readonly type_hint: string;
  readonly field_name: string;
  readonly actor_id: string;
  readonly component_type_id: number | null;
}

export interface PromptDiffPreview {
  readonly schema: 'xace.prompt_diff_preview.v1';
  readonly preview_id: string;
  readonly approval_token: string;
  readonly approval_token_hash: string;
  readonly approval_required: boolean;
  readonly parent_cgs_hash: string;
  readonly transaction_fingerprint: string;
  readonly mutation_summary: string;
  readonly risk_level: string;
  readonly confidence: number;
  readonly cgs_diff: {
    readonly schema: 'xace.prompt_diff_preview.cgs.v1';
    readonly operation_count: number;
    readonly operations: PromptDiffPreviewOperation[];
  };
  readonly system_diff: Record<string, unknown>;
  readonly asset_diff: Record<string, unknown>;
  readonly sgc_diff: Record<string, unknown>;
  readonly runtime_diff: Record<string, unknown>;
  readonly cost_diff: Record<string, unknown>;
}

// ── Clarification ─────────────────────────────────────────────────────────────

export type QuestionType =
  | 'CHOICE'
  | 'CONFIRM'
  | 'FILL'
  | 'SCOPE_SELECT';

export interface ClarificationQuestion {
  readonly question_id:   string;
  readonly question_type: QuestionType;
  readonly prompt:        string;
  readonly options:       string[];
  readonly hint:          string;
  readonly parameter_key: string;
}

export interface PromptClassifierResult {
  readonly schema: 'xace.prompt_classifier_result.v1';
  readonly matrix_hash: string;
  readonly matrix_version: number;
  readonly category_id: string;
  readonly category_label: string;
  readonly builder_decision: string;
  readonly builder_result_kind: string;
  readonly provider_call_policy: string;
  readonly mutation_policy: string;
  readonly product_wording: string;
  readonly builder_copy: string;
  readonly confidence: number;
  readonly reason: string;
  readonly route: string;
  readonly matched_example_id: string;
  readonly signals: string[];
  readonly provider_call_allowed: boolean;
  readonly mutation_allowed: boolean;
  readonly may_continue_to_pil: boolean;
}

export interface PromptApplyFeedbackSection {
  readonly schema?: string;
  readonly required?: boolean;
  readonly attempted?: boolean;
  readonly accepted?: boolean | null;
  readonly ok?: boolean | null;
  readonly status?: string;
  readonly reason?: string;
  readonly [key: string]: unknown;
}

export interface PromptApplyFeedback {
  readonly schema: 'xace.prompt_apply_feedback.v1';
  readonly ok: boolean;
  readonly stage: string;
  readonly code: string;
  readonly message: string;
  readonly transaction_id: string;
  readonly classifier: PromptClassifierResult | null;
  readonly diff: PromptDiffPreview | null;
  readonly sgc: PromptApplyFeedbackSection;
  readonly runtime_load: PromptApplyFeedbackSection;
  readonly replay: PromptApplyFeedbackSection;
  readonly adapter: PromptApplyFeedbackSection;
  readonly rollback: PromptApplyFeedbackSection;
  readonly cost: PromptApplyFeedbackSection;
  readonly latency: PromptApplyFeedbackSection;
  readonly proof_links: PromptApplyFeedbackSection;
  readonly approval: Record<string, unknown>;
  readonly authority: PromptApplyFeedbackSection;
  readonly warnings: unknown[];
  readonly error: PromptApplyFeedbackSection;
}

// ── Safety ────────────────────────────────────────────────────────────────────

export type GuardName =
  | 'scope_boundary'
  | 'destructive_change'
  | 'cascade_risk'
  | 'determinism_safety'
  | 'performance_risk'
  | 'validation_loop'
  | 'critique_engine'
  | 'output_parser'
  | 'intake'
  | 'pipeline';

// ── PIL Result — discriminated union ─────────────────────────────────────────

interface PILResultBase {
  readonly turn_index:          number;
  readonly intent_category:     string;
  readonly confidence:          number;
  readonly mode_profile_warnings: string[];
  readonly classifier?: PromptClassifierResult;
}

export interface MutationResult extends PILResultBase {
  readonly kind:           'mutation';
  readonly transaction:    MutationTransaction;
  readonly auto_committed: boolean;
  readonly diff_text:      string;
  readonly approval_required?: boolean;
  readonly preview?:       PromptDiffPreview;
}

export interface ClarificationResult extends PILResultBase {
  readonly kind:                     'clarification';
  readonly questions:                ClarificationQuestion[];
  readonly clarification_session_id: string;
  readonly reason:                   string;
  readonly clarification_schema?:    string;
  readonly requires_user_resolution?: boolean;
  readonly resolution_required_before_mutation?: boolean;
}

export interface BlockedResult extends PILResultBase {
  readonly kind:   'blocked';
  readonly reason: string;
  readonly guard:  GuardName | string;
}

export interface DiagnosticResult extends PILResultBase {
  readonly kind:        'diagnostic';
  readonly explanation: string;
  readonly suggestion:  MutationTransaction | null;
}

export interface TierSResult extends PILResultBase {
  readonly kind: 'tier_s';
}

export interface ErrorResult extends PILResultBase {
  readonly kind:   'error';
  readonly reason: string;
}

/** Discriminated union — use type guards to narrow */
export type PILResult =
  | MutationResult
  | ClarificationResult
  | BlockedResult
  | DiagnosticResult
  | TierSResult
  | ErrorResult;

// ── Type guards ───────────────────────────────────────────────────────────────

export const isMutation     = (r: PILResult): r is MutationResult     => r.kind === 'mutation';
export const isClarification = (r: PILResult): r is ClarificationResult => r.kind === 'clarification';
export const isBlocked       = (r: PILResult): r is BlockedResult       => r.kind === 'blocked';
export const isDiagnostic    = (r: PILResult): r is DiagnosticResult    => r.kind === 'diagnostic';
export const isTierS         = (r: PILResult): r is TierSResult         => r.kind === 'tier_s';
export const isError         = (r: PILResult): r is ErrorResult         => r.kind === 'error';

// ── Telemetry ─────────────────────────────────────────────────────────────────

export interface CallRecord {
  readonly pass:        string;
  readonly tier:        ComplexityTier;
  readonly tokens:      number;
  readonly cost_cents:  number;
  readonly cached:      boolean;
  readonly latency_ms:  number;
  readonly timestamp:   number;
}

export interface SessionTelemetry {
  readonly total_input_tokens:   number;
  readonly total_output_tokens:  number;
  readonly total_cost_cents:     number;
  readonly cache_read_tokens:    number;
  /** Fraction 0-1 */
  readonly cache_hit_rate:       number;
  readonly tier_counts:          Record<ComplexityTier, number>;
  readonly calls:                CallRecord[];
}

export function emptyTelemetry(): SessionTelemetry {
  return {
    total_input_tokens:  0,
    total_output_tokens: 0,
    total_cost_cents:    0,
    cache_read_tokens:   0,
    cache_hit_rate:      0,
    tier_counts:         { TIER_S: 0, TIER_M: 0, TIER_L: 0, TIER_XL: 0 },
    calls:               [],
  };
}

export function addCall(
  tele:   SessionTelemetry,
  update: PassUpdate,
): SessionTelemetry {
  const tier    = update.tier ?? 'TIER_M';
  const tokens  = update.tokens ?? 0;
  const cost    = update.cost_cents ?? 0;
  const cached  = update.cached ?? false;

  const newCall: CallRecord = {
    pass:       update.pass,
    tier,
    tokens,
    cost_cents: cost,
    cached,
    latency_ms: 0,
    timestamp:  Date.now(),
  };

  const totalCalls = tele.calls.length + 1;
  const cacheHits  = tele.calls.filter(c => c.cached).length + (cached ? 1 : 0);

  return {
    total_input_tokens:  tele.total_input_tokens + tokens,
    total_output_tokens: tele.total_output_tokens,
    total_cost_cents:    tele.total_cost_cents + cost,
    cache_read_tokens:   tele.cache_read_tokens + (cached ? tokens : 0),
    cache_hit_rate:      cacheHits / totalCalls,
    tier_counts: {
      ...tele.tier_counts,
      [tier]: tele.tier_counts[tier] + 1,
    },
    calls: [...tele.calls, newCall],
  };
}

/** Format cost in cents as a $ string */
export function formatCost(cents: number): string {
  if (cents < 1) return `<$0.01`;
  return `$${(cents / 100).toFixed(2)}`;
}

/** Format token count with k suffix */
export function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}
