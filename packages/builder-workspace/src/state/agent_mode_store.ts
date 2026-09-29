/**
 * Small shared state for the functional Agent Mode UI.
 *
 * The provider-settings response remains the authority for availability and
 * account state. This store only makes that already-sanitized state available
 * to the prompt bar and the compact Agent panel without prescribing the XACE
 * 11 information architecture.
 */
import { UNKNOWN_BILLING, normalizeBillingUsage, type BillingUsageStatus } from '../types/billing';


export interface AgentProviderUiStatus {
  readonly provider_id: string;
  readonly display_name: string;
  readonly installed: boolean;
  readonly available: boolean;
  readonly auth_state: string;
  readonly version: string | null;
  readonly account_label: string | null;
  readonly billing: BillingUsageStatus;
  readonly metadata: Record<string, unknown>;
}

export interface AgentModeLaunchStatus {
  readonly schema: string;
  readonly status: string;
  readonly release_certified: boolean;
  readonly implementation_shippable: boolean;
  readonly runtime_ready: boolean;
  readonly preferred_path: boolean;
  readonly fallback_mode: string;
  readonly fallback_active: boolean;
  readonly fallback_available: boolean;
  readonly requires_claude_or_local: boolean;
}

export interface AgentModeUiStatus {
  readonly mode: string;
  readonly enabled: boolean;
  readonly available: boolean;
  readonly ready: boolean;
  readonly active: boolean;
  readonly code: string;
  readonly message: string;
  readonly action: string;
  readonly primary_adapter: string;
  readonly tool_transport_preference: string;
  readonly launch_status: AgentModeLaunchStatus;
  readonly primary_adapter_status: AgentProviderUiStatus | null;
  readonly billing: BillingUsageStatus;
}

export interface AgentModeUiState {
  readonly aiMode: string;
  readonly agent: AgentModeUiStatus | null;
  readonly billing: BillingUsageStatus;
}

const INITIAL_STATE: AgentModeUiState = { aiMode: 'api_byok', agent: null, billing: UNKNOWN_BILLING };

type Listener = (state: AgentModeUiState) => void;

export class AgentModeStore {
  private _state: AgentModeUiState = INITIAL_STATE;
  private readonly _listeners = new Set<Listener>();

  get state(): AgentModeUiState {
    return this._state;
  }

  subscribe(listener: Listener): () => void {
    this._listeners.add(listener);
    listener(this._state);
    return () => this._listeners.delete(listener);
  }

  receive(value: { aiMode?: unknown; agent?: unknown; billing?: unknown }): void {
    this._state = {
      aiMode: String(value.aiMode || 'api_byok'),
      agent: normalizeAgentMode(value.agent),
      billing: normalizeBillingUsage(value.billing),
    };
    this._listeners.forEach((listener) => listener(this._state));
  }
}

function normalizeAgentMode(value: unknown): AgentModeUiStatus | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Record<string, unknown>;
  return {
    mode: String(raw.mode || raw.id || 'agent'),
    enabled: Boolean(raw.enabled),
    available: Boolean(raw.available),
    ready: Boolean(raw.ready),
    active: Boolean(raw.active),
    code: String(raw.code || ''),
    message: String(raw.message || ''),
    action: String(raw.action || ''),
    primary_adapter: String(raw.primary_adapter || 'codex_app_server'),
    tool_transport_preference: String(raw.tool_transport_preference || 'mcp'),
    launch_status: normalizeLaunchStatus(raw.launch_status),
    primary_adapter_status: normalizeAdapter(raw.primary_adapter_status),
    billing: normalizeBillingUsage(raw.billing),
  };
}

function normalizeLaunchStatus(value: unknown): AgentModeLaunchStatus {
  const raw = (typeof value === 'object' && value !== null ? value : {}) as Record<string, unknown>;
  return {
    schema: String(raw.schema || 'xace.agent_mode_launch_status.v1'),
    status: String(raw.status || 'unavailable'),
    release_certified: Boolean(raw.release_certified),
    implementation_shippable: Boolean(raw.implementation_shippable),
    runtime_ready: Boolean(raw.runtime_ready),
    preferred_path: Boolean(raw.preferred_path),
    fallback_mode: String(raw.fallback_mode || 'api_byok'),
    fallback_active: Boolean(raw.fallback_active),
    fallback_available: raw.fallback_available !== false,
    requires_claude_or_local: Boolean(raw.requires_claude_or_local),
  };
}

function normalizeAdapter(value: unknown): AgentProviderUiStatus | null {
  if (typeof value !== 'object' || value === null) return null;
  const raw = value as Record<string, unknown>;
  return {
    provider_id: String(raw.provider_id || ''),
    display_name: String(raw.display_name || raw.provider_id || 'Codex App Server'),
    installed: Boolean(raw.installed),
    available: Boolean(raw.available),
    auth_state: String(raw.auth_state || 'unknown'),
    version: typeof raw.version === 'string' ? raw.version : null,
    account_label: typeof raw.account_label === 'string' ? raw.account_label : null,
    billing: normalizeBillingUsage(raw.billing),
    metadata: typeof raw.metadata === 'object' && raw.metadata !== null
      ? raw.metadata as Record<string, unknown>
      : {},
  };
}

export const agentModeStore = new AgentModeStore();
