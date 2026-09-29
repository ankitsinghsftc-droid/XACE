/** AG-026: replaceable setup UI. No credentials or challenges in shared storage. */
import { agentModeStore } from '../state/agent_mode_store';
import { AgentSupportPanel } from './agent_support_panel';

interface RuntimeStatus {
  runtime: {
    setup_mode?: string; preferred_auth_flow?: string; message?: string;
    ready: boolean; state_error?: string | null; pending_operation?: boolean;
    active?: { version: string; executable_path: string; provenance_basis: string } | null;
    active_health?: { code: string };
  };
  job: { state: string; operation: string; error_code?: string | null };
  override_active: boolean;
}
interface Challenge { flow: string; url: string; user_code?: string }
interface AuthStatus {
  state: string; login_state: string; error_code?: string | null; recovery_action?: string;
  account?: { email?: string; plan_type?: string };
  limits?: { primary?: { usedPercent?: number; resetsAt?: number }; limit_reached?: boolean };
  challenge?: Challenge;
}

const HELP: Record<string, string> = {
  isolated_build_failed: 'Local build failed. Check Docker Desktop, use the exact official .tgz archive, and retry. The previous selection is preserved; API/BYOK remains available.',
  digest_mismatch: 'The runtime changed. Restore the original for repair, or verify a new version with Update.',
  schema_reverification_required: 'This pin predates the current compatibility check. Confirm its source and use Repair pin.',
  unsupported_version: 'This version is outside the schema-gated support window. Verify a supported version or roll back.',
  schema_mismatch: 'This runtime is incompatible. Choose a supported version or roll back.',
  private_runtime: 'An editor-private runtime cannot be selected. Choose an official standalone installation.',
  prerelease_runtime: 'Choose a stable official Codex release, not a prerelease.',
  runtime_revoked: 'This runtime is revoked. Select a supported update; do not bypass verification.',
  unsupported_platform: 'This executable does not match this computer. Choose the correct native version.',
  executable_missing: 'Find the installed native Codex executable, or follow the official installation guide.',
  rollback_unavailable: 'The old exact executable must still exist at its recorded path for rollback.',
  repair_requires_pin: 'Configure a verified runtime before using repair.',
  runtime_verification_failed: 'Verification failed. Check the path and official installation, then retry or roll back.',
  auth_expired: 'Sign in again. Codex will refresh and store its own credentials.',
  workspace_restricted: 'Your workspace restricts access. Contact its administrator or switch to API / BYOK.',
  rate_limited: 'The provider limit was reached. Wait for reset or switch to API / BYOK.',
  flow_unsupported: 'Try the other sign-in flow or a supported runtime update.',
  browser_unavailable: 'Use the manual sign-in link or cancel and choose device-code sign-in.',
  provider_unavailable: 'Codex is unavailable. Refresh to retry; API / BYOK remains available.',
  login_expired: 'The login attempt expired. Start a new sign-in.',
  cancelled: 'Verification cancelled. The previous runtime selection was preserved.',
};

const STYLE = `
.xb-agent-setup { padding:10px; border:1px solid var(--bd,#555); margin-bottom:10px; min-width:0; font-size:12px; }
.xb-agent-setup h3 { margin:0 0 8px; font-size:13px; }
.xb-agent-setup p, .xb-agent-setup pre { overflow-wrap:anywhere; white-space:pre-wrap; }
.xb-agent-setup input[type=text], .xb-agent-setup select { box-sizing:border-box; width:100%; min-width:0; padding:7px; margin:4px 0 8px; background:var(--bg2,#222); color:var(--txt,#fff); border:1px solid var(--bd,#666); }
.xb-agent-setup button, .xb-agent-setup a { min-height:32px; padding:5px 8px; overflow-wrap:anywhere; }
.xb-agent-setup button { cursor:pointer; background:var(--bg2,#222); color:var(--txt,#fff); border:1px solid var(--bd,#666); border-radius:4px; }
.xb-agent-setup button:disabled { opacity:.55; cursor:default; }
.xb-agent-setup :focus-visible { outline:2px solid var(--cyan,#00d4ff); outline-offset:2px; }
.xb-agent-setup-actions { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }
.xb-agent-setup label { display:block; margin:6px 0; }
.xb-agent-setup a { color:var(--cyan,#00d4ff); display:inline-block; }
.xb-agent-setup details { margin-top:10px; }
@media (max-width:480px) { .xb-agent-setup-actions > * { flex:1 1 120px; } }
@media (prefers-reduced-motion:reduce) { .xb-agent-setup *, .xb-agent-setup { animation:none!important; transition:none!important; scroll-behavior:auto!important; } }
`;

export class AgentSetupPanel {
  private _root!: HTMLElement;
  private _nativeControls: HTMLElement[] = [];
  private readonly _support = new AgentSupportPanel();
  private _summary!: HTMLElement;
  private _runtimeText!: HTMLElement;
  private _accountText!: HTMLElement;
  private _challenge!: HTMLElement;
  private _diagnostics!: HTMLElement;
  private _path!: HTMLInputElement;
  private _consent!: HTMLInputElement;
  private _logoutConsent!: HTMLInputElement;
  private _archiveControls!: HTMLDivElement;
  private _archivePath!: HTMLInputElement;
  private _archiveConsent!: HTMLInputElement;
  private _buildButton!: HTMLButtonElement;
  private _primary!: HTMLButtonElement;
  private _cancelButton!: HTMLButtonElement;
  private _runtime: RuntimeStatus | null = null;
  private _auth: AuthStatus | null = null;
  private _busy = false;
  private _disposed = false;
  private _polling = false;
  private _epoch = 0;
  private _timer: ReturnType<typeof setInterval> | null = null;
  private _requestAbort = new AbortController();
  private _ownsLogin = false;

  mount(container: HTMLElement): void {
    if (!document.getElementById('xb-agent-setup-style')) {
      const style = document.createElement('style');
      style.id = 'xb-agent-setup-style'; style.textContent = STYLE; document.head.append(style);
    }
    this._root = document.createElement('section');
    this._root.className = 'xb-agent-setup';
    this._root.setAttribute('aria-label', 'Codex setup and recovery');
    const heading = document.createElement('h3'); heading.textContent = 'Set up Codex';
    this._summary = document.createElement('p'); this._summary.setAttribute('role', 'status');
    this._summary.setAttribute('aria-live', 'polite'); this._summary.setAttribute('aria-atomic', 'true');
    this._runtimeText = document.createElement('p'); this._accountText = document.createElement('p');
    this._root.append(heading, this._summary, this._runtimeText, this._accountText);
    this._path = document.createElement('input'); this._path.type = 'text'; this._path.autocomplete = 'off';
    this._path.spellcheck = false; this._path.id = 'xb-agent-runtime-path';
    this._label('Native Codex executable (absolute path)', this._path);
    this._nativeControls.push(this._path, this._root.querySelector<HTMLElement>('label[for="xb-agent-runtime-path"]')!);
    this._consent = this._checkbox('I installed this from the official provider and approve changing XACE’s runtime selection. Active Codex connections will close.');
    this._nativeControls.push(this._consent.parentElement!);
    const controls = this._actions();
    const findInstalled = this._button(controls, 'Find installed Codex', () => this._run(async () => {
      const found = await this._request<{ candidate_path: string }>('/api/agent-runtime/detect', {});
      this._path.value = found.candidate_path;
      this._message(found.candidate_path ? 'Candidate found. Confirm its source, then verify.' : HELP.executable_missing!);
      this._path.focus();
    }));
    this._nativeControls.push(findInstalled);
    this._primary = this._button(controls, 'Check setup', () => this._run(() => this._primaryAction()));
    this._button(controls, 'Refresh / retry', () => this._run(() => this._refresh(true)));
    const guide = document.createElement('a');
    guide.href = 'https://developers.openai.com/codex/cli'; guide.target = '_blank'; guide.rel = 'noopener noreferrer';
    guide.textContent = 'Official installation / update guide'; this._root.append(guide);
    const note = document.createElement('p');
    note.textContent = 'XACE does not download Codex or run installer commands. Fresh installation remains provider-guided; an installed supported runtime can be configured here without a terminal.';
    this._root.append(note);
    this._nativeControls.push(guide, note);
    this._archiveControls = document.createElement('div');
    const archiveGuide = document.createElement('a');
    archiveGuide.href = 'https://registry.npmjs.org/@openai/codex/-/codex-0.155.1-linux-x64.tgz';
    archiveGuide.textContent = 'Download official pinned Codex archive';
    archiveGuide.target = '_blank'; archiveGuide.rel = 'noopener noreferrer';
    const archiveLabel = document.createElement('label');
    archiveLabel.textContent = 'Downloaded .tgz archive (absolute path; Windows Copy as path)';
    this._archivePath = document.createElement('input'); this._archivePath.type = 'text';
    this._archivePath.autocomplete = 'off'; archiveLabel.append(this._archivePath);
    const archiveConsentLabel = document.createElement('label');
    this._archiveConsent = document.createElement('input'); this._archiveConsent.type = 'checkbox';
    archiveConsentLabel.append(this._archiveConsent, ' I approve verifying this official archive and building the isolated runtime locally. Docker may download its pinned base image; existing Codex connections will close.');
    this._archiveControls.append(archiveGuide, archiveLabel, archiveConsentLabel);
    this._buildButton = this._button(this._archiveControls, 'Build / repair isolated runtime', () => this._run(async () => {
      if (!this._archiveConsent.checked) { this._message('Confirm the local build first.'); this._archiveConsent.focus(); return; }
      const path = this._archivePath.value.trim().replace(/^"|"$/g, '');
      if (!path) { this._message('Download the official archive and enter its file path.'); this._archivePath.focus(); return; }
      this._runtime = await this._request<RuntimeStatus>('/api/agent-runtime/install', { confirm: true, runtime_package: path });
      this._archiveConsent.checked = false; this._update();
    }));
    this._root.append(this._archiveControls);
    const recovery = this._actions();
    this._nativeControls.push(recovery);
    for (const [action, label] of [['update', 'Verify update'], ['repair', 'Repair pin'], ['rollback', 'Roll back'], ['remove', 'Remove selection'], ['recover', 'Recover interrupted setup']] as const) {
      this._button(recovery, label, () => this._run(() => this._runtimeAction(action)));
    }
    const auth = this._actions();
    this._nativeControls.push(this._button(auth, 'Sign in with browser', () => this._run(() => this._login('browser'))));
    this._button(auth, 'Sign in with device code', () => this._run(() => this._login('device_code')));
    this._cancelButton = this._button(auth, 'Cancel pending operation', () => { void this._cancel(); });
    this._challenge = document.createElement('div'); this._root.append(this._challenge);
    this._logoutConsent = this._checkbox('I approve signing out of Codex, including other clients that share its credential store.');
    this._button(this._actions(), 'Sign out', () => this._run(async () => {
      if (!this._logoutConsent.checked) { this._message('Confirm the sign-out consequence first.'); this._logoutConsent.focus(); return; }
      this._auth = await this._request<AuthStatus>('/api/agent-auth/logout', { confirm: true });
      this._clearChallenge(); this._logoutConsent.checked = false; this._update(); this._publish();
    }));
    const fallback = this._actions();
    this._button(fallback, 'Switch to API / BYOK', () => { void this._switchApi(); });
    this._button(fallback, 'Choose model / API settings', () => window.dispatchEvent(new CustomEvent('xace:open-model-settings')));
    const details = document.createElement('details'), title = document.createElement('summary');
    title.textContent = 'Local setup diagnostics (no login secrets)';
    this._diagnostics = document.createElement('pre'); details.append(title, this._diagnostics); this._root.append(details);
    this._support.mount(this._root);
    container.append(this._root);
    void this._run(() => this._refresh(false));
    this._timer = setInterval(() => { void this._poll(); }, 1500);
  }

  unmount(): void {
    this._support.unmount();
    this._disposed = true; ++this._epoch;
    if (this._timer) clearInterval(this._timer);
    this._requestAbort.abort();
    if (this._ownsLogin) {
      void fetch('/api/agent-auth/cancel', { method: 'POST', keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-XACE-Agent-Auth': '1' }, body: '{}' }).catch(() => {});
    }
    this._clearChallenge(); this._root.remove();
  }

  private async _request<T>(url: string, payload?: unknown): Promise<T> {
    const response = await fetch(url, { method: payload === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', 'X-XACE-Agent-Auth': '1' },
      body: payload === undefined ? undefined : JSON.stringify(payload), cache: 'no-store',
      signal: this._requestAbort.signal });
    const value = await response.json();
    if (!response.ok || value.ok === false) throw new Error('The action was rejected or the server is unavailable. Check consent and retry.');
    if (this._disposed) throw new Error('closed');
    return value as T;
  }

  private async _run(action: () => Promise<void>): Promise<void> {
    if (this._busy || this._disposed) return;
    this._busy = true; const epoch = this._epoch; this._root.setAttribute('aria-busy', 'true');
    this._cancelButton.disabled = false;
    this._message('Working…');
    try { await action(); }
    catch { if (!this._disposed && epoch === this._epoch) this._message('Action failed. Refresh to retry, or switch to API / BYOK.'); }
    finally { this._busy = false; this._root.setAttribute('aria-busy', 'false'); }
  }

  private async _primaryAction(): Promise<void> {
    if (!this._runtime?.runtime.ready) {
      if (this._runtime?.runtime.setup_mode === 'isolated_backend') { await this._refresh(true); return; }
      await this._runtimeAction('install'); return;
    }
    if (!this._auth || this._auth.state === 'unknown') { await this._refresh(true); return; }
    if (this._auth.state !== 'signed_in') { await this._login(this._runtime?.runtime.preferred_auth_flow || 'browser'); return; }
    const settings = await this._request<{ ai_mode: string; agent_mode: { ready: boolean; message: string }; billing: unknown }>('/api/agent-mode', { mode: 'agent', enabled: true });
    agentModeStore.receive({ aiMode: settings.ai_mode, agent: settings.agent_mode, billing: settings.billing });
    this._publish();
    if (settings.ai_mode === 'agent' && settings.agent_mode?.ready) {
      this._message('Codex Agent Mode is ready. Focus moved to the prompt.');
      window.dispatchEvent(new CustomEvent('xace:focus-prompt'));
    } else this._message(settings.agent_mode?.message || 'Choose an available Codex model in model settings, then retry.');
  }

  private async _runtimeAction(action: string): Promise<void> {
    if (!this._consent.checked) { this._message('Confirm the official source and runtime change first.'); this._consent.focus(); return; }
    if (['install', 'update', 'repair'].includes(action) && !this._path.value.trim()) {
      this._message('Find or enter the native executable path first.'); this._path.focus(); return;
    }
    this._runtime = await this._request<RuntimeStatus>(`/api/agent-runtime/${action}`, {
      confirm: true, ...(['install', 'update', 'repair'].includes(action) ? { executable_path: this._path.value.trim() } : {}),
    });
    this._consent.checked = false; this._update();
  }

  private async _login(flow: string): Promise<void> {
    if (['running', 'cancelling'].includes(this._runtime?.job.state || '')) { this._message('Finish or cancel runtime verification before signing in.'); return; }
    const epoch = this._epoch;
    const status = await this._request<AuthStatus>('/api/agent-auth/start', { flow });
    const challenge = status.challenge; delete status.challenge;
    if (epoch !== this._epoch) return;
    this._auth = status;
    this._ownsLogin = status.login_state === 'pending';
    this._clearChallenge();
    if (challenge) {
      const url = new URL(challenge.url);
      if (url.protocol !== 'https:' || !['auth.openai.com', 'chatgpt.com'].includes(url.hostname)) throw new Error('Unsafe sign-in URL');
      const link = document.createElement('a'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = 'Open secure sign-in (or copy this link if the browser does not open)';
      this._challenge.append(link);
      if (challenge.user_code) { const code = document.createElement('p'); code.textContent = `One-time device code: ${challenge.user_code}`; this._challenge.append(code); }
      link.focus();
    }
    this._update();
  }

  private async _cancel(): Promise<void> {
    ++this._epoch; this._clearChallenge();
    try {
      if (this._runtime && ['running', 'cancelling'].includes(this._runtime.job.state)) {
        this._runtime = await this._request<RuntimeStatus>('/api/agent-runtime/cancel', {});
      } else { this._auth = await this._request<AuthStatus>('/api/agent-auth/cancel', {}); this._ownsLogin = false; }
      this._update();
      if (!this._primary.disabled) this._primary.focus();
    } catch { this._message('Cancellation could not be confirmed. Refresh status before retrying.'); }
  }

  private async _switchApi(): Promise<void> {
    ++this._epoch; this._clearChallenge();
    if (this._ownsLogin || ['running', 'cancelling'].includes(this._runtime?.job.state || '')) await this._cancel();
    try {
      const settings = await this._request<{ ai_mode: string; agent_mode: unknown; billing: unknown }>('/api/agent-mode', { mode: 'api_byok' });
      agentModeStore.receive({ aiMode: settings.ai_mode, agent: settings.agent_mode, billing: settings.billing });
      this._publish(); this._message('API / BYOK selected. Existing provider settings are unchanged.');
      window.dispatchEvent(new CustomEvent('xace:focus-prompt'));
    } catch { this._message('Could not switch modes. Open model / API settings to retry.'); }
  }

  private async _refresh(account: boolean): Promise<void> {
    this._runtime = await this._request<RuntimeStatus>('/api/agent-runtime');
    this._auth = await this._request<AuthStatus>(account ? '/api/agent-auth/refresh' : '/api/agent-auth', account ? {} : undefined);
    this._update(); if (account) this._publish();
  }

  private async _poll(): Promise<void> {
    if (this._busy || this._polling || this._disposed) return;
    this._polling = true;
    try {
      const previousJob = this._runtime?.job.state, previousAuth = JSON.stringify(this._auth);
      this._auth = await this._request<AuthStatus>('/api/agent-auth');
      if (this._runtime && ['running', 'cancelling'].includes(this._runtime.job.state)) {
        this._runtime = await this._request<RuntimeStatus>('/api/agent-runtime');
      }
      if (this._auth.login_state !== 'pending') { this._ownsLogin = false; this._clearChallenge(); }
      if (previousJob !== this._runtime?.job.state || previousAuth !== JSON.stringify(this._auth)) {
        this._update(); this._publish();
      }
    } catch { if (!this._disposed) this._message('Setup status is unavailable. Refresh to retry or use API / BYOK.'); }
    finally { this._polling = false; }
  }

  private _update(): void {
    if (this._disposed) return;
    const runtime = this._runtime?.runtime, job = this._runtime?.job, auth = this._auth;
    const isolated = runtime?.setup_mode === 'isolated_backend';
    for (const control of this._nativeControls) control.hidden = isolated;
    this._archiveControls.hidden = !isolated;
    this._buildButton.disabled = ['running', 'cancelling'].includes(job?.state || '');
    this._runtimeText.textContent = isolated ? runtime?.message || 'Check isolated execution backend setup.' : runtime?.active
      ? `Runtime ${runtime.active.version}: ${runtime.ready ? 'verified' : runtime.active_health?.code}. Source: user-confirmed official installation; not vendor-signature certification.`
      : 'No verified runtime selected.';
    if (this._runtime?.override_active) this._runtimeText.textContent += ' A developer environment override takes precedence; clear it outside Builder to use this selection.';
    this._accountText.textContent = `Account: ${auth?.state || 'unknown'} ${auth?.account?.email || ''} ${auth?.account?.plan_type || ''}. ` +
      (auth?.limits?.primary ? `Provider usage: ${auth.limits.primary.usedPercent ?? 'unknown'}%. Reset: ${auth.limits.primary.resetsAt ? new Date(auth.limits.primary.resetsAt * 1000).toLocaleString() : 'unknown'}.` : 'Limits: not reported.');
    this._primary.textContent = !runtime?.ready ? isolated ? 'Recheck execution backend' : 'Verify and configure runtime' : auth?.state === 'signed_in' ? 'Use Codex and focus prompt' : !auth || auth.state === 'unknown' ? 'Check account' : 'Sign in to Codex';
    this._primary.disabled = job?.state === 'running' || job?.state === 'cancelling' || auth?.login_state === 'pending';
    this._cancelButton.disabled = !this._busy && !['running', 'cancelling'].includes(job?.state || '') && auth?.login_state !== 'pending';
    const code = job?.error_code || auth?.error_code || (runtime && !runtime.ready ? runtime.active_health?.code : '') || (auth?.limits?.limit_reached ? 'rate_limited' : '');
    this._message(job?.state === 'running' ? 'Verifying runtime… Cancellation stops activation, not an already completed change.'
      : job?.state === 'cancelling' ? 'Cancelling before activation… wait for verification to finish.'
      : code ? HELP[code] || 'Setup needs attention. Refresh, inspect diagnostics, or switch to API / BYOK.'
      : runtime?.state_error ? 'Runtime metadata needs attention. Recover interrupted setup or choose API / BYOK.'
      : auth?.login_state === 'pending' ? 'Complete provider sign-in using the secure link below, or cancel.'
      : runtime?.ready && auth?.state === 'signed_in' ? 'Ready to enable Agent Mode. Model availability is checked by Codex.'
      : 'Configure an official runtime and check sign-in. API / BYOK remains available.');
    if (isolated && !runtime?.ready) this._message(runtime?.message || 'Execution backend unavailable. API / BYOK remains available.');
    this._diagnostics.textContent = JSON.stringify({
      schema: 'xace.agent_setup_diagnostics.v1', runtime_ready: runtime?.ready ?? false,
      version: runtime?.active?.version ?? null, runtime_health: runtime?.active_health?.code,
      operation: job?.operation, operation_state: job?.state, error_code: code || null,
      auth_state: auth?.state, login_state: auth?.login_state, override_active: this._runtime?.override_active,
    }, null, 2);
  }
  private _publish(): void { window.dispatchEvent(new CustomEvent('xace:refresh-provider-settings')); }
  private _clearChallenge(): void {
    const focused = this._challenge?.contains(document.activeElement);
    this._challenge?.replaceChildren();
    if (focused && !this._disposed) this._primary.focus();
  }
  private _message(text: string): void { if (!this._disposed && this._summary.textContent !== text) this._summary.textContent = text; }
  private _actions(): HTMLElement { const el = document.createElement('div'); el.className = 'xb-agent-setup-actions'; this._root.append(el); return el; }
  private _button(parent: HTMLElement, label: string, action: () => void): HTMLButtonElement {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', action); parent.append(button); return button;
  }
  private _label(text: string, input: HTMLInputElement): void {
    const label = document.createElement('label'); label.textContent = text;
    label.htmlFor = input.id; this._root.append(label, input);
  }
  private _checkbox(text: string): HTMLInputElement {
    const input = document.createElement('input'); input.type = 'checkbox';
    const label = document.createElement('label'); label.append(input, document.createTextNode(text));
    this._root.append(label); return input;
  }
}
