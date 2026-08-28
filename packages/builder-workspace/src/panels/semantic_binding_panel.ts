import type { BuilderClient } from '../api/builder_client';
import { makeSemanticBindingUpdate } from '../api/message_types';
import type { CGSStore } from '../state/cgs_store';
import type {
  AssetRef,
  SemanticAssetBinding,
  SemanticPlaybackKind,
} from '../types/cgs';
import {
  defaultBindingId,
  defaultSemanticAction,
  ENGINE_TARGETS,
  eventsForPlaybackKind,
  isAssetCompatibleWithPlaybackKind,
  PLAYBACK_KINDS,
  rustAssetStatus,
  rustAssetType,
} from './semantic_binding_catalog';
import {
  evaluateSemanticBindingStatuses,
  semanticBindingStatusSummary,
  statusBlocksLaunch,
  type SemanticBindingEngineStatus,
} from './semantic_binding_status';

const STATUS_ORDER: SemanticBindingEngineStatus[] = ['resolved', 'fallback', 'unresolved', 'missing', 'unsupported'];

const STYLES = `
.xb-sbp { border-top: 1px solid var(--bd); margin-top: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 8px; }
.xb-sbp-head { display:flex; align-items:center; gap:6px; }
.xb-sbp-title { color: var(--txt); font-size: 11px; font-weight: 700; flex: 1; }
.xb-sbp-count { color: var(--txt3); font-size: 9px; font-family: var(--font-mono); }
.xb-sbp-note { color: var(--txt3); font-size: 9px; line-height: 1.45; }
.xb-sbp-list { display:flex; flex-direction:column; gap:6px; }
.xb-sbp-card { border:1px solid var(--bd); background: rgba(255,255,255,.025); border-radius: var(--r); padding:7px; display:flex; flex-direction:column; gap:5px; }
.xb-sbp-card-main { display:flex; gap:6px; align-items:center; min-width:0; }
.xb-sbp-kind { color: var(--cyan); font-size: 8.5px; font-weight: 800; letter-spacing:.04em; text-transform:uppercase; width:58px; flex-shrink:0; }
.xb-sbp-id { color: var(--txt); font-family: var(--font-mono); font-size: 9px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
.xb-sbp-sub { color: var(--txt3); font-family: var(--font-mono); font-size: 8.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.xb-sbp-remove { border:1px solid rgba(239,68,68,.28); color:var(--red); background:rgba(239,68,68,.05); border-radius:var(--rs); font:inherit; font-size:8.5px; padding:2px 6px; cursor:pointer; }
.xb-sbp-form { display:grid; grid-template-columns: 1fr 1fr; gap:6px; }
.xb-sbp-field { display:flex; flex-direction:column; gap:3px; min-width:0; }
.xb-sbp-field.full { grid-column:1 / -1; }
.xb-sbp-field label { color:var(--txt3); font-size:8px; font-weight:750; letter-spacing:.04em; text-transform:uppercase; }
.xb-sbp-field select, .xb-sbp-field input {
  background: rgba(255,255,255,.03); border: 1px solid var(--bd); border-radius: var(--rs);
  color: var(--txt2); font: inherit; font-size: 9.5px; padding: 4px 6px; min-width:0;
}
.xb-sbp-field select:focus, .xb-sbp-field input:focus { outline:none; border-color: rgba(0,212,255,.48); color:var(--txt); }
.xb-sbp-engines { display:flex; gap:5px; flex-wrap:wrap; }
.xb-sbp-engine { color:var(--txt2); font-size:8.5px; display:flex; align-items:center; gap:3px; border:1px solid var(--bd); border-radius:999px; padding:2px 6px; }
.xb-sbp-status-summary { display:flex; gap:5px; flex-wrap:wrap; border:1px solid var(--bd); border-radius:var(--r); padding:5px; background:rgba(255,255,255,.018); }
.xb-sbp-status-chip { color:var(--txt2); font-size:8px; font-family:var(--font-mono); border:1px solid var(--bd); border-radius:999px; padding:2px 6px; }
.xb-sbp-status-chip.blocking { border-color:rgba(239,68,68,.28); color:var(--red); }
.xb-sbp-badges { display:flex; gap:4px; flex-wrap:wrap; }
.xb-sbp-badge { font-family:var(--font-mono); font-size:7.8px; border:1px solid var(--bd); border-radius:999px; padding:2px 5px; color:var(--txt3); }
.xb-sbp-badge.resolved { border-color:rgba(16,185,129,.32); color:var(--grn); background:rgba(16,185,129,.06); }
.xb-sbp-badge.fallback { border-color:rgba(245,158,11,.38); color:var(--amb); background:rgba(245,158,11,.06); }
.xb-sbp-badge.unresolved, .xb-sbp-badge.missing, .xb-sbp-badge.unsupported { border-color:rgba(239,68,68,.32); color:var(--red); background:rgba(239,68,68,.045); }
.xb-sbp-add {
  grid-column:1 / -1; border:1px solid rgba(0,212,255,.32); color:var(--cyan); background:var(--cynd);
  border-radius:var(--rs); font:inherit; font-size:9.5px; font-weight:700; padding:5px 8px; cursor:pointer;
}
.xb-sbp-add:disabled { color:var(--txt3); border-color:var(--bd); background:rgba(255,255,255,.02); cursor:not-allowed; }
.xb-sbp-empty { border:1px dashed var(--bd); border-radius:var(--r); color:var(--txt3); font-size:9px; line-height:1.4; padding:8px; }
.xb-sbp-flash { color:var(--grn); font-size:8.5px; font-weight:700; min-height:12px; }
`;

interface SemanticBindingPanelDeps {
  readonly cgsStore: CGSStore;
  readonly client: BuilderClient;
}

export class SemanticBindingPanel {
  private readonly deps: SemanticBindingPanelDeps;
  private root!: HTMLElement;
  private flash!: HTMLElement;
  private readonly unsubs: Array<() => void> = [];
  private readonly onOpen = () => this.focus();

  constructor(deps: SemanticBindingPanelDeps) {
    this.deps = deps;
    this.injectStyles();
  }

  mount(container: HTMLElement): void {
    this.root = document.createElement('section');
    this.root.className = 'xb-sbp';
    this.root.setAttribute('aria-label', 'Semantic bindings');
    container.appendChild(this.root);
    this.unsubs.push(this.deps.cgsStore.subscribe(() => this.render()));
    window.addEventListener('xace:open-semantic-bindings', this.onOpen);
  }

  unmount(): void {
    this.unsubs.forEach((fn) => fn());
    window.removeEventListener('xace:open-semantic-bindings', this.onOpen);
    this.root?.remove();
  }

  focus(): void {
    this.root?.scrollIntoView({ block: 'nearest' });
    this.root?.classList.add('xb-sbp-focus');
    setTimeout(() => this.root?.classList.remove('xb-sbp-focus'), 900);
  }

  private render(): void {
    const bindings = [...this.deps.cgsStore.semanticBindings]
      .sort((left, right) => (left.priority ?? 0) - (right.priority ?? 0) || left.binding_id.localeCompare(right.binding_id));
    const assets = [...this.deps.cgsStore.assetRefs].sort((left, right) => left.placeholder_id.localeCompare(right.placeholder_id));

    this.root.innerHTML = '';
    const head = document.createElement('div');
    head.className = 'xb-sbp-head';
    head.innerHTML = `
      <div class="xb-sbp-title">Semantic bindings</div>
      <div class="xb-sbp-count">${bindings.length} mapped</div>
    `;
    this.root.appendChild(head);

    const note = document.createElement('div');
    note.className = 'xb-sbp-note';
    note.textContent = 'Map semantic events to portable Animation, Audio, or VFX playback commands. Pre-runtime/handoff status is tracked per engine before launch.';
    this.root.appendChild(note);

    this.root.appendChild(this.buildStatusSummary(bindings, assets));
    this.root.appendChild(this.buildBindingList(bindings, assets));
    this.root.appendChild(this.buildComposer(bindings, assets));

    this.flash = document.createElement('div');
    this.flash.className = 'xb-sbp-flash';
    this.root.appendChild(this.flash);
  }

  private buildStatusSummary(bindings: readonly SemanticAssetBinding[], assets: readonly AssetRef[]): HTMLElement {
    const summary = semanticBindingStatusSummary(bindings, assets);
    const wrap = document.createElement('div');
    wrap.className = 'xb-sbp-status-summary';
    wrap.setAttribute('aria-label', 'Semantic binding status before runtime/handoff launch');
    for (const status of STATUS_ORDER) {
      const chip = document.createElement('span');
      chip.className = `xb-sbp-status-chip${statusBlocksLaunch(status) && summary[status] > 0 ? ' blocking' : ''}`;
      chip.textContent = `${status}:${summary[status]}`;
      chip.title = statusBlocksLaunch(status)
        ? `${status} bindings block runtime/handoff launch for the affected engine.`
        : `${status} bindings do not block launch.`;
      wrap.appendChild(chip);
    }
    return wrap;
  }

  private buildBindingList(bindings: readonly SemanticAssetBinding[], assets: readonly AssetRef[]): HTMLElement {
    const list = document.createElement('div');
    list.className = 'xb-sbp-list';
    if (bindings.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'xb-sbp-empty';
      empty.textContent = 'No semantic playback bindings yet. Add one below after importing animation, audio, or VFX assets.';
      list.appendChild(empty);
      return list;
    }

    for (const binding of bindings) {
      const card = document.createElement('div');
      card.className = 'xb-sbp-card';
      const eventName = binding.event_name || 'unknown.event';
      const assetId = binding.asset?.id || 'missing_asset';
      const engines = engineTargetsFromBinding(binding).join(', ') || 'portable';
      card.innerHTML = `
        <div class="xb-sbp-card-main">
          <span class="xb-sbp-kind">${escapeHtml(binding.playback_kind)}</span>
          <span class="xb-sbp-id" title="${escapeHtml(binding.binding_id)}">${escapeHtml(binding.binding_id)}</span>
        </div>
        <div class="xb-sbp-sub">${escapeHtml(eventName)} -> ${escapeHtml(assetId)} (${escapeHtml(engines)})</div>
      `;
      const badges = document.createElement('div');
      badges.className = 'xb-sbp-badges';
      for (const status of evaluateSemanticBindingStatuses(binding, assets)) {
        const badge = document.createElement('span');
        badge.className = `xb-sbp-badge ${status.status}`;
        badge.title = status.reason;
        badge.textContent = `${status.engine}:${status.status}`;
        badges.appendChild(badge);
      }
      card.appendChild(badges);
      const remove = document.createElement('button');
      remove.className = 'xb-sbp-remove';
      remove.type = 'button';
      remove.textContent = 'Remove binding';
      remove.addEventListener('click', () => {
        this.saveBindings(bindings.filter((item) => item.binding_id !== binding.binding_id));
      });
      card.appendChild(remove);
      list.appendChild(card);
    }
    return list;
  }

  private buildComposer(bindings: readonly SemanticAssetBinding[], assets: readonly AssetRef[]): HTMLElement {
    const form = document.createElement('div');
    form.className = 'xb-sbp-form';

    const kind = selectField('Playback', PLAYBACK_KINDS.map((value) => ({ value, label: value })));
    const event = selectField('Event', []);
    const asset = selectField('Asset', []);
    const action = inputField('Action', defaultSemanticAction('Animation'));
    const path = inputField('Resource path', '');
    const priority = inputField('Priority', String(bindings.length));
    priority.input.type = 'number';
    priority.input.step = '1';
    const selector = selectField('Entity', [
      { value: 'SourceEntity', label: 'Source entity' },
      { value: 'TargetEntity', label: 'Target entity' },
    ]);
    const engines = engineField();
    const add = document.createElement('button');
    add.className = 'xb-sbp-add';
    add.type = 'button';
    add.textContent = 'Add semantic binding';

    const refresh = () => {
      const selectedKind = kind.select.value as SemanticPlaybackKind;
      action.input.value = action.input.value || defaultSemanticAction(selectedKind);
      replaceOptions(event.select, eventsForPlaybackKind(selectedKind).map((item) => ({
        value: item.name,
        label: item.label,
        title: item.summary,
      })));
      const compatibleAssets = assets.filter((item) => isAssetCompatibleWithPlaybackKind(item, selectedKind));
      replaceOptions(asset.select, compatibleAssets.map((item) => ({
        value: item.placeholder_id,
        label: `${item.placeholder_id} (${item.asset_type || 'unknown'})`,
        title: item.asset_path || item.component_name,
      })));
      const chosen = compatibleAssets.find((item) => item.placeholder_id === asset.select.value) ?? compatibleAssets[0];
      if (chosen) {
        path.input.value = chosen.asset_path || path.input.value || '';
      }
      add.disabled = compatibleAssets.length === 0;
      add.textContent = compatibleAssets.length === 0 ? 'Import compatible asset first' : 'Add semantic binding';
    };

    kind.select.addEventListener('change', () => {
      action.input.value = defaultSemanticAction(kind.select.value as SemanticPlaybackKind);
      path.input.value = '';
      refresh();
    });
    asset.select.addEventListener('change', () => {
      const chosen = assets.find((item) => item.placeholder_id === asset.select.value);
      path.input.value = chosen?.asset_path || '';
    });
    add.addEventListener('click', () => {
      const selectedKind = kind.select.value as SemanticPlaybackKind;
      const selectedAsset = assets.find((item) => item.placeholder_id === asset.select.value);
      if (!selectedAsset) {
        return;
      }
      const engineTargets = selectedEngineTargets(engines.container);
      const next = buildBindingRecord({
        eventName: event.select.value,
        kind: selectedKind,
        asset: selectedAsset,
        semanticAction: action.input.value.trim() || defaultSemanticAction(selectedKind),
        resourcePath: path.input.value.trim(),
        entitySelector: selector.select.value,
        priority: Number.parseInt(priority.input.value, 10) || 0,
        engineTargets,
        existingIds: new Set(bindings.map((item) => item.binding_id)),
      });
      this.saveBindings([...bindings, next]);
    });

    form.appendChild(kind.wrap);
    form.appendChild(event.wrap);
    form.appendChild(asset.wrap);
    form.appendChild(selector.wrap);
    form.appendChild(action.wrap);
    form.appendChild(priority.wrap);
    form.appendChild(path.wrap);
    form.appendChild(engines.wrap);
    form.appendChild(add);
    refresh();
    return form;
  }

  private saveBindings(bindings: readonly SemanticAssetBinding[]): void {
    const sorted = [...bindings].sort((left, right) => (left.priority ?? 0) - (right.priority ?? 0) || left.binding_id.localeCompare(right.binding_id));
    this.deps.client.send(makeSemanticBindingUpdate(sorted, this.deps.cgsStore.hash, this.deps.client.sessionId));
    this.showFlash('Semantic binding update sent');
  }

  private showFlash(message: string): void {
    if (!this.flash) return;
    this.flash.textContent = message;
    setTimeout(() => {
      if (this.flash) this.flash.textContent = '';
    }, 2500);
  }

  private injectStyles(): void {
    if (document.getElementById('xb-sbp-styles')) return;
    const style = document.createElement('style');
    style.id = 'xb-sbp-styles';
    style.textContent = STYLES;
    document.head.appendChild(style);
  }
}

interface BuildBindingInput {
  readonly eventName: string;
  readonly kind: SemanticPlaybackKind;
  readonly asset: AssetRef;
  readonly semanticAction: string;
  readonly resourcePath: string;
  readonly entitySelector: string;
  readonly priority: number;
  readonly engineTargets: readonly string[];
  readonly existingIds: ReadonlySet<string>;
}

export function buildBindingRecord(input: BuildBindingInput): SemanticAssetBinding {
  const parameters: Record<string, string> = {
    xace_engine_targets: input.engineTargets.join(','),
  };
  if (input.resourcePath) {
    parameters.resource_path = input.resourcePath;
    parameters.asset_path = input.resourcePath;
  }
  if (input.kind === 'Animation' && input.semanticAction) {
    parameters.state = input.semanticAction;
  }

  let bindingId = defaultBindingId(input.eventName, input.kind, input.asset.placeholder_id);
  let suffix = 2;
  while (input.existingIds.has(bindingId)) {
    bindingId = `${defaultBindingId(input.eventName, input.kind, input.asset.placeholder_id)}_${suffix}`;
    suffix += 1;
  }

  return {
    binding_id: bindingId,
    event_name: input.eventName,
    playback_kind: input.kind,
    asset: {
      id: input.asset.placeholder_id,
      asset_type: rustAssetType(input.asset.asset_type, input.kind),
      status: rustAssetStatus(input.asset.status),
    },
    semantic_action: input.semanticAction,
    entity_selector: input.entitySelector,
    parameters,
    enabled: true,
    priority: input.priority,
  };
}

function selectField(label: string, options: Array<{ value: string; label: string; title?: string }>) {
  const wrap = document.createElement('label');
  wrap.className = 'xb-sbp-field';
  const caption = document.createElement('label');
  caption.textContent = label;
  const select = document.createElement('select');
  replaceOptions(select, options);
  wrap.appendChild(caption);
  wrap.appendChild(select);
  return { wrap, select };
}

function inputField(label: string, value: string) {
  const wrap = document.createElement('label');
  wrap.className = label === 'Resource path' ? 'xb-sbp-field full' : 'xb-sbp-field';
  const caption = document.createElement('label');
  caption.textContent = label;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = value;
  wrap.appendChild(caption);
  wrap.appendChild(input);
  return { wrap, input };
}

function engineField() {
  const wrap = document.createElement('div');
  wrap.className = 'xb-sbp-field full';
  const caption = document.createElement('label');
  caption.textContent = 'Target engines';
  const container = document.createElement('div');
  container.className = 'xb-sbp-engines';
  for (const engine of ENGINE_TARGETS) {
    const item = document.createElement('label');
    item.className = 'xb-sbp-engine';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = engine;
    checkbox.checked = true;
    item.appendChild(checkbox);
    item.appendChild(document.createTextNode(engine));
    container.appendChild(item);
  }
  wrap.appendChild(caption);
  wrap.appendChild(container);
  return { wrap, container };
}

function replaceOptions(select: HTMLSelectElement, options: Array<{ value: string; label: string; title?: string }>): void {
  const previous = select.value;
  select.innerHTML = '';
  for (const option of options) {
    const el = document.createElement('option');
    el.value = option.value;
    el.textContent = option.label;
    if (option.title) el.title = option.title;
    select.appendChild(el);
  }
  if (options.some((option) => option.value === previous)) {
    select.value = previous;
  }
}

function selectedEngineTargets(container: HTMLElement): string[] {
  const selected = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))
    .filter((item) => item.checked)
    .map((item) => item.value);
  return selected.length > 0 ? selected : [...ENGINE_TARGETS];
}

function engineTargetsFromBinding(binding: SemanticAssetBinding): string[] {
  const raw = binding.parameters?.xace_engine_targets || '';
  return raw.split(',').map((item) => item.trim()).filter(Boolean);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[ch] ?? ch);
}
