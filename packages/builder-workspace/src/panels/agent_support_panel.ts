/** Local, opt-in, content-free support export; never a chat-history export. */
interface SupportPreview { preview_id: string; sha256: string; content: string; expires_in_seconds: number }

export class AgentSupportPanel {
  private _root!: HTMLElement;
  private _output!: HTMLPreElement;
  private _status!: HTMLElement;
  private _collect!: HTMLInputElement;
  private _reviewed!: HTMLInputElement;
  private _download!: HTMLButtonElement;
  private _preview: SupportPreview | null = null;
  private _abort = new AbortController();
  private _busy = false;
  private _disposed = false;
  private _expiry: ReturnType<typeof setTimeout> | null = null;

  mount(container: HTMLElement): void {
    const root = document.createElement('details'); this._root = root;
    const title = document.createElement('summary'); title.textContent = 'Agent privacy and support';
    const note = document.createElement('p');
    note.textContent = 'Includes versions, schema fingerprint and diagnostic states only. Excludes prompts, project content, chat, proposals, logs, credentials and account identity. No automatic upload. Preview expires after five minutes; downloaded files remain yours to delete.';
    this._status = document.createElement('p'); this._status.setAttribute('role', 'status'); this._status.setAttribute('aria-live', 'polite');
    root.append(title, note, this._status);
    this._button('View local diagnostics', async () => {
      const response = await this._request('diagnostics');
      const diagnostics = await response.json();
      if (this._disposed) return;
      this._invalidate(); this._output.textContent = JSON.stringify(diagnostics, null, 2);
      this._status.textContent = 'Local diagnostic snapshot only. No bundle prepared or uploaded.';
    });
    this._collect = this._checkbox('I consent to preparing a content-free Agent support preview.');
    this._button('Prepare support preview', async () => {
      if (!this._collect.checked) { this._status.textContent = 'Confirm collection first.'; this._collect.focus(); return; }
      this._invalidate();
      const response = await this._request('preview', { confirm: true });
      const preview = await response.json() as SupportPreview;
      if (this._disposed) return;
      if (typeof preview.content !== 'string' || preview.content.length > 16384) throw new Error('invalid preview');
      this._preview = preview; this._output.textContent = preview.content;
      this._download.disabled = false; this._collect.checked = false;
      this._status.textContent = 'Inspect the complete JSON below, then confirm download. Nothing has been uploaded.';
      this._output.focus();
      this._expiry = setTimeout(() => {
        this._invalidate(); this._output.textContent = ''; this._status.textContent = 'Preview expired. Prepare a new preview to download.';
      }, 300000);
    });
    this._output = document.createElement('pre'); this._output.tabIndex = 0;
    this._output.setAttribute('aria-label', 'Complete Agent support preview');
    this._output.style.maxHeight = '300px'; this._output.style.overflow = 'auto';
    root.append(this._output);
    this._reviewed = this._checkbox('I reviewed this preview and consent to downloading exactly these diagnostics.');
    this._download = this._button('Download reviewed support bundle', async () => {
      const preview = this._preview;
      if (!preview || !this._reviewed.checked) { this._status.textContent = 'Review the preview and confirm download first.'; this._reviewed.focus(); return; }
      const response = await this._request('export', { confirm: true, preview_id: preview.preview_id, sha256: preview.sha256 });
      const content = await response.text();
      if (this._disposed) return;
      if (content !== preview.content) { this._invalidate(); throw new Error('changed preview'); }
      const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = 'xace-agent-support.json';
      this._root.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      this._invalidate(); this._output.textContent = '';
      this._status.textContent = 'Reviewed bundle downloaded locally. Share it only through a trusted support channel; XACE did not upload it.';
    });
    this._download.disabled = true;
    this._button('Clear local support previews', async () => {
      await this._request('clear', { confirm: true }); this._invalidate(); this._output.textContent = '';
      this._status.textContent = 'Local support previews cleared. Downloads and chat history were not deleted.';
    });
    container.append(root);
  }

  unmount(): void { this._disposed = true; this._abort.abort(); this._invalidate(); this._root.remove(); }

  private _invalidate(): void {
    if (this._expiry) clearTimeout(this._expiry);
    this._expiry = null; this._preview = null;
    if (this._output) this._output.textContent = '';
    if (this._reviewed) this._reviewed.checked = false;
    if (this._download) this._download.disabled = true;
  }

  private async _request(action: string, body?: unknown): Promise<Response> {
    const response = await fetch(`/api/agent-support/${action}`, { method: body === undefined ? 'GET' : 'POST',
      body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', signal: this._abort.signal,
      headers: { 'Content-Type': 'application/json', 'X-XACE-Agent-Auth': '1' } });
    if (!response.ok || this._disposed) throw new Error('support request failed');
    return response;
  }

  private _button(label: string, action: () => Promise<void>): HTMLButtonElement {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', () => {
      if (this._busy || this._disposed) return;
      this._busy = true; this._root.setAttribute('aria-busy', 'true');
      void action().catch(() => {
        if (!this._disposed) this._status.textContent = 'Support action failed or preview expired. Prepare a fresh preview and retry. Nothing was uploaded.';
      }).finally(() => { this._busy = false; this._root.setAttribute('aria-busy', 'false'); });
    });
    this._root.append(button); return button;
  }
  private _checkbox(text: string): HTMLInputElement {
    const input = document.createElement('input'); input.type = 'checkbox';
    const label = document.createElement('label'); label.append(input, document.createTextNode(text));
    this._root.append(label); return input;
  }
}
