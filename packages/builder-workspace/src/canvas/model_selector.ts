/**
 * model_selector.ts - Provider and model settings panel.
 */

import type { BuilderClient, ProviderUxState } from '../api/builder_client';

const STYLES = `
.xb-ms-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  background: rgba(255,255,255,.04);
  border: 1px solid var(--bd);
  border-radius: 4px;
  cursor: pointer;
  font-size: 9.5px;
  color: var(--txt2);
  font-family: inherit;
  white-space: nowrap;
  transition: all var(--tr-f);
  max-width: 155px;
  overflow: hidden;
  text-overflow: ellipsis;
  position: relative;
}
.xb-ms-btn:hover { border-color: var(--bdh); color: var(--txt); }
.xb-ms-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.xb-ms-dot.healthy { background: var(--grn); }
.xb-ms-dot.unhealthy { background: var(--red); }
.xb-ms-dot.loading { background: var(--amb); animation: pulse-dot 1s ease-in-out infinite; }
.xb-ms-drop {
  position: fixed;
  background: var(--bga);
  border: 1px solid var(--bdh);
  border-radius: var(--r);
  width: min(430px, calc(100vw - 18px));
  z-index: 600;
  padding: 8px;
  box-shadow: 0 8px 32px rgba(0,0,0,.5);
  animation: fade-in 100ms ease-out;
}
.xb-ms-status {
  border: 1px solid var(--bd);
  border-radius: var(--rs);
  background: rgba(255,255,255,.025);
  padding: 7px;
  margin-bottom: 7px;
  display: grid;
  gap: 4px;
}
.xb-ms-status-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 7px;
  font-size: 9.5px;
  line-height: 1.35;
}
.xb-ms-status-k {
  color: var(--txt3);
  text-transform: uppercase;
  letter-spacing: .06em;
  font-size: 8px;
}
.xb-ms-status-v {
  color: var(--txt2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.xb-ms-status-v.ok { color: var(--grn); }
.xb-ms-status-v.warn { color: var(--amb); }
.xb-ms-status-v.err { color: var(--red); }
.xb-ms-section {
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--txt3);
  padding: 4px 2px 5px;
}
.xb-ms-provider-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
  margin-bottom: 7px;
}
.xb-ms-provider {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  gap: 7px;
  align-items: center;
  min-height: 34px;
  padding: 7px;
  background: rgba(255,255,255,.025);
  color: var(--txt2);
  border: 1px solid var(--bd);
  border-radius: var(--rs);
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.xb-ms-provider:hover { border-color: var(--bdh); color: var(--txt); }
.xb-ms-provider:disabled { opacity: .62; cursor: default; }
.xb-ms-provider.active { border-color: var(--cyan); background: var(--cynd); }
.xb-ms-provider-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
}
.xb-ms-form {
  border-top: 1px solid var(--bd);
  padding-top: 7px;
  display: grid;
  gap: 7px;
}
.xb-ms-field {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.xb-ms-label {
  color: var(--txt3);
  font-size: 8.5px;
  text-transform: uppercase;
  letter-spacing: .06em;
}
.xb-ms-input,
.xb-ms-select {
  width: 100%;
  min-width: 0;
  height: 26px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--bd);
  background: rgba(0,0,0,.24);
  color: var(--txt);
  font: 10px var(--font-mono);
  outline: none;
}
.xb-ms-input:focus,
.xb-ms-select:focus { border-color: var(--cyan); }
.xb-ms-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.xb-ms-action {
  height: 26px;
  padding: 0 10px;
  border-radius: 4px;
  border: 1px solid var(--bd);
  background: rgba(255,255,255,.04);
  color: var(--txt2);
  cursor: pointer;
  font: 10px var(--font-ui);
}
.xb-ms-action:hover { border-color: var(--bdh); color: var(--txt); }
.xb-ms-action.primary { border-color: var(--cyan); color: var(--cyan); background: var(--cynd); }
.xb-ms-action:disabled { opacity: .55; cursor: default; }
.xb-ms-message {
  min-height: 14px;
  color: var(--txt3);
  font-size: 9px;
  line-height: 1.4;
}
.xb-ms-message.ok { color: var(--grn); }
.xb-ms-message.err { color: var(--red); }
.xb-ms-note {
  color: var(--txt3);
  font-size: 8.5px;
  line-height: 1.35;
}
.xb-ms-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 6px;
}
.xb-ms-refresh {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--txt3);
  cursor: pointer;
  font-size: 9px;
  padding: 0 2px;
  font-family: inherit;
}
.xb-ms-refresh:hover { color: var(--txt2); }
`;

interface ProviderChecks {
  key_present: boolean;
  key_valid: boolean;
  model_reachable: boolean;
  test_call: boolean;
}

interface ProviderReadiness {
  ok: boolean;
  provider: string;
  model: string;
  kind: string;
  code: string;
  message: string;
  action: string;
  checks: ProviderChecks;
  ux_state: ProviderUxState | null;
}

interface ProviderOption {
  id: string;
  label: string;
  kind: string;
  requires_key: boolean;
  default_model: string;
  base_url: string;
  models: string[];
  key_present: boolean;
  key_fingerprint: string;
  healthy: boolean;
  ready: boolean;
  checks: ProviderChecks;
  message: string;
}

interface AiModeOption {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
  available: boolean;
  ready: boolean;
  active: boolean;
  code: string;
  message: string;
  action: string;
  reserved: boolean;
}

interface AgentSecurityPolicy {
  readonly allow_raw_shell: boolean;
  readonly allow_real_project_writes: boolean;
  readonly allow_direct_gde_commit: boolean;
  readonly allow_direct_runtime_mutation: boolean;
  readonly allow_credential_access: boolean;
  readonly builder_safe: boolean;
}

interface AgentCapabilities {
  readonly supports_mcp_tools: boolean;
  readonly supports_streaming_events: boolean;
  readonly supports_thread_resume: boolean;
  readonly supports_thread_fork: boolean;
  readonly supports_compaction: boolean;
  readonly supports_cancellation: boolean;
  readonly supports_model_discovery: boolean;
  readonly supports_account_state: boolean;
  readonly supports_progressive_retrieval: boolean;
  readonly supported_tool_transports: readonly string[];
  readonly xace_tools: readonly Record<string, unknown>[];
  readonly security_policy: AgentSecurityPolicy;
  readonly warnings: readonly string[];
}

interface AgentProviderStatus {
  readonly schema: string;
  readonly provider_id: string;
  readonly display_name: string;
  readonly provider_kind: string;
  readonly installed: boolean;
  readonly available: boolean;
  readonly auth_state: string;
  readonly executable_path: string | null;
  readonly version: string | null;
  readonly min_supported_version: string | null;
  readonly account_label: string | null;
  readonly capabilities: AgentCapabilities;
  readonly warnings: readonly string[];
  readonly last_checked_at: string;
  readonly metadata: Record<string, unknown>;
}

interface AgentModeStatus extends AiModeOption {
  mode: string;
  primary_adapter: string;
  selected_adapter: string;
  certified_adapters: string[];
  available_adapters: string[];
  adapters: AgentProviderStatus[];
  primary_adapter_status: AgentProviderStatus | null;
  completion_scope: string;
  feature_stage: string;
  tool_transport_preference: string;
  distribution?: Record<string, unknown>;
}

interface ProviderSettings {
  ok: boolean;
  provider: string;
  current: string;
  model: string;
  models: string[];
  healthy: boolean;
  ready: boolean;
  readiness: ProviderReadiness | null;
  url: string;
  providers: ProviderOption[];
  storage_note: string;
  status_message: string;
  ai_mode: string;
  requested_ai_mode: string;
  ai_modes: AiModeOption[];
  agent_mode: AgentModeStatus | null;
}

const UNRESOLVED_MODEL = 'unresolved';

const EMPTY_SETTINGS: ProviderSettings = {
  ok: false,
  provider: 'auto',
  current: 'loading...',
  model: 'loading...',
  models: [],
  healthy: false,
  ready: false,
  readiness: null,
  url: '',
  providers: [],
  storage_note: '',
  status_message: '',
  ai_mode: 'api_byok',
  requested_ai_mode: 'api_byok',
  ai_modes: [],
  agent_mode: null,
};

export class ModelSelector {
  private readonly _client: BuilderClient;
  private _btn!: HTMLButtonElement;
  private _info: ProviderSettings = EMPTY_SETTINGS;
  private _selectedProvider = 'auto';
  private _selectedModel = 'auto';
  private _open = false;
  private _drop: HTMLElement | null = null;
  private _message = '';
  private _messageKind: '' | 'ok' | 'err' = '';
  private readonly _onOpenSettings = () => {
    this._open ? this._close() : this._openDrop();
  };

  constructor(client: BuilderClient) {
    this._client = client;
    this._injectStyles();
  }

  mount(container: HTMLElement): HTMLButtonElement {
    this._btn = document.createElement('button');
    this._btn.className = 'xb-ms-btn';
    this._renderBtn();
    this._btn.addEventListener('click', (event) => {
      event.stopPropagation();
      this._open ? this._close() : this._openDrop();
    });
    container.appendChild(this._btn);
    window.addEventListener('xace:open-model-settings', this._onOpenSettings);
    this._fetchSettings();
    return this._btn;
  }

  private _renderBtn(): void {
    const dotClass = this._info.current === 'loading...'
      ? 'loading'
      : this._info.ready ? 'healthy' : 'unhealthy';
    const labelText = `${this._info.provider}:${this._info.current}`;
    const label = labelText.length > 22 ? `${labelText.slice(0, 21)}...` : labelText;
    this._btn.innerHTML = '';
    const dot = document.createElement('div');
    dot.className = `xb-ms-dot ${dotClass}`;
    this._btn.appendChild(dot);
    this._btn.appendChild(document.createTextNode(label));
    const uxState = this._info.readiness?.ux_state;
    this._btn.title = `Provider: ${this._info.provider}. Model: ${this._info.current}. State: ${uxState?.label || (this._info.ready ? 'Ready' : 'Needs setup')}.`;
  }

  private async _fetchSettings(): Promise<void> {
    try {
      const response = await fetch('/api/provider-settings');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      this._info = this._normalizeSettings(await response.json());
      this._selectedProvider = this._info.provider;
      this._selectedModel = this._info.current;
      this._publishReadiness();
      this._renderBtn();
      if (this._drop) this._renderDrop(this._drop);
    } catch {
      this._info = { ...EMPTY_SETTINGS, current: 'no server', model: 'no server' };
      this._client.updateProviderStatus({
        checked: true,
        ready: false,
        provider: '',
        model: '',
        message: 'Builder server is not available.',
        action: 'open_builder',
      });
      this._renderBtn();
    }
  }

  private _openDrop(): void {
    this._open = true;
    this._selectedProvider = this._info.provider || 'auto';
    this._selectedModel = this._info.current || 'auto';

    const drop = document.createElement('div');
    drop.className = 'xb-ms-drop';
    drop.addEventListener('click', (event) => event.stopPropagation());

    const rect = this._btn.getBoundingClientRect();
    drop.style.bottom = `${window.innerHeight - rect.top + 6}px`;
    drop.style.left = `${Math.min(rect.left, window.innerWidth - 440)}px`;

    this._renderDrop(drop);
    document.body.appendChild(drop);
    this._drop = drop;

    setTimeout(() => {
      document.addEventListener('click', this._onOutside, { once: true });
    }, 10);
  }

  private _renderDrop(drop: HTMLElement): void {
    drop.innerHTML = '';
    drop.appendChild(this._buildStatusBlock());
    this._renderAiModes(drop);
    this._renderProviderChoices(drop);
    drop.appendChild(this._buildForm());
    drop.appendChild(this._buildFooter());
  }

  private _buildStatusBlock(): HTMLElement {
    const provider = this._provider(this._info.provider);
    const keyText = provider?.requires_key
      ? provider.key_present ? provider.key_fingerprint || 'stored' : 'missing'
      : 'not required';
    const keyKind = provider?.requires_key
      ? provider.key_present ? 'ok' : 'err'
      : 'ok';
    const testText = provider?.kind === 'hosted'
      ? this._info.ready ? 'ready' : 'not ready'
      : this._info.ready ? 'ready' : 'offline';
    const testKind = provider?.kind === 'hosted'
      ? this._info.ready ? 'ok' : 'warn'
      : this._info.ready ? 'ok' : 'err';
    const uxState = this._info.readiness?.ux_state ?? null;
    const stateText = uxState?.label || (this._info.ready ? 'Ready' : 'Needs setup');
    const stateKind = this._info.ready
      ? 'ok'
      : uxState?.state === 'stale_health_proof' || uxState?.state === 'rate_limit' || uxState?.state === 'quota_failure'
        ? 'warn'
        : 'err';

    const block = document.createElement('div');
    block.className = 'xb-ms-status';
    this._appendStatusRow(block, 'Provider', provider?.label ?? this._info.provider, '');
    this._appendStatusRow(block, 'Model', this._info.current, '');
    this._appendStatusRow(block, 'State', stateText, stateKind);
    this._appendStatusRow(block, 'Key', keyText, keyKind);
    const mode = this._aiMode(this._info.ai_mode);
    this._appendStatusRow(block, 'Mode', mode?.label ?? this._info.ai_mode, mode?.ready ? 'ok' : mode?.active ? 'warn' : '');
    this._appendStatusRow(block, 'Health', testText, testKind);
    return block;
  }

  private _appendStatusRow(parent: HTMLElement, key: string, value: string, kind: string): void {
    const row = document.createElement('div');
    row.className = 'xb-ms-status-row';
    const k = document.createElement('span');
    k.className = 'xb-ms-status-k';
    k.textContent = key;
    const v = document.createElement('span');
    v.className = `xb-ms-status-v ${kind}`;
    v.textContent = value || '-';
    v.title = value || '-';
    row.appendChild(k);
    row.appendChild(v);
    parent.appendChild(row);
  }

  private _renderAiModes(parent: HTMLElement): void {
    if (!this._info.ai_modes.length) return;
    const section = document.createElement('div');
    section.className = 'xb-ms-section';
    section.textContent = 'Mode';
    parent.appendChild(section);

    const grid = document.createElement('div');
    grid.className = 'xb-ms-provider-grid';
    for (const mode of this._info.ai_modes) {
      const button = document.createElement('button');
      button.className = `xb-ms-provider${mode.active ? ' active' : ''}`;
      button.type = 'button';
      button.disabled = mode.id !== 'api_byok';
      button.title = mode.message || mode.description || mode.label;
      const dot = document.createElement('span');
      dot.className = `xb-ms-dot ${mode.ready ? 'healthy' : mode.enabled ? 'loading' : 'unhealthy'}`;
      const label = document.createElement('span');
      label.className = 'xb-ms-provider-name';
      label.textContent = mode.label;
      button.appendChild(dot);
      button.appendChild(label);
      grid.appendChild(button);
    }
    parent.appendChild(grid);

    if (this._info.agent_mode?.message) {
      const note = document.createElement('div');
      note.className = 'xb-ms-note';
      note.textContent = this._info.agent_mode.message;
      parent.appendChild(note);
    }
    const adapter = this._info.agent_mode?.primary_adapter_status ?? this._info.agent_mode?.adapters[0] ?? null;
    if (adapter) {
      const note = document.createElement('div');
      note.className = 'xb-ms-note';
      note.textContent = this._agentAdapterSummary(adapter);
      parent.appendChild(note);
    }
  }

  private _renderProviderChoices(parent: HTMLElement): void {
    const section = document.createElement('div');
    section.className = 'xb-ms-section';
    section.textContent = 'Provider';
    parent.appendChild(section);

    const grid = document.createElement('div');
    grid.className = 'xb-ms-provider-grid';
    for (const provider of this._info.providers) {
      const button = document.createElement('button');
      button.className = `xb-ms-provider${provider.id === this._selectedProvider ? ' active' : ''}`;
      button.type = 'button';
      const dot = document.createElement('span');
      dot.className = `xb-ms-dot ${provider.ready ? 'healthy' : 'unhealthy'}`;
      const label = document.createElement('span');
      label.className = 'xb-ms-provider-name';
      label.textContent = provider.label;
      button.appendChild(dot);
      button.appendChild(label);
      button.addEventListener('click', () => {
        this._selectedProvider = provider.id;
        this._selectedModel = provider.models[0] || provider.default_model || '';
        this._message = '';
        this._messageKind = '';
        this._renderDrop(parent);
      });
      grid.appendChild(button);
    }
    parent.appendChild(grid);
  }

  private _buildForm(): HTMLElement {
    const provider = this._provider(this._selectedProvider);
    const form = document.createElement('div');
    form.className = 'xb-ms-form';
    if (!provider) return form;

    if (provider.requires_key) {
      form.appendChild(this._field('API key', this._keyInput(provider)));
    }

    if (provider.id === 'ollama' || provider.id === 'auto') {
      form.appendChild(this._field('URL', this._urlInput(provider)));
    }

    form.appendChild(this._field('Model', this._modelSelect(provider)));
    form.appendChild(this._field('Manual', this._modelInput(provider)));

    const actions = document.createElement('div');
    actions.className = 'xb-ms-actions';
    const save = document.createElement('button');
    save.className = 'xb-ms-action primary';
    save.type = 'button';
    save.textContent = 'Save';
    save.addEventListener('click', () => this._saveProvider(save));
    const test = document.createElement('button');
    test.className = 'xb-ms-action';
    test.type = 'button';
    test.textContent = 'Test';
    test.addEventListener('click', () => this._testProvider(test));
    const message = document.createElement('div');
    message.className = `xb-ms-message ${this._messageKind}`;
    message.textContent = this._message || this._info.readiness?.ux_state?.message || this._info.readiness?.message || provider.message || '';
    actions.appendChild(save);
    actions.appendChild(test);
    actions.appendChild(message);
    form.appendChild(actions);

    if (this._info.storage_note) {
      const note = document.createElement('div');
      note.className = 'xb-ms-note';
      note.textContent = this._info.storage_note;
      form.appendChild(note);
    }

    return form;
  }

  private _field(labelText: string, input: HTMLElement): HTMLElement {
    const field = document.createElement('label');
    field.className = 'xb-ms-field';
    const label = document.createElement('span');
    label.className = 'xb-ms-label';
    label.textContent = labelText;
    field.appendChild(label);
    field.appendChild(input);
    return field;
  }

  private _keyInput(provider: ProviderOption): HTMLInputElement {
    const input = document.createElement('input');
    input.className = 'xb-ms-input';
    input.id = 'xb-ms-api-key';
    input.type = 'password';
    input.autocomplete = 'off';
    input.placeholder = provider.key_present ? 'Stored key unchanged' : 'Paste API key';
    return input;
  }

  private _urlInput(provider: ProviderOption): HTMLInputElement {
    const input = document.createElement('input');
    input.className = 'xb-ms-input';
    input.id = 'xb-ms-base-url';
    input.type = 'text';
    input.value = provider.base_url || this._info.url || 'http://localhost:11434';
    return input;
  }

  private _modelSelect(provider: ProviderOption): HTMLSelectElement {
    const select = document.createElement('select');
    select.className = 'xb-ms-select';
    select.id = 'xb-ms-model-select';
    const models = provider.models.length ? provider.models : [provider.default_model].filter(Boolean);
    for (const model of models) {
      const option = document.createElement('option');
      option.value = model;
      option.textContent = model;
      option.selected = model === this._selectedModel;
      select.appendChild(option);
    }
    select.addEventListener('change', () => {
      this._selectedModel = select.value;
      const manual = this._drop?.querySelector<HTMLInputElement>('#xb-ms-model-input');
      if (manual) manual.value = select.value;
    });
    return select;
  }

  private _modelInput(provider: ProviderOption): HTMLInputElement {
    const input = document.createElement('input');
    input.className = 'xb-ms-input';
    input.id = 'xb-ms-model-input';
    input.type = 'text';
    input.value = this._selectedModel || provider.default_model || '';
    input.placeholder = provider.default_model || 'model id';
    input.addEventListener('input', () => {
      this._selectedModel = input.value.trim();
    });
    return input;
  }

  private _buildFooter(): HTMLElement {
    const footer = document.createElement('div');
    footer.className = 'xb-ms-footer';
    const note = document.createElement('span');
    note.className = 'xb-ms-note';
    note.textContent = this._info.url || '';
    footer.appendChild(note);
    const refresh = document.createElement('button');
    refresh.className = 'xb-ms-refresh';
    refresh.type = 'button';
    refresh.textContent = 'refresh';
    refresh.addEventListener('click', async () => {
      refresh.disabled = true;
      await this._fetchSettings();
      refresh.disabled = false;
    });
    footer.appendChild(refresh);
    return footer;
  }

  private async _saveProvider(button: HTMLButtonElement): Promise<void> {
    button.disabled = true;
    try {
      const payload = this._currentPayload();
      const response = await this._postJson<ProviderSettings>('/api/provider-settings', payload);
      this._info = this._normalizeSettings(response);
      this._selectedProvider = this._info.provider;
      this._selectedModel = this._info.current;
      this._message = 'Saved.';
      this._messageKind = 'ok';
      this._publishReadiness();
      this._renderBtn();
      this._client.send({
        type: 'model_change',
        provider: this._info.provider,
        model: this._info.current,
        session_id: this._client.sessionId,
      });
      window.dispatchEvent(new CustomEvent('xace:model-changed', {
        detail: { provider: this._info.provider, model: this._info.current },
      }));
    } catch (error) {
      this._message = String(error);
      this._messageKind = 'err';
    } finally {
      button.disabled = false;
      if (this._drop) this._renderDrop(this._drop);
    }
  }

  private async _testProvider(button: HTMLButtonElement): Promise<void> {
    button.disabled = true;
    this._message = 'Testing...';
    this._messageKind = '';
    if (this._drop) this._renderDrop(this._drop);
    try {
      const saved = await this._postJson<ProviderSettings>('/api/provider-settings', this._currentPayload());
      this._info = this._normalizeSettings(saved);
      this._selectedProvider = this._info.provider;
      this._selectedModel = this._info.current;
      const result = await this._postJson<{ ok: boolean; message: string; ux_state?: ProviderUxState }>('/api/provider-settings/test', {
        provider: this._info.provider,
        model: this._info.current,
        base_url: this._info.url,
      });
      this._message = result.ux_state?.message || result.message || (result.ok ? 'Provider is ready.' : 'Provider test failed.');
      this._messageKind = result.ok ? 'ok' : 'err';
      await this._fetchSettings();
    } catch (error) {
      this._message = String(error);
      this._messageKind = 'err';
    } finally {
      button.disabled = false;
      if (this._drop) this._renderDrop(this._drop);
    }
  }

  private _currentPayload(): Record<string, string> {
    const modelInput = this._drop?.querySelector<HTMLInputElement>('#xb-ms-model-input');
    const select = this._drop?.querySelector<HTMLSelectElement>('#xb-ms-model-select');
    const keyInput = this._drop?.querySelector<HTMLInputElement>('#xb-ms-api-key');
    const urlInput = this._drop?.querySelector<HTMLInputElement>('#xb-ms-base-url');
    const model = (modelInput?.value || select?.value || this._selectedModel || '').trim();
    return {
      provider: this._selectedProvider,
      model,
      api_key: keyInput?.value.trim() || '',
      base_url: urlInput?.value.trim() || '',
    };
  }

  private _publishReadiness(): void {
    const readiness = this._info.readiness;
    this._client.updateProviderStatus({
      checked: true,
      ready: Boolean(this._info.ready),
      provider: this._info.provider,
      model: this._info.current,
      message: readiness?.message || this._info.status_message || '',
      action: readiness?.action || '',
      ux_state: readiness?.ux_state || null,
    });
  }

  private async _postJson<T>(url: string, payload: unknown): Promise<T> {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(String(data.error || data.message || `HTTP ${response.status}`));
    }
    return data as T;
  }

  private _provider(id: string): ProviderOption | undefined {
    return this._info.providers.find(provider => provider.id === id);
  }

  private _normalizeSettings(data: unknown): ProviderSettings {
    const raw = (typeof data === 'object' && data !== null ? data : {}) as Partial<ProviderSettings>;
    const providers = Array.isArray(raw.providers)
      ? raw.providers.map(provider => this._normalizeProvider(provider))
      : [];
    return {
      ok: Boolean(raw.ok),
      provider: String(raw.provider || 'auto'),
      current: String(raw.current || raw.model || UNRESOLVED_MODEL),
      model: String(raw.model || raw.current || UNRESOLVED_MODEL),
      models: Array.isArray(raw.models) ? raw.models.map(String) : [],
      healthy: Boolean(raw.healthy),
      ready: Boolean(raw.ready),
      readiness: this._normalizeReadiness(raw.readiness),
      url: String(raw.url || ''),
      providers,
      storage_note: String(raw.storage_note || ''),
      status_message: String(raw.status_message || ''),
      ai_mode: String(raw.ai_mode || 'api_byok'),
      requested_ai_mode: String(raw.requested_ai_mode || raw.ai_mode || 'api_byok'),
      ai_modes: Array.isArray(raw.ai_modes) ? raw.ai_modes.map(mode => this._normalizeAiMode(mode)) : [],
      agent_mode: this._normalizeAgentMode(raw.agent_mode),
    };
  }

  private _normalizeProvider(value: unknown): ProviderOption {
    const raw = (typeof value === 'object' && value !== null ? value : {}) as Partial<ProviderOption>;
    const checksRaw = (typeof raw.checks === 'object' && raw.checks !== null ? raw.checks : {}) as Partial<ProviderChecks>;
    return {
      id: String(raw.id || ''),
      label: String(raw.label || raw.id || ''),
      kind: String(raw.kind || 'hosted'),
      requires_key: Boolean(raw.requires_key),
      default_model: String(raw.default_model || ''),
      base_url: String(raw.base_url || ''),
      models: Array.isArray(raw.models) ? raw.models.map(String) : [],
      key_present: Boolean(raw.key_present),
      key_fingerprint: String(raw.key_fingerprint || ''),
      healthy: Boolean(raw.healthy),
      ready: Boolean(raw.ready),
      message: String(raw.message || ''),
      checks: {
        key_present: Boolean(checksRaw.key_present),
        key_valid: Boolean(checksRaw.key_valid),
        model_reachable: Boolean(checksRaw.model_reachable),
        test_call: Boolean(checksRaw.test_call),
      },
    };
  }

  private _normalizeAiMode(value: unknown): AiModeOption {
    const raw = (typeof value === 'object' && value !== null ? value : {}) as Partial<AiModeOption>;
    return {
      id: String(raw.id || ''),
      label: String(raw.label || raw.id || ''),
      description: String(raw.description || ''),
      enabled: Boolean(raw.enabled),
      available: Boolean(raw.available),
      ready: Boolean(raw.ready),
      active: Boolean(raw.active),
      code: String(raw.code || ''),
      message: String(raw.message || ''),
      action: String(raw.action || ''),
      reserved: Boolean(raw.reserved),
    };
  }

  private _normalizeAgentMode(value: unknown): AgentModeStatus | null {
    if (typeof value !== 'object' || value === null) return null;
    const raw = value as Partial<AgentModeStatus>;
    const base = this._normalizeAiMode(raw);
    const adapters = Array.isArray(raw.adapters)
      ? raw.adapters
          .map(adapter => this._normalizeAgentProviderStatus(adapter))
          .filter((adapter): adapter is AgentProviderStatus => Boolean(adapter))
      : [];
    return {
      ...base,
      mode: String(raw.mode || base.id),
      primary_adapter: String(raw.primary_adapter || ''),
      selected_adapter: String(raw.selected_adapter || ''),
      certified_adapters: Array.isArray(raw.certified_adapters) ? raw.certified_adapters.map(String) : [],
      available_adapters: Array.isArray(raw.available_adapters) ? raw.available_adapters.map(String) : [],
      adapters,
      primary_adapter_status: this._normalizeAgentProviderStatus(raw.primary_adapter_status) ?? adapters[0] ?? null,
      completion_scope: String(raw.completion_scope || ''),
      feature_stage: String(raw.feature_stage || ''),
      tool_transport_preference: String(raw.tool_transport_preference || ''),
      distribution: typeof raw.distribution === 'object' && raw.distribution !== null ? raw.distribution : undefined,
    };
  }

  private _normalizeAgentProviderStatus(value: unknown): AgentProviderStatus | null {
    if (typeof value !== 'object' || value === null) return null;
    const raw = value as Partial<AgentProviderStatus>;
    return {
      schema: String(raw.schema || ''),
      provider_id: String(raw.provider_id || ''),
      display_name: String(raw.display_name || raw.provider_id || ''),
      provider_kind: String(raw.provider_kind || ''),
      installed: Boolean(raw.installed),
      available: Boolean(raw.available),
      auth_state: String(raw.auth_state || 'unknown'),
      executable_path: typeof raw.executable_path === 'string' ? raw.executable_path : null,
      version: typeof raw.version === 'string' ? raw.version : null,
      min_supported_version: typeof raw.min_supported_version === 'string' ? raw.min_supported_version : null,
      account_label: typeof raw.account_label === 'string' ? raw.account_label : null,
      capabilities: this._normalizeAgentCapabilities(raw.capabilities),
      warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
      last_checked_at: String(raw.last_checked_at || ''),
      metadata: typeof raw.metadata === 'object' && raw.metadata !== null ? raw.metadata : {},
    };
  }

  private _normalizeAgentCapabilities(value: unknown): AgentCapabilities {
    const raw = (typeof value === 'object' && value !== null ? value : {}) as Partial<AgentCapabilities>;
    const policy = (typeof raw.security_policy === 'object' && raw.security_policy !== null ? raw.security_policy : {}) as Partial<AgentSecurityPolicy>;
    return {
      supports_mcp_tools: Boolean(raw.supports_mcp_tools),
      supports_streaming_events: Boolean(raw.supports_streaming_events),
      supports_thread_resume: Boolean(raw.supports_thread_resume),
      supports_thread_fork: Boolean(raw.supports_thread_fork),
      supports_compaction: Boolean(raw.supports_compaction),
      supports_cancellation: Boolean(raw.supports_cancellation),
      supports_model_discovery: Boolean(raw.supports_model_discovery),
      supports_account_state: Boolean(raw.supports_account_state),
      supports_progressive_retrieval: Boolean(raw.supports_progressive_retrieval),
      supported_tool_transports: Array.isArray(raw.supported_tool_transports) ? raw.supported_tool_transports.map(String) : [],
      xace_tools: Array.isArray(raw.xace_tools) ? raw.xace_tools.filter(tool => typeof tool === 'object' && tool !== null) as Record<string, unknown>[] : [],
      security_policy: {
        allow_raw_shell: Boolean(policy.allow_raw_shell),
        allow_real_project_writes: Boolean(policy.allow_real_project_writes),
        allow_direct_gde_commit: Boolean(policy.allow_direct_gde_commit),
        allow_direct_runtime_mutation: Boolean(policy.allow_direct_runtime_mutation),
        allow_credential_access: Boolean(policy.allow_credential_access),
        builder_safe: policy.builder_safe !== false,
      },
      warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
    };
  }

  private _aiMode(id: string): AiModeOption | undefined {
    return this._info.ai_modes.find(mode => mode.id === id);
  }

  private _agentAdapterSummary(adapter: AgentProviderStatus): string {
    const metadata = adapter.metadata || {};
    const modelIds = Array.isArray(metadata.model_ids) ? metadata.model_ids.map(String) : [];
    const defaultModel = typeof metadata.default_model === 'string' ? metadata.default_model : '';
    const installText = adapter.installed ? 'installed' : 'missing';
    const versionText = adapter.version ? `v${adapter.version}` : 'version unknown';
    const authText = adapter.auth_state.replace(/_/g, ' ');
    const modelText = modelIds.length
      ? `${modelIds.length} model${modelIds.length === 1 ? '' : 's'}${defaultModel ? `, default ${defaultModel}` : ''}`
      : 'no models reported';
    const transportText = adapter.capabilities.supports_mcp_tools ? 'MCP tools preferred' : 'MCP tools unavailable';
    return `${adapter.display_name || 'Codex'}: ${installText}, ${authText}, ${versionText}; ${modelText}; ${transportText}.`;
  }

  private _normalizeReadiness(value: unknown): ProviderReadiness | null {
    if (typeof value !== 'object' || value === null) return null;
    const raw = value as Partial<ProviderReadiness>;
    const checksRaw = (typeof raw.checks === 'object' && raw.checks !== null ? raw.checks : {}) as Partial<ProviderChecks>;
    return {
      ok: Boolean(raw.ok),
      provider: String(raw.provider || ''),
      model: String(raw.model || ''),
      kind: String(raw.kind || ''),
      code: String(raw.code || ''),
      message: String(raw.message || ''),
      action: String(raw.action || ''),
      ux_state: this._normalizeUxState(raw.ux_state),
      checks: {
        key_present: Boolean(checksRaw.key_present),
        key_valid: Boolean(checksRaw.key_valid),
        model_reachable: Boolean(checksRaw.model_reachable),
        test_call: Boolean(checksRaw.test_call),
      },
    };
  }

  private _normalizeUxState(value: unknown): ProviderUxState | null {
    if (typeof value !== 'object' || value === null) return null;
    const raw = value as Partial<ProviderUxState>;
    return {
      schema: String(raw.schema || ''),
      state: String(raw.state || ''),
      code: String(raw.code || ''),
      label: String(raw.label || raw.state || ''),
      message: String(raw.message || ''),
      action: String(raw.action || ''),
      severity: String(raw.severity || ''),
    };
  }

  private _close(): void {
    this._open = false;
    this._drop?.remove();
    this._drop = null;
  }

  private _onOutside = (): void => { this._close(); };

  private _injectStyles(): void {
    if (document.getElementById('xb-ms-styles')) return;
    const style = document.createElement('style');
    style.id = 'xb-ms-styles';
    style.textContent = STYLES;
    document.head.appendChild(style);
  }
}
