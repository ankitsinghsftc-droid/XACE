/**
 * views/processing_view.ts — 5-pass live processing tracker
 *
 * Shows the PIL pipeline passes in real-time as they stream from the server.
 * Each pass: label, tier badge, status indicator, token/cost once done.
 * Mode-adaptive: Guided shows plain descriptions, Architect shows pass IDs.
 */

import type { ConsoleSM }    from '../state/console_state_machine';
import type { UIStore }      from '../state/ui_store';
import type { PassUpdate, PromptApplyFeedback } from '../types/pil';
import { PASS_DESCRIPTIONS, PASS_TIERS, TIER_COLORS } from '../types/pil';

const STYLES = `
.xb-proc { padding: 12px; animation: fade-in 200ms; }
.xb-proc-title { font-size: 11.5px; font-weight: 600; color: var(--txt); display: flex; align-items: center; gap: 7px; margin-bottom: 10px; }
.xb-proc-spinner { font-size: 14px; animation: spin 600ms linear infinite; color: var(--cyan); }
.xb-proc-track { height: 2px; background: var(--bd); border-radius: 2px; margin-bottom: 12px; overflow: hidden; }
.xb-proc-fill { height: 100%; background: var(--cyan); border-radius: 2px; transition: width 400ms ease-out; }
.xb-pass-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.xb-pass-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.xb-pass-dot.done    { background: var(--grn); }
.xb-pass-dot.running { background: var(--cyan); animation: pulse-dot 1s ease-in-out infinite; color: var(--cyan); }
.xb-pass-dot.failed  { background: var(--red); }
.xb-pass-dot.pending { background: var(--bd); }
.xb-pass-lbl { font-size: 10.5px; flex: 1; }
.xb-pass-lbl.done    { color: var(--txt3); }
.xb-pass-lbl.running { color: var(--txt); }
.xb-pass-lbl.pending { color: var(--txt3); }
.xb-pass-lbl.failed  { color: var(--red); }
.xb-pass-tier { font-size: 8px; padding: 1px 4px; border-radius: 3px; font-family: var(--font-mono); flex-shrink: 0; }
.xb-pass-meta { font-size: 9px; color: var(--txt3); font-family: var(--font-mono); flex-shrink: 0; }
.xb-apply { padding: 12px; animation: fade-in 160ms; }
.xb-apply-title { font-size: 11.5px; font-weight: 700; color: var(--txt); display: flex; align-items: center; gap: 7px; margin-bottom: 9px; }
.xb-apply-summary { font-size: 10px; color: var(--txt2); line-height: 1.45; margin-bottom: 10px; }
.xb-apply-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.xb-apply-step { border: 1px solid var(--bd); background: var(--bgc); border-radius: var(--rs); padding: 7px; min-width: 0; }
.xb-apply-step b { display: block; font-size: 9.5px; color: var(--txt); margin-bottom: 3px; }
.xb-apply-step span { display: block; font-size: 9px; color: var(--txt3); }
`;

const ALL_PASSES = [
  'pass1_planning', 'pass2_dsl_draft', 'pass3_self_critique',
  'pass4_determinism_audit', 'pass5_final_output',
];

export class ProcessingView {
  private readonly _consoleSM: ConsoleSM;
  private readonly _uiStore:   UIStore;
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(consoleSM: ConsoleSM, uiStore: UIStore) {
    this._consoleSM = consoleSM; this._uiStore = uiStore;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    container.appendChild(this._el);
    this._unsubs.push(this._consoleSM.subscribe(() => this._render()));
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn()); this._el?.remove();
  }

  private _render(): void {
    const state = this._consoleSM.state;
    if (state.name === 'ApplyingMutation') {
      this._renderApplying(state.summary);
      return;
    }
    if (state.name !== 'Processing') { this._el.innerHTML = ''; return; }

    const { passUpdates, prompt } = state;
    const mode = this._uiStore.mode;
    const isArch = mode === 'ARCHITECT_MODE' || mode === 'ADVANCED';

    // Build pass status map
    const statusMap = new Map<string, PassUpdate>();
    for (const u of passUpdates) statusMap.set(u.pass, u);

    // Progress %
    const done  = passUpdates.filter(u => u.status === 'done').length;
    const total = ALL_PASSES.length;
    const pct   = Math.min(95, Math.round((done / total) * 100));

    const wrap = document.createElement('div');
    wrap.className = 'xb-proc';

    // Title
    const title = document.createElement('div');
    title.className = 'xb-proc-title';
    title.innerHTML = `<span class="xb-proc-spinner">✦</span>
      ${isArch ? `Processing: <span style="font-family:var(--font-mono);font-size:10px;color:var(--txt2)">"${prompt.slice(0, 40)}${prompt.length > 40 ? '…' : ''}"</span>`
               : 'Processing your request'}`;
    wrap.appendChild(title);

    // Progress bar
    const track = document.createElement('div');
    track.className = 'xb-proc-track';
    const fill  = document.createElement('div');
    fill.className = 'xb-proc-fill';
    fill.style.width = `${pct}%`;
    track.appendChild(fill);
    wrap.appendChild(track);

    // Pass rows
    for (const passId of ALL_PASSES) {
      const update = statusMap.get(passId);
      const status = update?.status ?? 'pending';
      const row    = document.createElement('div');
      row.className = 'xb-pass-row';

      const dot = document.createElement('div');
      dot.className = `xb-pass-dot ${status}`;
      row.appendChild(dot);

      const lbl = document.createElement('div');
      lbl.className = `xb-pass-lbl ${status}`;
      lbl.textContent = isArch ? passId : (PASS_DESCRIPTIONS[passId] ?? passId);
      row.appendChild(lbl);

      const tier = PASS_TIERS[passId as keyof typeof PASS_TIERS];
      if (tier && isArch) {
        const tierBadge = document.createElement('span');
        tierBadge.className = 'xb-pass-tier';
        tierBadge.textContent = tier;
        tierBadge.style.background = TIER_COLORS[tier] + '1a';
        tierBadge.style.color      = TIER_COLORS[tier];
        tierBadge.style.border     = `1px solid ${TIER_COLORS[tier]}44`;
        row.appendChild(tierBadge);
      }

      if (update?.status === 'done' && isArch) {
        const meta = document.createElement('span');
        meta.className   = 'xb-pass-meta';
        meta.textContent = `${update.tokens ?? 0}t · ${update.cost_cents?.toFixed(2) ?? '0.00'}¢`;
        row.appendChild(meta);
      }

      wrap.appendChild(row);
    }

    this._el.innerHTML = '';
    this._el.appendChild(wrap);
  }

  private _renderApplying(summary: string): void {
    const wrap = document.createElement('div');
    wrap.className = 'xb-apply';

    const title = document.createElement('div');
    title.className = 'xb-apply-title';
    title.innerHTML = '<span class="xb-proc-spinner">*</span> Applying change';
    wrap.appendChild(title);

    const summaryEl = document.createElement('div');
    summaryEl.className = 'xb-apply-summary';
    summaryEl.textContent = summary || 'Reviewed mutation';
    wrap.appendChild(summaryEl);

    const grid = document.createElement('div');
    grid.className = 'xb-apply-grid';
    const steps: Array<[string, string]> = [
      ['GDE', 'committing'],
      ['SGC', 'checking plan'],
      ['Runtime', 'loading CGS'],
      ['Replay', 'waiting'],
    ];
    for (const [label, status] of steps) {
      const item = document.createElement('div');
      item.className = 'xb-apply-step';
      const strong = document.createElement('b');
      strong.textContent = label;
      const span = document.createElement('span');
      span.textContent = status;
      item.appendChild(strong);
      item.appendChild(span);
      grid.appendChild(item);
    }
    wrap.appendChild(grid);
    this._el.innerHTML = '';
    this._el.appendChild(wrap);
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-proc-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-proc-styles'; s.textContent = STYLES;
    document.head.appendChild(s);
  }
}


/**
 * views/idle_view.ts — Welcome screen with suggestion chips
 */
export class IdleView {
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  mount(container: HTMLElement, _uiStore: UIStore): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:24px;animation:fade-in 300ms';

    this._el.innerHTML = `
      <div style="font-size:15px;font-weight:700;color:var(--txt)">Good evening.</div>
      <div style="font-size:11px;color:var(--txt2)">What do you want to build?</div>
      <div class="xb-idle-chips" style="display:flex;flex-wrap:wrap;gap:5px;justify-content:center;max-width:340px"></div>
    `;

    const chips = [
      'Add a patrolling enemy',
      'Make player jump higher',
      'Add a health regen system',
      'Balance zombie difficulty',
      'Add a damage multiplier',
      'Create a win condition rule',
    ];

    const chipContainer = this._el.querySelector('.xb-idle-chips')!;
    for (const chip of chips) {
      const btn = document.createElement('button');
      btn.style.cssText = `
        font-size:10px;padding:4px 11px;border-radius:20px;border:1px solid var(--bd);
        color:var(--txt2);cursor:pointer;background:var(--bgc);transition:all 120ms;font-family:inherit
      `;
      btn.textContent = chip;
      btn.addEventListener('mouseenter', () => { btn.style.borderColor = 'rgba(0,212,255,.3)'; btn.style.color = 'var(--cyan)'; });
      btn.addEventListener('mouseleave', () => { btn.style.borderColor = 'var(--bd)'; btn.style.color = 'var(--txt2)'; });
      btn.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('xace:prefill-prompt', { detail: { text: chip } }));
      });
      chipContainer.appendChild(btn);
    }

    container.appendChild(this._el);
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn()); this._el?.remove();
  }
}


/**
 * views/review_view.ts — PreviewPending state: diff + decision bar
 */
import type { BuilderClient }  from '../api/builder_client';
import { makePilApply }        from '../api/message_types';
import { DiffViewer }          from '../canvas/diff_viewer';

export class ReviewView {
  private readonly _consoleSM: ConsoleSM;
  private readonly _uiStore:   UIStore;
  private readonly _client:    BuilderClient;
  private _el!:       HTMLElement;
  private _diffViewer!: DiffViewer;
  private readonly _unsubs: Array<() => void> = [];

  constructor(consoleSM: ConsoleSM, uiStore: UIStore, client: BuilderClient) {
    this._consoleSM = consoleSM;
    this._uiStore   = uiStore;
    this._client    = client;
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'display:flex;flex-direction:column;flex:1;overflow:hidden;animation:fade-in 200ms';
    container.appendChild(this._el);

    // Header
    const hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:8px 12px;flex-shrink:0';
    hdr.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;min-width:0">
        <div style="font-size:12.5px;font-weight:600;color:var(--txt)">Proposed change</div>
        <div style="font-size:8.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--grn);border:1px solid rgba(16,185,129,.28);border-radius:999px;padding:2px 6px;background:rgba(16,185,129,.07)">safe</div>
      </div>
      <div id="xb-rv-pass" style="font-size:9.5px;color:var(--txt2)"></div>
    `;
    this._el.appendChild(hdr);

    const note = document.createElement('div');
    note.style.cssText = 'padding:0 12px 8px;font-size:10px;color:var(--txt3);line-height:1.45;flex-shrink:0';
    note.textContent = 'Review this proposal before saving. Apply writes it to the project; Revise keeps editing; Discard leaves the project unchanged.';
    this._el.appendChild(note);

    // Diff viewer
    const diffWrap = document.createElement('div');
    diffWrap.style.cssText = 'padding:0 12px;flex:1;overflow-y:auto';
    this._diffViewer = new DiffViewer(this._consoleSM, this._uiStore);
    this._diffViewer.mount(diffWrap);
    this._el.appendChild(diffWrap);

    // Decision bar
    this._el.appendChild(this._buildDecisionBar());

    this._unsubs.push(
      this._consoleSM.subscribe(state => {
        if (state.name === 'PreviewPending') {
          const passEl = document.getElementById('xb-rv-pass');
          if (passEl) passEl.textContent = `Confidence: ${Math.round(state.result.confidence * 100)}%`;
        }
      }),
    );
  }

  unmount(): void {
    this._diffViewer?.unmount();
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  private _buildDecisionBar(): HTMLElement {
    const bar = document.createElement('div');
    bar.style.cssText = `
      border-top:1px solid var(--bd);padding:7px 12px;
      display:flex;align-items:center;gap:7px;background:var(--bgp);flex-shrink:0
    `;

    const discard = document.createElement('button');
    discard.style.cssText = 'font-size:10.5px;color:var(--txt2);cursor:pointer;padding:4px 7px;border-radius:4px;background:none;border:none;font-family:inherit;transition:all 120ms';
    discard.textContent = 'Discard';
    discard.addEventListener('mouseenter', () => { discard.style.color = 'var(--red)'; discard.style.background = 'rgba(239,68,68,.07)'; });
    discard.addEventListener('mouseleave', () => { discard.style.color = 'var(--txt2)'; discard.style.background = 'none'; });
    discard.addEventListener('click', () => {
      this._consoleSM.discardMutation();
      this._client.send({ type: 'pil_discard', session_id: this._client.sessionId });
    });
    bar.appendChild(discard);

    const revise = document.createElement('button');
    revise.style.cssText = 'font-size:10.5px;color:var(--txt2);cursor:pointer;padding:4px 7px;background:none;border:none;font-family:inherit';
    revise.textContent = 'Revise Prompt';
    revise.addEventListener('click', () => this._consoleSM.reviseMutation());
    bar.appendChild(revise);

    const spacer = document.createElement('div');
    spacer.style.flex = '1';
    bar.appendChild(spacer);

    const apply = document.createElement('button');
    apply.style.cssText = `
      background:linear-gradient(135deg,rgba(0,212,255,.25),rgba(168,85,247,.25));
      border:1px solid rgba(0,212,255,.4);border-radius:var(--r);color:var(--cyan);
      font-family:inherit;font-size:11px;font-weight:700;padding:5px 18px;cursor:pointer;transition:all var(--tr)
    `;
    apply.textContent = 'Apply to Project';
    apply.addEventListener('mouseenter', () => { apply.style.boxShadow = '0 0 20px rgba(0,212,255,.25)'; apply.style.transform = 'translateY(-1px)'; });
    apply.addEventListener('mouseleave', () => { apply.style.boxShadow = 'none'; apply.style.transform = 'none'; });
    apply.addEventListener('click', () => {
      const state = this._consoleSM.state;
      const approval = state.name === 'PreviewPending' && state.result.preview
        ? {
            schema: 'xace.prompt_preview_approval.v1' as const,
            preview_id: state.result.preview.preview_id,
            approval_token: state.result.preview.approval_token,
            approval_source: 'builder_review',
            approved_by: this._client.sessionId,
          }
        : undefined;
      this._consoleSM.applyMutation();
      this._client.send(makePilApply(this._client.sessionId, approval));
    });
    bar.appendChild(apply);

    return bar;
  }
}


/**
 * views/blocked_view.ts — Safety block explanation card
 */
export class BlockedView {
  private readonly _consoleSM: ConsoleSM;
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(consoleSM: ConsoleSM) { this._consoleSM = consoleSM; }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'padding:16px;animation:fade-in 200ms';
    container.appendChild(this._el);
    this._unsubs.push(this._consoleSM.subscribe(() => this._render()));
  }

  unmount(): void { this._unsubs.forEach(fn => fn()); this._el?.remove(); }

  private _render(): void {
    const state = this._consoleSM.state;
    if (state.name !== 'BlockedView' && state.name !== 'ErrorView') {
      this._el.innerHTML = '';
      return;
    }

    const isError = state.name === 'ErrorView';
    const applyFeedback = isError ? state.applyFeedback : undefined;
    const title = isError ? 'Request failed' : 'Change blocked';
    const reason = isError
      ? state.reason
      : state.result.reason;
    const detail = isError
      ? applyFeedback
        ? `${applyFeedback.stage}: ${applyFeedback.code || applyFeedback.message}`
        : 'Nothing was saved. Put the request back in the prompt, then send it again when ready.'
      : `Guard: ${state.result.guard}. Nothing was saved.`;

    this._el.innerHTML = '';
    const card = document.createElement('div');
    card.style.cssText = 'background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.2);border-radius:var(--r);padding:14px;border-left:3px solid var(--red)';

    const heading = document.createElement('div');
    heading.style.cssText = 'font-size:12px;font-weight:600;color:var(--txt);display:flex;align-items:center;gap:8px;margin-bottom:8px';
    const icon = document.createElement('span');
    icon.style.color = 'var(--red)';
    icon.textContent = '!';
    heading.appendChild(icon);
    heading.appendChild(document.createTextNode(title));
    card.appendChild(heading);

    const reasonEl = document.createElement('div');
    reasonEl.style.cssText = 'font-size:10.5px;color:var(--txt2);margin-bottom:8px;line-height:1.6';
    reasonEl.textContent = reason || 'XACE could not complete that request.';
    card.appendChild(reasonEl);

    const detailEl = document.createElement('div');
    detailEl.style.cssText = 'font-size:9.5px;color:var(--txt3);line-height:1.5';
    detailEl.textContent = detail;
    card.appendChild(detailEl);

    if (applyFeedback) {
      this._appendApplyFeedback(card, applyFeedback);
    }

    const actions = document.createElement('div');
    actions.style.cssText = 'margin-top:12px;display:flex;gap:8px;flex-wrap:wrap';

    const dismiss = document.createElement('button');
    dismiss.style.cssText = 'font-size:10.5px;padding:4px 12px;background:rgba(255,255,255,.04);border:1px solid var(--bd);border-radius:var(--rs);color:var(--txt2);cursor:pointer;font-family:inherit';
    dismiss.textContent = 'Dismiss';
    dismiss.addEventListener('click', () => this._consoleSM.dismiss());
    actions.appendChild(dismiss);

    if (isError) {
      const tryAgain = document.createElement('button');
      tryAgain.style.cssText = 'font-size:10.5px;padding:4px 12px;background:rgba(0,212,255,.07);border:1px solid rgba(0,212,255,.2);border-radius:var(--rs);color:var(--cyan);cursor:pointer;font-family:inherit';
      tryAgain.textContent = 'Put Back in Prompt';
      tryAgain.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('xace:prefill-prompt', { detail: { text: state.prompt.slice(0, 120) } }));
        this._consoleSM.dismiss();
      });
      actions.appendChild(tryAgain);
    }

    if (!isError) {
      const rephrase = document.createElement('button');
      rephrase.style.cssText = 'font-size:10.5px;padding:4px 12px;background:rgba(0,212,255,.07);border:1px solid rgba(0,212,255,.2);border-radius:var(--rs);color:var(--cyan);cursor:pointer;font-family:inherit';
      rephrase.textContent = 'Rephrase';
      rephrase.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('xace:prefill-prompt', { detail: { text: state.prompt.slice(0, 120) } }));
        this._consoleSM.dismiss();
      });
      actions.appendChild(rephrase);
    }

    card.appendChild(actions);
    this._el.appendChild(card);
  }

  private _appendApplyFeedback(card: HTMLElement, feedback: PromptApplyFeedback): void {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-top:12px;border-top:1px solid rgba(255,255,255,.08);padding-top:10px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px';
    const rows: Array<[string, string]> = [
      ['Classifier', feedback.classifier?.category_id ?? 'unavailable'],
      ['Diff', `${feedback.diff?.cgs_diff?.operation_count ?? 0} CGS ops`],
      ['SGC', sectionStatus(feedback.sgc)],
      ['Runtime', sectionStatus(feedback.runtime_load)],
      ['Replay', sectionStatus(feedback.replay)],
      ['Rollback', String(feedback.rollback.status ?? 'unknown')],
      ['Cost', `${numberText(feedback.cost.total_cost_cents)}c / ${numberText(feedback.cost.token_count)} tok`],
      ['Latency', `${numberText(feedback.latency.apply_latency_ms)} ms`],
      ['Proof', proofSummary(feedback.proof_links)],
    ];
    for (const [label, value] of rows) {
      const row = document.createElement('div');
      row.style.cssText = 'min-width:0';
      const name = document.createElement('div');
      name.style.cssText = 'font-size:8.5px;color:var(--txt3);text-transform:uppercase;font-weight:700;margin-bottom:2px';
      name.textContent = label;
      const text = document.createElement('div');
      text.style.cssText = 'font-size:9.5px;color:var(--txt2);font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
      text.title = value;
      text.textContent = value;
      row.appendChild(name);
      row.appendChild(text);
      wrap.appendChild(row);
    }
    card.appendChild(wrap);
  }
}

function sectionStatus(section: Record<string, unknown>): string {
  const status = typeof section.status === 'string' ? section.status : '';
  const accepted = typeof section.accepted === 'boolean' ? (section.accepted ? 'accepted' : 'rejected') : '';
  const ok = typeof section.ok === 'boolean' ? (section.ok ? 'ok' : 'failed') : '';
  const attempted = section.attempted === true ? 'attempted' : '';
  const required = section.required === true ? 'required' : 'optional';
  return status || accepted || ok || attempted || required;
}

function numberText(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value * 100) / 100) : '0';
}

function proofSummary(section: Record<string, unknown>): string {
  const plan = section.execution_plan;
  if (typeof plan === 'object' && plan !== null && 'path' in plan) {
    const path = (plan as { path?: unknown }).path;
    return typeof path === 'string' && path ? path : String(section.audit_dataset ?? '');
  }
  return String(section.audit_dataset ?? '');
}


/**
 * views/diagnostic_view.ts — Explanation/debug result from DiagnosticOrchestrator
 */
export class DiagnosticView {
  private readonly _consoleSM: ConsoleSM;
  private _el!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];

  constructor(consoleSM: ConsoleSM) { this._consoleSM = consoleSM; }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.style.cssText = 'padding:16px;animation:fade-in 200ms';
    container.appendChild(this._el);
    this._unsubs.push(this._consoleSM.subscribe(() => this._render()));
  }

  unmount(): void { this._unsubs.forEach(fn => fn()); this._el?.remove(); }

  private _render(): void {
    const state = this._consoleSM.state;
    if (state.name !== 'DiagnosticView') { this._el.innerHTML = ''; return; }
    const hasFix = !!state.result.suggestion;
    this._el.innerHTML = `
      <div style="background:var(--bgc);border:1px solid var(--bd);border-radius:var(--r);padding:14px;border-left:3px solid var(--cyan)">
        <div style="font-size:12px;font-weight:600;color:var(--txt);display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <span style="color:var(--cyan)">✦</span> ${state.result.intent_category === 'DebugIssue' ? 'Debug Analysis' : 'Explanation'}
        </div>
        <div style="font-size:11px;color:var(--txt);line-height:1.7;margin-bottom:10px">${state.result.explanation}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button onclick="window.dispatchEvent(new CustomEvent('xace:dismiss-diag'))"
            style="font-size:10.5px;padding:4px 12px;background:rgba(255,255,255,.04);border:1px solid var(--bd);border-radius:var(--rs);color:var(--txt2);cursor:pointer;font-family:inherit">
            Close
          </button>
          ${hasFix ? `<button onclick="window.dispatchEvent(new CustomEvent('xace:implement-fix'))"
            style="font-size:10.5px;padding:4px 14px;background:rgba(0,212,255,.1);border:1px solid rgba(0,212,255,.3);border-radius:var(--rs);color:var(--cyan);cursor:pointer;font-family:inherit;font-weight:600">
            ✓ Implement suggested fix
          </button>` : ''}
        </div>
      </div>
    `;
    window.addEventListener('xace:dismiss-diag',    () => this._consoleSM.dismissDiagnostic(), { once: true });
    window.addEventListener('xace:implement-fix',   () => {
      this._consoleSM.implementDiagnosticFix('Implement the fix for: ' + state.prompt);
    }, { once: true });
  }
}

// Import UIStore for IdleView — imported at top of file
