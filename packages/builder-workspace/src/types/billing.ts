/** Provider-neutral billing and usage state rendered across Builder modes. */

export type BillingSource = 'api_byok' | 'provider_account' | 'local_runtime' | 'unknown';
export type CostState = 'estimated' | 'provider_managed' | 'local_resource' | 'unknown';
export type TokenTrackingState = 'xace_tracked' | 'provider_reported' | 'local_observed' | 'unknown';

export interface BillingUsageStatus {
  readonly schema: 'xace.billing_usage.v1';
  readonly source: BillingSource;
  readonly cost_state: CostState;
  readonly token_tracking: TokenTrackingState;
  readonly label: string;
  readonly detail: string;
  readonly currency: string | null;
  readonly estimated_cost_cents: number | null;
  readonly usage_summary: Record<string, unknown>;
  readonly rate_limits: Record<string, unknown>;
}

export const UNKNOWN_BILLING: BillingUsageStatus = {
  schema: 'xace.billing_usage.v1',
  source: 'unknown',
  cost_state: 'unknown',
  token_tracking: 'unknown',
  label: 'Cost unavailable',
  detail: 'No reliable billing or usage source is available.',
  currency: null,
  estimated_cost_cents: null,
  usage_summary: {},
  rate_limits: {},
};

export function normalizeBillingUsage(value: unknown): BillingUsageStatus {
  if (typeof value !== 'object' || value === null) return UNKNOWN_BILLING;
  const raw = value as Record<string, unknown>;
  const source = enumValue<BillingSource>(raw.source, ['api_byok', 'provider_account', 'local_runtime', 'unknown'], 'unknown');
  const costState = enumValue<CostState>(raw.cost_state, ['estimated', 'provider_managed', 'local_resource', 'unknown'], 'unknown');
  const tokenTracking = enumValue<TokenTrackingState>(raw.token_tracking, ['xace_tracked', 'provider_reported', 'local_observed', 'unknown'], 'unknown');
  return {
    schema: 'xace.billing_usage.v1',
    source,
    cost_state: costState,
    token_tracking: tokenTracking,
    label: String(raw.label || UNKNOWN_BILLING.label),
    detail: String(raw.detail || UNKNOWN_BILLING.detail),
    currency: typeof raw.currency === 'string' ? raw.currency : null,
    estimated_cost_cents: finiteNumber(raw.estimated_cost_cents),
    usage_summary: objectValue(raw.usage_summary),
    rate_limits: objectValue(raw.rate_limits),
  };
}

export function billingCostLabel(billing: BillingUsageStatus, estimatedCents?: number): string {
  if (billing.cost_state === 'estimated') {
    const cents = Number.isFinite(estimatedCents) ? Number(estimatedCents) : billing.estimated_cost_cents;
    return cents === null ? 'XACE-estimated API cost' : formatUsdCents(cents);
  }
  if (billing.cost_state === 'provider_managed') return 'Provider-managed';
  if (billing.cost_state === 'local_resource') return 'Local compute';
  return 'Cost unavailable';
}

export function billingUsageLabel(billing: BillingUsageStatus): string {
  const lifetime = finiteNumber(billing.usage_summary.lifetimeTokens);
  if (billing.token_tracking === 'provider_reported' && lifetime !== null) {
    return `${formatTokens(lifetime)} tokens reported by provider`;
  }
  if (billing.token_tracking === 'xace_tracked') return 'Tokens tracked by XACE';
  if (billing.token_tracking === 'local_observed') return 'Tokens observed; compute cost not priced';
  if (billing.token_tracking === 'provider_reported') return 'Usage reported by provider when available';
  return 'Usage unavailable';
}

export function billingRateLimitLabel(billing: BillingUsageStatus): string {
  const bucket = objectValue(billing.rate_limits.rateLimits);
  const primary = objectValue(bucket.primary);
  const used = finiteNumber(primary.usedPercent);
  if (used === null) return 'Provider limit state unavailable';
  const resetsAt = finiteNumber(primary.resetsAt);
  const resetText = resetsAt === null ? '' : `; resets ${new Date(resetsAt * 1000).toLocaleString()}`;
  return `${Math.max(0, Math.min(100, used)).toFixed(0)}% of provider window used${resetText}`;
}

function objectValue(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function formatUsdCents(cents: number): string {
  return `$${(Math.max(0, cents) / 100).toFixed(2)} est.`;
}

function formatTokens(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(Math.round(value));
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  const text = String(value || '');
  return allowed.includes(text as T) ? text as T : fallback;
}
