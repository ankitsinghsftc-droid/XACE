// Real DOM smoke; generated output and a disposable browser profile only.
import { build } from 'esbuild';
import { mkdtempSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
const binary = process.env.XACE_TEST_BROWSER || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].find(existsSync);
if (!binary) throw new Error('Set XACE_TEST_BROWSER to a Chromium binary; this test does not install one.');
const folder = mkdtempSync(join(tmpdir(), 'xace-agent-ui-'));
try {
  await build({ entryPoints: [resolve('tools/agent_setup_browser_fixture.ts')], bundle: true,
    outfile: join(folder, 'fixture.js'), format: 'esm', target: 'chrome120' });
  writeFileSync(join(folder, 'index.html'), '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script type="module" src="fixture.js"></script></body></html>');
  const output = execFileSync(binary, ['--headless', '--disable-gpu', '--no-first-run',
    '--allow-file-access-from-files', '--force-prefers-reduced-motion', '--window-size=360,740',
    '--virtual-time-budget=6000', '--dump-dom', `--user-data-dir=${join(folder, 'profile')}`,
    pathToFileURL(join(folder, 'index.html')).href], { encoding: 'utf8', timeout: 45000, stdio: ['ignore', 'pipe', 'pipe'] });
  if (!output.includes('data-test-state="passed"')) throw new Error(output);
  console.log('AG-026/028 real-browser setup, support preview/export consent, cancellation, prompt/fallback, focus, narrow layout and reduced-motion checks passed.');
} finally { rmSync(folder, { recursive: true, force: true, maxRetries: 4, retryDelay: 200 }); }
