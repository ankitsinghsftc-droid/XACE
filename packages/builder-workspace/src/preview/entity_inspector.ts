/**
 * Read-only CGS entity inspector.
 *
 * The inspector never mutates schema state directly. Edits are represented as
 * explicit builder intents so they can pass through PIL/runtime validation.
 */

import type { CGSActor, CGSComponent, CGSFieldValue } from '../types/cgs';
import { allActors, allSystems } from '../types/cgs';
import type { CGSStore } from '../state/cgs_store';
import type { UIStore } from '../state/ui_store';
import type { BuilderClient } from '../api/builder_client';
import type {
  EngineEditAckMessage,
  EngineEditAuditEntry,
  EngineEditCommitAckMessage,
  ServerMessage,
} from '../api/message_types';
import { makeEngineEdit, makeEngineEditCommit } from '../api/message_types';

const STYLES = `
.xb-ins { display: flex; flex-direction: column; overflow: hidden; flex: 1; min-height: 0; }
.xb-ins-head { padding: 6px 9px; border-bottom: 1px solid var(--bd); display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.xb-ins-name { font-size: 12px; font-weight: 600; color: var(--txt); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-ins-btn { font-size: 9.5px; color: var(--vlt); border: 1px solid rgba(168,85,247,.25); padding: 2px 8px; border-radius: 3px; cursor: pointer; background: transparent; font-family: inherit; white-space: nowrap; }
.xb-ins-btn:hover { background: var(--vltd); border-color: var(--vlt); }
.xb-ins-scroll { flex: 1; overflow-y: auto; min-height: 0; }
.xb-ins-meta { padding: 5px 9px; display: flex; gap: 6px; border-bottom: 1px solid var(--bd); align-items: center; min-width: 0; }
.xb-ins-pill { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: rgba(255,255,255,.04); color: var(--txt2); border: 1px solid var(--bd); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-ins-section { border-bottom: 1px solid var(--bd); }
.xb-ins-section-hd { padding: 6px 9px; display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; min-width: 0; }
.xb-ins-section-hd:hover { background: rgba(255,255,255,.02); }
.xb-ins-icon { width: 14px; height: 14px; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-size: 8px; font-weight: 700; background: rgba(0,212,255,.08); color: var(--cyan); flex-shrink: 0; }
.xb-ins-comp { font-size: 11px; font-weight: 600; color: var(--txt); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-ins-tag { font-size: 8.5px; padding: 1px 4px; border-radius: 3px; background: rgba(255,255,255,.04); color: var(--txt2); border: 1px solid var(--bd); white-space: nowrap; }
.xb-ins-body { padding: 5px 9px 8px; display: grid; gap: 3px; }
.xb-ins-field { display: grid; grid-template-columns: minmax(76px, 112px) minmax(0, 1fr) auto; align-items: center; gap: 6px; min-width: 0; }
.xb-ins-field-name { font-family: var(--font-mono); font-size: 9.5px; color: var(--txt2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-ins-field-val { font-family: var(--font-mono); font-size: 10px; color: var(--cyan); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-ins-field-val.bool-true { color: var(--grn); }
.xb-ins-field-val.bool-false { color: var(--red); }
.xb-ins-actions { display: flex; gap: 3px; justify-content: flex-end; }
.xb-ins-edit { font-size: 9px; color: var(--txt3); background: none; border: none; cursor: pointer; padding: 1px 4px; border-radius: 3px; font-family: inherit; white-space: nowrap; }
.xb-ins-edit:hover { background: var(--cynd); color: var(--cyan); }
.xb-ins-edit:disabled { opacity: .35; cursor: not-allowed; }
.xb-ins-edit:disabled:hover { background: none; color: var(--txt3); }
.xb-ins-note { padding: 8px 9px; font-size: 9.5px; color: var(--txt3); text-align: center; border-top: 1px solid var(--bd); flex-shrink: 0; background: rgba(0,0,0,.1); }
.xb-ins-audit { border-top: 1px solid var(--bd); padding: 7px 9px; display: grid; gap: 4px; background: rgba(0,0,0,.08); flex-shrink: 0; max-height: 92px; overflow-y: auto; }
.xb-ins-audit-title { font-size: 9px; color: var(--txt3); text-transform: uppercase; letter-spacing: .04em; }
.xb-ins-audit-row { font-size: 9.5px; color: var(--txt2); display: flex; gap: 6px; align-items: baseline; min-width: 0; }
.xb-ins-audit-row.ok { color: var(--grn); }
.xb-ins-audit-row.err { color: var(--red); }
.xb-ins-audit-main { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.xb-ins-audit-commit { margin-left: auto; font-size: 9px; color: var(--cyan); background: rgba(0,212,255,.06); border: 1px solid rgba(0,212,255,.22); border-radius: 3px; padding: 1px 5px; cursor: pointer; font-family: inherit; white-space: nowrap; }
.xb-ins-audit-commit:hover { background: var(--cynd); border-color: var(--cyan); }
.xb-ins-audit-commit:disabled { opacity: .45; cursor: not-allowed; }
.xb-ins-live-state { padding: 5px 9px; font-size: 9.5px; color: var(--txt2); border-bottom: 1px solid var(--bd); background: rgba(0,212,255,.025); }
.xb-ins-empty { padding: 22px 12px; font-size: 10.5px; color: var(--txt2); text-align: center; line-height: 1.7; }
`;

interface InspectorDeps {
  cgsStore: CGSStore;
  uiStore: UIStore;
  client: BuilderClient;
}

interface LocatedComponentUsage {
  readonly readers: number;
  readonly writers: number;
}

export class EntityInspector {
  private readonly deps: InspectorDeps;
  private readonly expanded = new Set<string>();
  private readonly unsubs: Array<() => void> = [];
  private readonly audit: EngineEditAuditEntry[] = [];
  private readonly committing = new Set<string>();
  private readonly committed = new Set<string>();
  private commitStatus = '';
  private root: HTMLElement | null = null;

  constructor(deps: InspectorDeps) {
    this.deps = deps;
    injectStyles();
  }

  mount(container: HTMLElement): void {
    this.root = document.createElement('div');
    this.root.className = 'xb-ins';
    container.appendChild(this.root);
    this.unsubs.push(this.deps.uiStore.select((state) => state.selectedEntity?.id ?? '', () => this.render()));
    this.unsubs.push(this.deps.cgsStore.subscribe(() => this.render()));
    this.unsubs.push(this.deps.client.onEngineEditAck((message) => this.handleEngineEditAck(message)));
    this.unsubs.push(this.deps.client.onRawMessage((message) => this.handleRawMessage(message)));
    this.render();
  }

  unmount(): void {
    this.unsubs.splice(0).forEach((unsub) => unsub());
    this.root?.remove();
    this.root = null;
  }

  private render(): void {
    if (!this.root) {
      return;
    }

    const selected = this.deps.uiStore.state.selectedEntity;
    if (!selected || selected.kind !== 'actor') {
      this.root.innerHTML = '<div class="xb-ins-empty">Select an actor in Preview or the project tree to inspect its component fields.</div>';
      return;
    }

    const located = allActors(this.deps.cgsStore.cgs).find(({ actor, modeId }) => (
      actor.id === selected.label || actor.id === selected.id || `actor:${modeId}:${actor.id}` === selected.id
    ));
    if (!located) {
      this.root.innerHTML = '<div class="xb-ins-empty">That actor is not in the current project file anymore. Select another actor.</div>';
      return;
    }

    const { actor, modeId } = located;
    this.root.innerHTML = '';
    this.root.appendChild(this.renderHeader(actor, modeId));

    const scroll = document.createElement('div');
    scroll.className = 'xb-ins-scroll';
    scroll.appendChild(this.renderMeta(actor, modeId));
    scroll.appendChild(this.renderLiveState(actor));
    for (const component of actor.components) {
      scroll.appendChild(this.renderComponent(actor, modeId, component));
    }
    this.root.appendChild(scroll);

    const note = document.createElement('div');
    note.className = 'xb-ins-note';
    note.textContent = this.commitStatus || 'Saved project fields are shown above. Live Preview changes only the running game until you save an accepted edit.';
    this.root.appendChild(note);
    this.root.appendChild(this.renderAudit());
  }

  private renderHeader(actor: CGSActor, modeId: string): HTMLElement {
    const head = document.createElement('div');
    head.className = 'xb-ins-head';

    const name = document.createElement('div');
    name.className = 'xb-ins-name';
    name.textContent = actor.id;
    name.title = `${modeId}/${actor.id}`;
    head.appendChild(name);

    const edit = document.createElement('button');
    edit.className = 'xb-ins-btn';
    edit.textContent = 'Edit via Prompt';
    edit.addEventListener('click', () => prefillPrompt(`Modify actor ${actor.id} in mode ${modeId}: `));
    head.appendChild(edit);

    const liveEntityId = this.runtimeEntityId(actor);
    const focus = document.createElement('button');
    focus.className = 'xb-ins-btn';
    focus.textContent = 'Focus Live';
    focus.disabled = liveEntityId === null;
    focus.title = liveEntityId === null
      ? 'Start the runtime and request a snapshot before focusing this actor.'
      : `Focus runtime entity ${liveEntityId}`;
    focus.addEventListener('click', () => {
      if (liveEntityId === null) return;
      this.deps.client.send(makeEngineEdit('focus_entity', this.deps.client.sessionId, {
        entity_id: String(liveEntityId),
        source: 'builder_inspector',
      }));
    });
    head.appendChild(focus);
    return head;
  }

  private renderMeta(actor: CGSActor, modeId: string): HTMLElement {
    const meta = document.createElement('div');
    meta.className = 'xb-ins-meta';
    meta.innerHTML = `
      <span class="xb-ins-pill" title="Actor type">${escapeHtml(actor.actor_type)}</span>
      <span class="xb-ins-pill" title="Control type">${escapeHtml(actor.control_type)}</span>
      <span class="xb-ins-pill" title="Mode">${escapeHtml(modeId)}</span>
      <span class="xb-ins-pill" style="margin-left:auto">${actor.components.length} components</span>
    `;
    return meta;
  }

  private renderLiveState(actor: CGSActor): HTMLElement {
    const live = document.createElement('div');
    live.className = 'xb-ins-live-state';
    const runtimeId = this.runtimeEntityId(actor);
    if (runtimeId === null) {
      live.textContent = 'Live preview: not connected to this actor yet. Start runtime, then request a snapshot.';
    } else {
      live.textContent = `Live preview: runtime entity ${runtimeId}. Preview edits are temporary until saved to the project.`;
    }
    return live;
  }

  private renderComponent(actor: CGSActor, modeId: string, component: CGSComponent): HTMLElement {
    const key = `${modeId}:${actor.id}:${component.type_id}`;
    const isOpen = this.expanded.has(key) || this.shouldAutoOpen(component);
    const usage = this.componentUsage(component.type_id);
    const section = document.createElement('section');
    section.className = 'xb-ins-section';

    const head = document.createElement('div');
    head.className = 'xb-ins-section-hd';
    head.innerHTML = `
      <span class="xb-ins-icon">${escapeHtml(component.name.slice(5, 6) || '?')}</span>
      <span class="xb-ins-comp" title="${escapeHtml(component.name)}">${escapeHtml(component.name)}</span>
      <span class="xb-ins-tag">id:${component.type_id}</span>
      <span class="xb-ins-tag">r:${usage.readers}</span>
      <span class="xb-ins-tag">w:${usage.writers}</span>
      <span>${isOpen ? 'v' : '>'}</span>
    `;

    const body = document.createElement('div');
    body.className = 'xb-ins-body';
    body.style.display = isOpen ? 'grid' : 'none';
    for (const [field, value] of Object.entries(component.defaults)) {
      body.appendChild(this.renderField(actor, modeId, component, field, value));
    }
    if (Object.keys(component.defaults).length === 0) {
      const empty = document.createElement('div');
      empty.className = 'xb-ins-empty';
      empty.textContent = 'No default fields.';
      body.appendChild(empty);
    }

    head.addEventListener('click', () => {
      if (this.expanded.has(key)) {
        this.expanded.delete(key);
      } else {
        this.expanded.add(key);
      }
      this.render();
    });
    section.appendChild(head);
    section.appendChild(body);
    return section;
  }

  private renderField(
    actor: CGSActor,
    modeId: string,
    component: CGSComponent,
    field: string,
    value: CGSFieldValue,
  ): HTMLElement {
    const row = document.createElement('div');
    row.className = 'xb-ins-field';
    const formatted = formatValue(value);
    const fieldPath = `${modeId}.${actor.id}.${component.name}.${field}`;
    row.innerHTML = `
      <span class="xb-ins-field-name" title="${escapeHtml(fieldPath)}">${escapeHtml(field)}</span>
      <span class="xb-ins-field-val ${typeof value === 'boolean' ? `bool-${value}` : ''}" title="${escapeHtml(formatted)}">${escapeHtml(formatted)}</span>
      <span class="xb-ins-actions">
        <button class="xb-ins-edit" data-action="copy">Copy</button>
        <button class="xb-ins-edit" data-action="edit">Prompt</button>
        <button class="xb-ins-edit" data-action="live">Preview</button>
      </span>
    `;
    row.querySelector<HTMLButtonElement>('[data-action="edit"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      prefillPrompt(`Set ${actor.id} ${component.name}.${field} to `);
    });
    row.querySelector<HTMLButtonElement>('[data-action="copy"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      void copyText(fieldPath);
    });
    const liveButton = row.querySelector<HTMLButtonElement>('[data-action="live"]');
    const runtimeEntityId = this.runtimeEntityId(actor);
    const canLiveEdit = runtimeEntityId !== null
      && isPrimitiveEditable(value)
      && this.runtimeHasComponent(runtimeEntityId, component.type_id);
    if (liveButton) {
      liveButton.disabled = !canLiveEdit;
      liveButton.title = canLiveEdit
        ? 'Preview this value in the running game without saving it yet.'
        : 'Live Preview needs a running runtime snapshot with this entity/component and a number, text, or true/false field.';
      liveButton.addEventListener('click', (event) => {
        event.stopPropagation();
        if (!canLiveEdit || runtimeEntityId === null) return;
        const next = promptForValue(field, value);
        if (next.cancelled) return;
        this.deps.client.send(makeEngineEdit('set_component_field', this.deps.client.sessionId, {
          entity_id: String(runtimeEntityId),
          mode_id: modeId,
          actor_id: actor.id,
          component_type_id: component.type_id,
          component_name: component.name,
          field_path: field,
          value: next.value,
          source: 'builder_inspector',
        }));
      });
    }
    return row;
  }

  private renderAudit(): HTMLElement {
    const audit = document.createElement('div');
    audit.className = 'xb-ins-audit';
    const title = document.createElement('div');
    title.className = 'xb-ins-audit-title';
    title.textContent = 'Live preview edits';
    audit.appendChild(title);

    if (this.audit.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'xb-ins-audit-row';
      empty.textContent = 'No live previews in this session.';
      audit.appendChild(empty);
      return audit;
    }

    for (const item of this.audit.slice(0, 5)) {
      const row = document.createElement('div');
      row.className = `xb-ins-audit-row ${item.accepted ? 'ok' : 'err'}`;
      const field = item.field_path ? `${item.component_type_id ?? '?'}:${item.field_path}` : item.kind;
      row.innerHTML = `
        <span>${item.accepted ? 'ok' : 'blocked'}</span>
        <span class="xb-ins-audit-main" title="${escapeHtml(item.reason)}">${escapeHtml(field)} - ${escapeHtml(item.reason)}</span>
      `;
      const commit = this.renderCommitButton(item);
      if (commit) {
        row.appendChild(commit);
      }
      audit.appendChild(row);
    }
    return audit;
  }

  private renderCommitButton(item: EngineEditAuditEntry): HTMLButtonElement | null {
    if (!canCommitAudit(item)) {
      return null;
    }
    const key = auditKey(item);
    const button = document.createElement('button');
    button.className = 'xb-ins-audit-commit';
    button.textContent = this.committed.has(key)
      ? 'saved'
      : this.committing.has(key) ? 'saving' : 'save';
    button.disabled = this.committed.has(key) || this.committing.has(key);
    button.title = this.committed.has(key)
      ? 'This accepted live edit has been saved into the project CGS.'
      : 'Save this accepted preview edit into game.cgs.json through the safe mutation path.';
    button.addEventListener('click', () => {
      this.commitLiveEdit(item);
    });
    return button;
  }

  private commitLiveEdit(item: EngineEditAuditEntry): void {
    if (!canCommitAudit(item)) {
      return;
    }
    const key = auditKey(item);
    this.committing.add(key);
    this.commitStatus = 'Saving accepted preview edit into the project...';
    this.deps.client.send(makeEngineEditCommit(this.deps.client.sessionId, {
      mode_id: item.mode_id,
      actor_id: item.actor_id,
      component_type_id: Number(item.component_type_id),
      component_name: item.component_name,
      field_path: item.field_path,
      value: item.value,
      audit_ts: item.ts,
    }));
    this.render();
  }

  private handleEngineEditAck(message: EngineEditAckMessage): void {
    const audit = message.audit ?? {
      ts: Date.now() / 1000,
      kind: 'set_component_field',
      entity_id: '',
      accepted: message.accepted,
      reason: message.reason ?? '',
      affected_entity_ids: message.affected_entity_ids,
    };
    this.audit.unshift(audit);
    if (this.audit.length > 30) {
      this.audit.splice(30);
    }
    this.render();
  }

  private handleRawMessage(message: ServerMessage): void {
    if (message.type !== 'engine_edit_commit_ack') {
      return;
    }
    const ack = message as EngineEditCommitAckMessage;
    const item = this.audit.find(candidate => candidate.ts === ack.audit_ts);
    const key = item ? auditKey(item) : '';
    if (key) {
      this.committing.delete(key);
    }
    if (ack.accepted) {
      if (key) {
        this.committed.add(key);
      }
      this.commitStatus = `Saved preview edit to the project (${ack.cgs_hash ?? 'new hash'}).`;
    } else {
      this.commitStatus = ack.reason || 'Could not save that preview edit.';
    }
    this.render();
  }

  private runtimeEntityId(actor: CGSActor): number | null {
    const entities = this.deps.client.runtimeStatus.lastTick?.entities ?? [];
    const found = entities.find(entity => (
      entity.actor_id === actor.id || String(entity.id) === actor.id
    ));
    return found?.id ?? null;
  }

  private runtimeHasComponent(entityId: number, componentTypeId: number): boolean {
    const entity = this.deps.client.runtimeStatus.lastTick?.entities?.find(item => item.id === entityId);
    return Boolean(entity?.components?.[String(componentTypeId)]);
  }

  private shouldAutoOpen(component: CGSComponent): boolean {
    return component.name.includes('HEALTH') || component.name.includes('TRANSFORM');
  }

  private componentUsage(typeId: number): LocatedComponentUsage {
    let readers = 0;
    let writers = 0;
    for (const { system } of allSystems(this.deps.cgsStore.cgs)) {
      if (system.reads.includes(typeId)) readers += 1;
      if (system.writes.includes(typeId)) writers += 1;
    }
    return { readers, writers };
  }
}

function prefillPrompt(text: string): void {
  window.dispatchEvent(new CustomEvent('xace:prefill-prompt', { detail: { text } }));
}

async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard?.writeText(value);
  } catch {
    prefillPrompt(value);
  }
}

function formatValue(value: CGSFieldValue): string {
  if (typeof value === 'string') return `"${value}"`;
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === 'boolean') return String(value);
  if (value === null) return 'null';
  return JSON.stringify(value);
}

function isPrimitiveEditable(value: CGSFieldValue): boolean {
  return typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean';
}

function canCommitAudit(item: EngineEditAuditEntry): item is EngineEditAuditEntry & {
  mode_id: string;
  actor_id: string;
  component_type_id: number;
  field_path: string;
} {
  return item.accepted
    && item.kind === 'set_component_field'
    && Boolean(item.mode_id)
    && Boolean(item.actor_id)
    && typeof item.component_type_id === 'number'
    && Boolean(item.field_path)
    && (typeof item.value === 'number' || typeof item.value === 'string' || typeof item.value === 'boolean');
}

function auditKey(item: EngineEditAuditEntry): string {
  return [
    item.ts,
    item.mode_id ?? '',
    item.actor_id ?? '',
    item.component_type_id ?? '',
    item.field_path ?? '',
    JSON.stringify(item.value),
  ].join(':');
}

function promptForValue(field: string, current: CGSFieldValue): { cancelled: true } | { cancelled: false; value: unknown } {
  const raw = window.prompt(`Live preview value for ${field}`, primitivePromptValue(current));
  if (raw === null) {
    return { cancelled: true };
  }
  if (typeof current === 'number') {
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      window.alert('Please enter a valid number.');
      return { cancelled: true };
    }
    return { cancelled: false, value };
  }
  if (typeof current === 'boolean') {
    const normalized = raw.trim().toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(normalized)) {
      return { cancelled: false, value: true };
    }
    if (['false', '0', 'no', 'off'].includes(normalized)) {
      return { cancelled: false, value: false };
    }
    window.alert('Please enter true or false.');
    return { cancelled: true };
  }
  return { cancelled: false, value: raw };
}

function primitivePromptValue(value: CGSFieldValue): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function injectStyles(): void {
  if (document.getElementById('xb-ins-styles')) return;
  const style = document.createElement('style');
  style.id = 'xb-ins-styles';
  style.textContent = STYLES;
  document.head.appendChild(style);
}

function escapeHtml(value: string): string {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
}
