/**
 * XACE embedded terminal.
 *
 * The terminal connects to the builder server terminal WebSocket. It keeps a
 * small browser-native terminal surface so the builder can run without extra
 * CDN assets or runtime package dependencies.
 */

const MAX_OUTPUT_CHARS = 120_000;

const TERMINAL_STYLES = `
.xb-term-overlay { position: fixed; left: 0; right: 0; bottom: 0; z-index: 700; display: flex; flex-direction: column; background: rgba(4,6,14,.97); border-top: 1px solid rgba(0,212,255,.2); min-height: 160px; max-height: 78vh; animation: fade-in 150ms ease-out; box-shadow: 0 -8px 40px rgba(0,0,0,.6); }
.xb-term-drag { height: 6px; cursor: row-resize; background: transparent; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.xb-term-drag:hover { background: rgba(0,212,255,.06); }
.xb-term-drag-pip { width: 36px; height: 2px; background: rgba(0,212,255,.25); border-radius: 2px; }
.xb-term-head { display: flex; align-items: center; gap: 8px; padding: 4px 12px; border-bottom: 1px solid rgba(255,255,255,.06); flex-shrink: 0; min-width: 0; }
.xb-term-title { font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: rgba(0,212,255,.7); white-space: nowrap; }
.xb-term-status { font-size: 9px; font-family: var(--font-mono); color: rgba(255,255,255,.34); display: flex; align-items: center; gap: 4px; white-space: nowrap; }
.xb-term-status-dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
.xb-term-status-dot.connected { background: #00d4ff; box-shadow: 0 0 6px #00d4ff; }
.xb-term-status-dot.disconnected { background: rgba(239,68,68,.7); }
.xb-term-status-dot.connecting { background: #f59e0b; animation: pulse-dot 1s ease-in-out infinite; }
.xb-term-cmds { display: flex; gap: 4px; flex-wrap: wrap; margin-left: 8px; min-width: 0; overflow: hidden; }
.xb-term-cmd { font-size: 8.5px; padding: 2px 7px; border: 1px solid rgba(255,255,255,.1); border-radius: 3px; color: rgba(255,255,255,.48); cursor: pointer; font-family: var(--font-mono); background: transparent; transition: all 100ms; white-space: nowrap; }
.xb-term-cmd:hover { border-color: rgba(0,212,255,.3); color: rgba(0,212,255,.8); background: rgba(0,212,255,.04); }
.xb-term-close { margin-left: auto; background: none; border: none; color: rgba(255,255,255,.32); font-size: 14px; cursor: pointer; transition: color 100ms; line-height: 1; flex-shrink: 0; }
.xb-term-close:hover { color: rgba(255,255,255,.78); }
.xb-term-body { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #04060e; font-family: var(--font-mono); font-size: 11px; }
.xb-term-output { flex: 1; min-height: 0; overflow: auto; white-space: pre-wrap; word-break: break-word; padding: 8px 10px; color: #c8d3f5; line-height: 1.45; }
.xb-term-input-row { display: flex; align-items: center; gap: 6px; border-top: 1px solid rgba(255,255,255,.08); padding: 6px 8px; background: #070a14; }
.xb-term-prompt { color: #00d4ff; flex-shrink: 0; }
.xb-term-input { flex: 1; min-width: 0; border: 0; outline: none; background: transparent; color: #c8d3f5; font: inherit; caret-color: #00d4ff; }
.xb-term-input::placeholder { color: rgba(200,211,245,.28); }
`;

const QUICK_COMMANDS: Array<{ readonly label: string; readonly command: string }> = [
  { label: 'cargo test', command: 'cargo test' },
  { label: 'ollama list', command: 'ollama list' },
  { label: 'ollama serve', command: 'ollama serve' },
  { label: 'clear', command: 'clear' },
];

type TerminalStatus = 'connected' | 'disconnected' | 'connecting';

export class XaceTerminal {
  private overlay: HTMLElement | null = null;
  private output: HTMLElement | null = null;
  private input: HTMLInputElement | null = null;
  private ws: WebSocket | null = null;
  private readonly wsUrl: string;
  private visible = false;
  private panelHeight = 280;
  private dragging = false;
  private dragStartY = 0;
  private dragStartHeight = 0;
  private statusDot: HTMLElement | null = null;
  private statusText: HTMLElement | null = null;
  private readonly history: string[] = [];
  private historyIndex = 0;

  constructor(wsBaseUrl = '') {
    this.wsUrl = wsBaseUrl;
    injectStyles();
    document.addEventListener('keydown', (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key === '`') {
        event.preventDefault();
        this.toggle();
      }
    });
  }

  show(): void {
    if (this.visible) {
      this.input?.focus();
      return;
    }
    this.visible = true;
    this.overlay = this.build();
    document.body.appendChild(this.overlay);
    this.writeLocal('XACE terminal ready. Connecting to builder server...\n');
    this.connect();
    requestAnimationFrame(() => this.input?.focus());
  }

  hide(): void {
    if (!this.visible) {
      return;
    }
    this.visible = false;
    this.ws?.close(1000, 'terminal hidden');
    this.ws = null;
    this.overlay?.remove();
    this.overlay = null;
    this.output = null;
    this.input = null;
  }

  toggle(): void {
    this.visible ? this.hide() : this.show();
  }

  private build(): HTMLElement {
    const overlay = document.createElement('div');
    overlay.className = 'xb-term-overlay';
    overlay.style.height = `${this.panelHeight}px`;

    const drag = document.createElement('div');
    drag.className = 'xb-term-drag';
    drag.innerHTML = '<div class="xb-term-drag-pip"></div>';
    drag.addEventListener('mousedown', (event) => this.startDrag(event, overlay));
    overlay.appendChild(drag);

    const head = document.createElement('div');
    head.className = 'xb-term-head';

    const title = document.createElement('span');
    title.className = 'xb-term-title';
    title.textContent = 'Terminal';
    head.appendChild(title);

    const status = document.createElement('div');
    status.className = 'xb-term-status';
    this.statusDot = document.createElement('div');
    this.statusDot.className = 'xb-term-status-dot connecting';
    this.statusText = document.createElement('span');
    this.statusText.textContent = 'connecting';
    status.appendChild(this.statusDot);
    status.appendChild(this.statusText);
    head.appendChild(status);

    const cmds = document.createElement('div');
    cmds.className = 'xb-term-cmds';
    for (const quick of QUICK_COMMANDS) {
      const button = document.createElement('button');
      button.className = 'xb-term-cmd';
      button.textContent = quick.label;
      button.addEventListener('click', () => this.submitCommand(quick.command));
      cmds.appendChild(button);
    }
    head.appendChild(cmds);

    const close = document.createElement('button');
    close.className = 'xb-term-close';
    close.textContent = 'x';
    close.title = 'Close (Ctrl+`)';
    close.addEventListener('click', () => this.hide());
    head.appendChild(close);
    overlay.appendChild(head);

    const body = document.createElement('div');
    body.className = 'xb-term-body';
    this.output = document.createElement('div');
    this.output.className = 'xb-term-output';
    body.appendChild(this.output);

    const inputRow = document.createElement('div');
    inputRow.className = 'xb-term-input-row';
    const prompt = document.createElement('span');
    prompt.className = 'xb-term-prompt';
    prompt.textContent = '>';
    this.input = document.createElement('input');
    this.input.className = 'xb-term-input';
    this.input.placeholder = 'type a command and press Enter';
    this.input.autocomplete = 'off';
    this.input.spellcheck = false;
    this.input.addEventListener('keydown', (event) => this.handleInputKey(event));
    inputRow.appendChild(prompt);
    inputRow.appendChild(this.input);
    body.appendChild(inputRow);
    overlay.appendChild(body);

    return overlay;
  }

  private connect(): void {
    const url = `${this.terminalBaseUrl()}/ws/terminal/${createSessionId()}`;
    this.setStatus('connecting', 'connecting');

    try {
      this.ws = new WebSocket(url);
    } catch (error) {
      this.setStatus('disconnected', 'unavailable');
      this.writeLocal(`terminal websocket unavailable: ${String(error)}\n`);
      return;
    }

    this.ws.onopen = () => {
      this.setStatus('connected', 'shell');
      this.writeLocal('connected\n');
    };
    this.ws.onmessage = (event: MessageEvent) => {
      this.writeLocal(String(event.data));
    };
    this.ws.onclose = () => {
      this.setStatus('disconnected', 'disconnected');
      this.writeLocal('\n[connection closed]\n');
    };
    this.ws.onerror = () => {
      this.setStatus('disconnected', 'error');
      this.writeLocal('\n[connection error: is builder_server.py running?]\n');
    };
  }

  private handleInputKey(event: KeyboardEvent): void {
    if (!this.input) {
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const command = this.input.value.trimEnd();
      this.input.value = '';
      this.submitCommand(command);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.recallHistory(-1);
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.recallHistory(1);
    }
  }

  private submitCommand(command: string): void {
    const trimmed = command.trim();
    if (!trimmed) {
      return;
    }
    if (trimmed === 'clear') {
      if (this.output) this.output.textContent = '';
      return;
    }
    this.history.push(trimmed);
    if (this.history.length > 100) {
      this.history.shift();
    }
    this.historyIndex = this.history.length;
    this.writeLocal(`> ${trimmed}\n`);
    this.send(`${trimmed}\n`);
  }

  private send(data: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data);
      return;
    }
    this.writeLocal('[not connected]\n');
  }

  private recallHistory(delta: -1 | 1): void {
    if (!this.input || this.history.length === 0) {
      return;
    }
    this.historyIndex = Math.max(0, Math.min(this.history.length, this.historyIndex + delta));
    this.input.value = this.history[this.historyIndex] ?? '';
    requestAnimationFrame(() => {
      this.input?.setSelectionRange(this.input.value.length, this.input.value.length);
    });
  }

  private writeLocal(text: string): void {
    if (!this.output) {
      return;
    }
    const sanitized = stripAnsi(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    this.output.textContent = trimOutput((this.output.textContent ?? '') + sanitized);
    this.output.scrollTop = this.output.scrollHeight;
  }

  private terminalBaseUrl(): string {
    const configured = this.wsUrl || defaultWsUrl();
    return configured.replace(/\/ws\/?$/, '').replace(/\/$/, '');
  }

  private startDrag(event: MouseEvent, overlay: HTMLElement): void {
    this.dragging = true;
    this.dragStartY = event.clientY;
    this.dragStartHeight = overlay.offsetHeight;

    const onMove = (moveEvent: MouseEvent) => {
      if (!this.dragging) {
        return;
      }
      const delta = this.dragStartY - moveEvent.clientY;
      const nextHeight = Math.min(Math.max(160, this.dragStartHeight + delta), window.innerHeight * 0.78);
      this.panelHeight = nextHeight;
      overlay.style.height = `${nextHeight}px`;
    };

    const onUp = () => {
      this.dragging = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    event.preventDefault();
  }

  private setStatus(state: TerminalStatus, label: string): void {
    if (this.statusDot) {
      this.statusDot.className = `xb-term-status-dot ${state}`;
    }
    if (this.statusText) {
      this.statusText.textContent = label;
    }
  }
}

function injectStyles(): void {
  if (document.getElementById('xb-term-styles')) return;
  const style = document.createElement('style');
  style.id = 'xb-term-styles';
  style.textContent = TERMINAL_STYLES;
  document.head.appendChild(style);
}

function createSessionId(): string {
  const bytes = new Uint8Array(8);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  return `terminal-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

function defaultWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}`;
}

function stripAnsi(value: string): string {
  return value.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '');
}

function trimOutput(value: string): string {
  if (value.length <= MAX_OUTPUT_CHARS) {
    return value;
  }
  return value.slice(value.length - MAX_OUTPUT_CHARS);
}
