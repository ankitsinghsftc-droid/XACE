/**
 * app.ts — XACE Builder root application shell
 *
 * Initialisation sequence:
 *   1. Start loading splash
 *   2. Import state stores (synchronous)
 *   3. Create BuilderClient and connect to builder_server
 *   4. Mount MainLayout into #app
 *   5. Mount BottomBar
 *   6. Once session_init received → hide splash
 *
 * This file is the only place that wires together the top-level
 * dependencies. Components receive their dependencies via constructor
 * params, not by importing singletons directly — except for the three
 * stores (consoleSM, cgsStore, uiStore) which are module-level singletons.
 */

import { initBuilderClient }   from './api/builder_client';
import { consoleSM }           from './state/console_state_machine';
import { cgsStore }            from './state/cgs_store';
import { uiStore }             from './state/ui_store';
import { MainLayout }          from './layout/main_layout';
import { BottomBar }           from './layout/bottom_bar';

// ── Environment ───────────────────────────────────────────────────────────────

const WS_URL     = import.meta.env.VITE_WS_URL     ?? 'ws://localhost:8765/ws';
const PROJECT_ID = import.meta.env.VITE_PROJECT_ID ?? 'default';

// ── Splash progress ───────────────────────────────────────────────────────────

function setSplashProgress(pct: number): void {
  const bar = document.getElementById('splash-bar');
  if (bar) bar.style.width = `${pct}%`;
}

function hideSplash(): void {
  const splash = document.getElementById('splash');
  if (!splash) return;
  splash.classList.add('hidden');
  setTimeout(() => splash.remove(), 350);
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────

async function boot(): Promise<void> {
  setSplashProgress(15);

  // ── Create WebSocket client ───────────────────────────────────────────────
  const client = initBuilderClient({
    url:          WS_URL,
    projectPath:  PROJECT_ID,
    reconnectBase: 1000,
    reconnectMax:  30_000,
    pingInterval:  20_000,
  });

  setSplashProgress(35);

  // ── Mount layout ──────────────────────────────────────────────────────────
  const appEl = document.getElementById('app');
  if (!appEl) {
    console.error('[boot] #app element not found — check index.html');
    return;
  }

  const layout = new MainLayout({ client, consoleSM, cgsStore, uiStore });
  layout.mount(appEl);

  setSplashProgress(60);

  // ── Mount bottom bar ──────────────────────────────────────────────────────
  // BottomBar lives outside the workspace flex container so it always
  // sticks to the viewport bottom.
  const bottomEl = document.createElement('div');
  bottomEl.id = 'bottom-bar-root';
  document.body.appendChild(bottomEl);

  const bottomBar = new BottomBar({ cgsStore, uiStore, client });
  bottomBar.mount(bottomEl);

  setSplashProgress(80);

  // ── Wire all components into layout slots ──────────────────────────────
  const { BuilderCanvas } = await import("./canvas/builder_canvas");
  const canvas = new BuilderCanvas({ layout, client, consoleSM, cgsStore, uiStore });
  canvas.mount();

  // ── Mount terminal (Ctrl+` to toggle) ────────────────────────────────────
  const { XaceTerminal } = await import('./console/xace_terminal');
  const terminal = new XaceTerminal(WS_URL);

  // Add terminal toggle button to the bottom bar area
  const termBtn = document.createElement('button');
  termBtn.style.cssText = `
    position: fixed; bottom: 44px; right: 12px; z-index: 300;
    background: rgba(4,6,14,.9); border: 1px solid rgba(0,212,255,.2);
    border-radius: 5px; color: rgba(0,212,255,.6); font-size: 11px;
    padding: 4px 10px; cursor: pointer; font-family: monospace;
    transition: all 120ms; backdrop-filter: blur(6px);
    display: flex; align-items: center; gap: 5px;
  `;
  termBtn.innerHTML = `<span style="font-size:9px;opacity:.6">Ctrl+\`</span> Terminal`;
  termBtn.addEventListener('mouseenter', () => {
    termBtn.style.borderColor = 'rgba(0,212,255,.5)';
    termBtn.style.color = 'var(--cyan)';
  });
  termBtn.addEventListener('mouseleave', () => {
    termBtn.style.borderColor = 'rgba(0,212,255,.2)';
    termBtn.style.color = 'rgba(0,212,255,.6)';
  });
  termBtn.addEventListener('click', () => terminal.toggle());
  document.body.appendChild(termBtn);

  // ── Connect WebSocket ─────────────────────────────────────────────────────
  // Listen for session_init (means server is up and CGS is loaded)
  const unsub = cgsStore.select(
    s => s.isLoading,
    (isLoading) => {
      if (!isLoading) {
        setSplashProgress(100);
        setTimeout(hideSplash, 200);
        unsub();
      }
    },
  );

  // Timeout — hide splash even if server is slow
  setTimeout(() => hideSplash(), 8000);

  client.connect();

  setSplashProgress(90);

  // ── Global error boundary ─────────────────────────────────────────────────
  window.addEventListener('unhandledrejection', (ev) => {
    console.error('[app] Unhandled promise rejection:', ev.reason);
  });

  window.addEventListener('error', (ev) => {
    console.error('[app] Uncaught error:', ev.error);
  });

  // ── Dev-mode extras ───────────────────────────────────────────────────────
  if (import.meta.env.DEV) {
    // Expose stores to browser console for debugging
    Object.assign(window, { __xace: { consoleSM, cgsStore, uiStore, client } });
    console.info(
      '%cXACE Builder (dev mode)',
      'color:#00d4ff;font-weight:600;font-size:13px',
      '\nAccess internals via window.__xace',
    );
  }
}

// ── Start ─────────────────────────────────────────────────────────────────────

boot().catch(err => {
  console.error('[boot] Fatal error:', err);
  const splash = document.getElementById('splash');
  if (splash) {
    splash.innerHTML = `
      <div style="color:#ef4444;font-family:monospace;font-size:13px;text-align:center;padding:20px">
        <div style="font-size:24px;margin-bottom:8px">⚠</div>
        <div>XACE Builder failed to start</div>
        <div style="color:#5a6880;margin-top:6px;font-size:11px">${String(err)}</div>
        <div style="margin-top:12px">
          <a href="/" style="color:#00d4ff">Reload</a>
        </div>
      </div>
    `;
  }
});
