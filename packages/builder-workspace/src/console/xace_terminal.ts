/**
 * xace_terminal.ts — XACE Embedded Terminal
 *
 * A proper terminal panel built on xterm.js (loaded from cdnjs).
 * Opens as a draggable panel over the builder or in a bottom drawer.
 *
 * Purpose: run Ollama commands (ollama pull, ollama list, ollama serve)
 * and general shell commands for local dev without leaving the builder.
 *
 * Architecture:
 *   Browser ← WebSocket → /ws/terminal/{session_id} → bash subprocess
 *   builder_server.py handles the /ws/terminal endpoint (add_terminal_endpoint())
 *
 * Features:
 *   - Full xterm.js terminal (256 colour, unicode, resize)
 *   - Quick-command buttons: ollama list, ollama serve, ollama pull <model>
 *   - Connection status indicator
 *   - Resizable height by dragging the top edge
 *   - Keyboard shortcut: Ctrl+` to toggle
 */

declare const Terminal: any;   // xterm.js global from CDN
declare const FitAddon: any;   // xterm-addon-fit

const TERMINAL_STYLES = `
.xb-term-overlay {
  position:     fixed;
  left:         0; right: 0; bottom: 0;
  z-index:      700;
  display:      flex;
  flex-direction: column;
  background:   rgba(4,6,14,.97);
  border-top:   1px solid rgba(0,212,255,.2);
  min-height:   160px;
  max-height:   70vh;
  animation:    fade-in 150ms ease-out;
  box-shadow:   0 -8px 40px rgba(0,0,0,.6);
}
.xb-term-drag {
  height:       6px;
  cursor:       row-resize;
  background:   transparent;
  display:      flex;
  align-items:  center;
  justify-content: center;
  flex-shrink:  0;
}
.xb-term-drag:hover { background: rgba(0,212,255,.06); }
.xb-term-drag-pip {
  width:         36px; height: 2px;
  background:    rgba(0,212,255,.25);
  border-radius: 2px;
}
.xb-term-head {
  display:      flex;
  align-items:  center;
  gap:          8px;
  padding:      4px 12px;
  border-bottom: 1px solid rgba(255,255,255,.06);
  flex-shrink:  0;
}
.xb-term-title {
  font-size:    9px;
  font-weight:  700;
  letter-spacing: .12em;
  text-transform: uppercase;
  color:        rgba(0,212,255,.7);
}
.xb-term-status {
  font-size:    9px;
  font-family:  var(--font-mono);
  color:        rgba(255,255,255,.2);
  display:      flex;
  align-items:  center;
  gap:          4px;
}
.xb-term-status-dot {
  width:   5px; height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.xb-term-status-dot.connected    { background: #00d4ff; box-shadow: 0 0 6px #00d4ff; }
.xb-term-status-dot.disconnected { background: rgba(239,68,68,.7); }
.xb-term-status-dot.connecting   { background: #f59e0b; animation: pulse-dot 1s ease-in-out infinite; color: #f59e0b; }
.xb-term-cmds {
  display:  flex;
  gap:      4px;
  flex-wrap: wrap;
  margin-left: 8px;
}
.xb-term-cmd {
  font-size:    8.5px;
  padding:      2px 7px;
  border:       1px solid rgba(255,255,255,.1);
  border-radius: 3px;
  color:        rgba(255,255,255,.4);
  cursor:       pointer;
  font-family:  var(--font-mono);
  background:   transparent;
  transition:   all 100ms;
  white-space:  nowrap;
}
.xb-term-cmd:hover { border-color: rgba(0,212,255,.3); color: rgba(0,212,255,.8); background: rgba(0,212,255,.04); }
.xb-term-close {
  margin-left:  auto;
  background:   none;
  border:       none;
  color:        rgba(255,255,255,.2);
  font-size:    14px;
  cursor:       pointer;
  transition:   color 100ms;
  line-height:  1;
}
.xb-term-close:hover { color: rgba(255,255,255,.7); }
.xb-term-body {
  flex:         1;
  overflow:     hidden;
  padding:      4px 0 0;
}
/* xterm.js overrides for dark XACE theme */
.xb-term-body .xterm { height: 100%; }
.xb-term-body .xterm-viewport { overflow-y: hidden !important; }
`;

const QUICK_COMMANDS = [
  { label: 'ollama list',         cmd: 'ollama list\n' },
  { label: 'ollama serve',        cmd: 'ollama serve\n' },
  { label: 'pull llama3.2',       cmd: 'ollama pull llama3.2\n' },
  { label: 'pull llama3.1',       cmd: 'ollama pull llama3.1\n' },
  { label: 'clear',               cmd: 'clear\n' },
];

export class XaceTerminal {
  private _overlay:  HTMLElement | null = null;
  private _terminal: any  = null;    // xterm.js Terminal instance
  private _fitAddon: any  = null;
  private _ws:       WebSocket | null = null;
  private _visible:  boolean = false;
  private _wsUrl:    string;
  private _startH:   number = 280;
  private _dragging: boolean = false;
  private _dragStartY: number = 0;
  private _dragStartH: number = 0;
  private _statusDot: HTMLElement | null = null;
  private _statusText: HTMLElement | null = null;
  private _fallbackOut: HTMLElement | null = null;

  constructor(wsBaseUrl = '') {
    this._wsUrl = wsBaseUrl;
    this._injectStyles();

    // Ctrl+` keyboard shortcut
    document.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '`') {
        e.preventDefault();
        this._visible ? this.hide() : this.show();
      }
    });
  }

  show(): void {
    if (this._visible) return;
    this._visible  = true;
    this._overlay  = this._build();
    document.body.appendChild(this._overlay);
    this._loadXterm().then(
      () => this._initTerminal(),
      () => this._initFallback('xterm.js unavailable; using basic terminal.'),
    ).finally(() => {
      this._connect();
    });
  }

  hide(): void {
    if (!this._visible) return;
    this._visible = false;
    this._ws?.close();
    this._ws = null;
    this._terminal?.dispose();
    this._terminal = null;
    this._fallbackOut = null;
    this._overlay?.remove();
    this._overlay = null;
  }

  toggle(): void {
    this._visible ? this.hide() : this.show();
  }

  private _build(): HTMLElement {
    const overlay = document.createElement('div');
    overlay.className = 'xb-term-overlay';
    overlay.style.height = `${this._startH}px`;

    // ── Drag handle ──────────────────────────────────────────────────────
    const drag = document.createElement('div');
    drag.className = 'xb-term-drag';
    drag.innerHTML = `<div class="xb-term-drag-pip"></div>`;
    drag.addEventListener('mousedown', (e) => this._startDrag(e, overlay));
    overlay.appendChild(drag);

    // ── Header ────────────────────────────────────────────────────────────
    const head = document.createElement('div');
    head.className = 'xb-term-head';

    const title = document.createElement('span');
    title.className   = 'xb-term-title';
    title.textContent = 'Terminal';
    head.appendChild(title);

    // Status
    const status = document.createElement('div');
    status.className = 'xb-term-status';
    const dot = document.createElement('div');
    dot.className = 'xb-term-status-dot connecting';
    const txt = document.createElement('span');
    txt.textContent = 'connecting…';
    status.appendChild(dot);
    status.appendChild(txt);
    head.appendChild(status);
    this._statusDot  = dot;
    this._statusText = txt;

    // Quick commands
    const cmds = document.createElement('div');
    cmds.className = 'xb-term-cmds';
    for (const qc of QUICK_COMMANDS) {
      const btn = document.createElement('button');
      btn.className   = 'xb-term-cmd';
      btn.textContent = qc.label;
      btn.addEventListener('click', () => this._send(qc.cmd));
      cmds.appendChild(btn);
    }
    head.appendChild(cmds);

    // Close
    const close = document.createElement('button');
    close.className   = 'xb-term-close';
    close.textContent = '✕';
    close.title       = 'Close (Ctrl+`)';
    close.addEventListener('click', () => this.hide());
    head.appendChild(close);

    overlay.appendChild(head);

    // ── Terminal body ──────────────────────────────────────────────────────
    const body = document.createElement('div');
    body.className = 'xb-term-body';
    body.id        = 'xb-term-body';
    overlay.appendChild(body);

    return overlay;
  }

  // ── xterm.js loading ──────────────────────────────────────────────────────

  private async _loadXterm(): Promise<void> {
    if (typeof Terminal !== 'undefined') return;

    // Load xterm.js + FitAddon from CDN
    await Promise.all([
      _loadScript('https://cdnjs.cloudflare.com/ajax/libs/xterm/5.3.0/xterm.min.js'),
      _loadCSS('https://cdnjs.cloudflare.com/ajax/libs/xterm/5.3.0/xterm.min.css'),
    ]);
    await _loadScript('https://cdnjs.cloudflare.com/ajax/libs/xterm/5.3.0/addon-fit.min.js');
  }

  private _initTerminal(): void {
    if (typeof Terminal === 'undefined') {
      this._initFallback('xterm.js unavailable; using basic terminal.');
      return;
    }

    this._terminal = new Terminal({
      theme: {
        background:  '#04060e',
        foreground:  '#c8d3f5',
        cursor:      '#00d4ff',
        cursorAccent:'#04060e',
        black:       '#1b1d2b',
        red:         '#ff757f',
        green:       '#c3e88d',
        yellow:      '#ffc777',
        blue:        '#82aaff',
        magenta:     '#c099ff',
        cyan:        '#86e1fc',
        white:       '#c8d3f5',
        brightBlack: '#444a73',
        brightCyan:  '#00d4ff',
      },
      fontFamily: '"JetBrains Mono", "Cascadia Code", "Fira Code", monospace',
      fontSize:   12,
      lineHeight: 1.4,
      cursorBlink: true,
      allowTransparency: true,
      scrollback: 2000,
    });

    try {
      this._fitAddon = new (FitAddon as any).FitAddon();
      this._terminal.loadAddon(this._fitAddon);
    } catch {
      // FitAddon may not be available — continue without resize
    }

    const container = document.getElementById('xb-term-body');
    if (container) {
      this._terminal.open(container);
      try { this._fitAddon?.fit(); } catch { /* */ }
    }

    // Forward keystrokes to server
    this._terminal.onData((data: string) => {
      this._send(data);
    });

    // Handle window resize
    window.addEventListener('resize', () => {
      try { this._fitAddon?.fit(); } catch { /* */ }
    });
  }

  // ── WebSocket shell ───────────────────────────────────────────────────────

  private _connect(): void {
    const sessionId = 'terminal-' + Math.random().toString(36).slice(2, 8);
    const url       = `${this._terminalBaseUrl()}/ws/terminal/${sessionId}`;

    this._setStatus('connecting', 'connecting…');

    try {
      this._ws = new WebSocket(url);
    } catch (e) {
      this._setStatus('disconnected', 'unavailable');
      this._writeLocal('\r\n\x1b[33m⚠ Terminal WebSocket not available.\x1b[0m\r\n');
      this._writeLocal('\x1b[2mThe shell backend requires builder_server.py to be running.\x1b[0m\r\n');
      this._writeLocal('\r\n\x1b[36mYou can still use the quick-command buttons above.\x1b[0m\r\n');
      return;
    }

    this._ws.onopen = () => {
      this._setStatus('connected', 'bash');
      this._writeLocal('\x1b[36m── XACE Terminal ──────────────────────────────────\x1b[0m\r\n');
      this._writeLocal('\x1b[2mCtrl+` to toggle · Quick commands in the toolbar above\x1b[0m\r\n\r\n');
    };

    this._ws.onmessage = (event: MessageEvent) => {
      if (this._terminal) {
        this._terminal.write(event.data);
      } else {
        this._writeLocal(event.data);
      }
    };

    this._ws.onclose = () => {
      this._setStatus('disconnected', 'disconnected');
      this._writeLocal('\r\n\x1b[31m[connection closed]\x1b[0m\r\n');
    };

    this._ws.onerror = () => {
      this._setStatus('disconnected', 'error');
      this._writeLocal('\r\n\x1b[31m[connection error — is builder_server.py running?]\x1b[0m\r\n');
      this._writeLocal('\x1b[2mStart with: python builder_server.py --project ./project --dev\x1b[0m\r\n');
    };
  }

  private _send(data: string): void {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(data);
    } else {
      // No connection — echo locally for quick command feedback
      this._writeLocal('\r\n\x1b[33m[not connected — start builder_server.py]\x1b[0m\r\n');
    }
  }

  private _writeLocal(text: string): void {
    if (this._terminal) {
      this._terminal.write(text);
      return;
    }
    if (this._fallbackOut) {
      const plain = text.replace(/\x1b\[[0-9;]*m/g, '');
      this._fallbackOut.textContent += plain;
      this._fallbackOut.scrollTop = this._fallbackOut.scrollHeight;
    }
  }

  private _initFallback(message: string): void {
    const body = document.getElementById('xb-term-body');
    if (!body) return;

    body.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.style.cssText = 'height:100%;display:flex;flex-direction:column;font-family:var(--font-mono);font-size:11px';

    const out = document.createElement('div');
    out.style.cssText = 'flex:1;overflow:auto;white-space:pre-wrap;padding:8px 10px;color:#c8d3f5;background:#04060e';
    out.textContent = `${message}\n`;
    this._fallbackOut = out;

    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'type a command and press Enter';
    input.style.cssText = 'border:0;border-top:1px solid rgba(255,255,255,.1);outline:none;background:#070a14;color:#c8d3f5;padding:7px 10px;font-family:inherit;font-size:11px';
    input.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key !== 'Enter') return;
      const cmd = input.value;
      input.value = '';
      this._writeLocal(`> ${cmd}\n`);
      this._send(`${cmd}\n`);
    });

    wrap.appendChild(out);
    wrap.appendChild(input);
    body.appendChild(wrap);
    setTimeout(() => input.focus(), 20);
  }

  private _terminalBaseUrl(): string {
    const configured = this._wsUrl || _defaultWsUrl();
    return configured.replace(/\/ws\/?$/, '').replace(/\/$/, '');
  }

  // ── Drag resize ───────────────────────────────────────────────────────────

  private _startDrag(e: MouseEvent, overlay: HTMLElement): void {
    this._dragging   = true;
    this._dragStartY = e.clientY;
    this._dragStartH = overlay.offsetHeight;

    const onMove = (ev: MouseEvent) => {
      if (!this._dragging) return;
      const delta   = this._dragStartY - ev.clientY;
      const newH    = Math.min(Math.max(120, this._dragStartH + delta), window.innerHeight * 0.8);
      overlay.style.height = `${newH}px`;
      try { this._fitAddon?.fit(); } catch { /* */ }
    };

    const onUp = () => {
      this._dragging = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    e.preventDefault();
  }

  // ── Status ────────────────────────────────────────────────────────────────

  private _setStatus(state: 'connected' | 'disconnected' | 'connecting', label: string): void {
    if (this._statusDot) {
      this._statusDot.className = `xb-term-status-dot ${state}`;
    }
    if (this._statusText) {
      this._statusText.textContent = label;
    }
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-term-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-term-styles'; s.textContent = TERMINAL_STYLES;
    document.head.appendChild(s);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const s   = document.createElement('script');
    s.src     = src;
    s.onload  = () => resolve();
    s.onerror = () => reject(new Error(`Failed to load: ${src}`));
    document.head.appendChild(s);
  });
}

function _loadCSS(href: string): Promise<void> {
  return new Promise((resolve) => {
    if (document.querySelector(`link[href="${href}"]`)) { resolve(); return; }
    const l   = document.createElement('link');
    l.rel     = 'stylesheet';
    l.href    = href;
    l.onload  = () => resolve();
    document.head.appendChild(l);
  });
}

function _defaultWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}`;
}
