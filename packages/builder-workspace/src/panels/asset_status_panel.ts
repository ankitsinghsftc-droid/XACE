/**
 * asset_status_panel.ts — Asset Status Panel
 *
 * Shows three counts: placeholder / linked / missing
 * and a "Link Assets →" button that opens the AssetLinkDialog.
 *
 * Reads from cgsStore.assetStatusSummary (derived from CGS defaults
 * fields ending in _id, _path, or _ref).
 *
 * The "game runs as grey boxes" message is shown when all assets
 * are placeholder — this is normal and expected in early design.
 */

import type { CGSStore }    from '../state/cgs_store';
import type { UIStore }     from '../state/ui_store';
import type { BuilderClient } from '../api/builder_client';

const STYLES = `
.xb-asp { padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
.xb-asp-row { display: flex; align-items: center; gap: 6px; font-size: 10.5px; }
.xb-asp-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.xb-asp-lbl { color: var(--txt2); flex: 1; }
.xb-asp-cnt { font-weight: 600; font-family: var(--font-mono); }
.xb-asp-btn {
  margin-top: 6px; width: 100%; background: rgba(255,255,255,.03);
  border: 1px solid var(--bd); border-radius: var(--rs); color: var(--txt2);
  font-size: 10px; padding: 5px; cursor: pointer; transition: all var(--tr-f); font-family: inherit;
}
.xb-asp-btn:hover { border-color: rgba(0,212,255,.3); color: var(--cyan); background: var(--cynd); }
.xb-asp-note {
  font-size: 9px; color: var(--txt3); font-style: italic; line-height: 1.5;
  padding: 5px 0;
}
`;

interface AssetPanelDeps {
  cgsStore: CGSStore;
  uiStore:  UIStore;
  client:   BuilderClient;
}

export class AssetStatusPanel {
  private readonly _deps:  AssetPanelDeps;
  private _el!:            HTMLElement;
  private _dialog:         AssetLinkDialog | null = null;
  private readonly _unsubs: Array<() => void> = [];

  constructor(deps: AssetPanelDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = document.createElement('div');
    this._el.className = 'xb-asp';
    container.appendChild(this._el);
    this._unsubs.push(this._deps.cgsStore.subscribe(() => this._render()));
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn()); this._el?.remove();
  }

  private _render(): void {
    const { linked, placeholder, missing } = this._deps.cgsStore.assetStatusSummary;
    const total   = linked + placeholder + missing;
    const allPlaceholder = total > 0 && placeholder === total;

    this._el.innerHTML = '';

    const rows = [
      { color: 'var(--amb)', label: 'Placeholder', count: placeholder, countColor: 'var(--amb)' },
      { color: 'var(--grn)', label: 'Linked',      count: linked,      countColor: 'var(--grn)' },
      { color: 'var(--txt3)',label: 'Missing',      count: missing,     countColor: missing > 0 ? 'var(--red)' : 'var(--txt3)' },
    ];

    for (const row of rows) {
      const r = document.createElement('div');
      r.className = 'xb-asp-row';
      r.innerHTML = `
        <div class="xb-asp-dot" style="background:${row.color}"></div>
        <span class="xb-asp-lbl">${row.label}</span>
        <span class="xb-asp-cnt" style="color:${row.countColor}">${row.count}</span>
      `;
      this._el.appendChild(r);
    }

    if (allPlaceholder) {
      const note = document.createElement('div');
      note.className   = 'xb-asp-note';
      note.textContent = 'Game currently runs with grey box placeholders. Link real assets when art is ready.';
      this._el.appendChild(note);
    }

    const btn = document.createElement('button');
    btn.className   = 'xb-asp-btn';
    btn.textContent = 'Link Assets ->';
    btn.addEventListener('click', () => this._openDialog());
    this._el.appendChild(btn);
  }

  private _openDialog(): void {
    if (this._dialog) return;
    this._dialog = new AssetLinkDialog({
      cgsStore: this._deps.cgsStore,
      client:   this._deps.client,
      onClose:  () => { this._dialog = null; },
    });
    this._dialog.open();
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-asp-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-asp-styles'; s.textContent = STYLES;
    document.head.appendChild(s);
  }
}


/**
 * asset_link_dialog.ts — Asset Linking File Browser Dialog
 *
 * Modal dialog: lists all placeholder asset refs from CGS.
 * For each placeholder, shows a file input so the designer can
 * browse to the local file and link it.
 *
 * On link: sends `asset_link` WebSocket message → builder_server writes
 * the path into the CGS and persists. No backend processing required.
 *
 * Design: file:// paths are stored as-is. The engine adapter (Phase 15)
 * resolves them relative to the project root at load time.
 */

const DIALOG_STYLES = `
.xb-ald-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.65);
  display: flex; align-items: center; justify-content: center;
  z-index: 900; backdrop-filter: blur(4px);
}
.xb-ald-modal {
  background: var(--bgc); border: 1px solid var(--bdh); border-radius: var(--rl);
  width: 520px; max-width: 94vw; max-height: 80vh; display: flex;
  flex-direction: column; overflow: hidden; animation: fade-in 150ms ease-out;
}
.xb-ald-head {
  padding: 14px 16px 10px; border-bottom: 1px solid var(--bd);
  display: flex; align-items: center;
}
.xb-ald-title { font-size: 13px; font-weight: 600; color: var(--txt); flex: 1; }
.xb-ald-close {
  width: 24px; height: 24px; background: transparent; border: none;
  color: var(--txt2); font-size: 16px; cursor: pointer; border-radius: 3px;
  display: flex; align-items: center; justify-content: center; transition: all 100ms;
}
.xb-ald-close:hover { background: rgba(255,255,255,.05); color: var(--txt); }
.xb-ald-body { flex: 1; overflow-y: auto; padding: 10px 14px; display: flex; flex-direction: column; gap: 10px; }
.xb-ald-item {
  background: var(--bgp); border: 1px solid var(--bd); border-radius: var(--r);
  padding: 10px 12px; display: flex; flex-direction: column; gap: 6px;
}
.xb-ald-item-head { display: flex; align-items: center; gap: 8px; }
.xb-ald-status-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.xb-ald-id { font-family: var(--font-mono); font-size: 11px; color: var(--txt); flex: 1; }
.xb-ald-comp { font-size: 9.5px; color: var(--txt2); font-family: var(--font-mono); }
.xb-ald-path-row { display: flex; gap: 6px; align-items: center; }
.xb-ald-path-inp {
  flex: 1; background: rgba(255,255,255,.03); border: 1px solid var(--bd);
  border-radius: var(--rs); padding: 4px 8px; color: var(--txt2); font-size: 10px;
  font-family: var(--font-mono); outline: none; transition: border-color var(--tr-f);
}
.xb-ald-path-inp:focus { border-color: var(--cyan); color: var(--txt); }
.xb-ald-browse {
  font-size: 9.5px; padding: 4px 10px; background: rgba(255,255,255,.04);
  border: 1px solid var(--bd); border-radius: var(--rs); color: var(--txt2);
  cursor: pointer; font-family: inherit; white-space: nowrap; transition: all 100ms;
}
.xb-ald-browse:hover { border-color: var(--bdh); color: var(--txt); }
.xb-ald-link-btn {
  font-size: 9.5px; padding: 4px 10px;
  background: rgba(16,185,129,.08); border: 1px solid rgba(16,185,129,.25);
  border-radius: var(--rs); color: var(--grn); cursor: pointer;
  font-family: inherit; transition: all 100ms;
}
.xb-ald-link-btn:hover { background: rgba(16,185,129,.15); border-color: var(--grn); }
.xb-ald-empty { padding: 20px; text-align: center; font-size: 10.5px; color: var(--txt2); }
.xb-ald-foot { padding: 10px 14px; border-top: 1px solid var(--bd); display: flex; justify-content: flex-end; }
.xb-ald-done {
  padding: 5px 16px; background: var(--cynd); border: 1px solid rgba(0,212,255,.3);
  border-radius: var(--r); color: var(--cyan); font-size: 11px; font-weight: 600;
  cursor: pointer; font-family: inherit;
}
`;

interface DialogDeps {
  cgsStore: CGSStore;
  client:   BuilderClient;
  onClose:  () => void;
}

export class AssetLinkDialog {
  private readonly _deps: DialogDeps;
  private _overlay!: HTMLElement;

  constructor(deps: DialogDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  open(): void {
    this._overlay = document.createElement('div');
    this._overlay.className = 'xb-ald-overlay';
    this._overlay.appendChild(this._buildModal());
    document.body.appendChild(this._overlay);
    this._overlay.addEventListener('click', (e) => {
      if (e.target === this._overlay) this.close();
    });
  }

  close(): void {
    this._overlay?.remove();
    this._deps.onClose();
  }

  private _buildModal(): HTMLElement {
    const modal = document.createElement('div');
    modal.className = 'xb-ald-modal';

    // Header
    const head = document.createElement('div');
    head.className = 'xb-ald-head';
    head.innerHTML = `<div class="xb-ald-title">Link Assets</div>`;
    const closeBtn = document.createElement('button');
    closeBtn.className   = 'xb-ald-close';
    closeBtn.textContent = 'x';
    closeBtn.addEventListener('click', () => this.close());
    head.appendChild(closeBtn);
    modal.appendChild(head);

    // Body — list all asset refs
    const body = document.createElement('div');
    body.className = 'xb-ald-body';

    const refs = this._deps.cgsStore.assetRefs;
    if (refs.length === 0) {
      body.innerHTML = `<div class="xb-ald-empty">No asset references found in the CGS.<br><span style="color:var(--txt3);font-size:9.5px">Add mesh_id, texture_id, or audio_id fields to components to enable asset linking.</span></div>`;
    } else {
      for (const ref of refs) {
        body.appendChild(this._buildItem(ref));
      }
    }
    modal.appendChild(body);

    // Footer
    const foot = document.createElement('div');
    foot.className = 'xb-ald-foot';
    const done = document.createElement('button');
    done.className   = 'xb-ald-done';
    done.textContent = 'Done';
    done.addEventListener('click', () => this.close());
    foot.appendChild(done);
    modal.appendChild(foot);

    return modal;
  }

  private _buildItem(ref: import('../types/cgs').AssetRef): HTMLElement {
    const item = document.createElement('div');
    item.className = 'xb-ald-item';

    const statusColor = ref.status === 'linked' ? 'var(--grn)'
                      : ref.status === 'missing' ? 'var(--red)'
                      : 'var(--amb)';

    item.innerHTML = `
      <div class="xb-ald-item-head">
        <div class="xb-ald-status-dot" style="background:${statusColor}"></div>
        <span class="xb-ald-id">${ref.placeholder_id}</span>
        <span class="xb-ald-comp">${ref.component_name} · ${ref.actor_id}</span>
      </div>
    `;

    const pathRow = document.createElement('div');
    pathRow.className = 'xb-ald-path-row';

    const pathInp = document.createElement('input');
    pathInp.className   = 'xb-ald-path-inp';
    pathInp.type        = 'text';
    pathInp.placeholder = './assets/...';
    pathInp.value       = ref.asset_path ?? '';

    const browseBtn = document.createElement('button');
    browseBtn.className   = 'xb-ald-browse';
    browseBtn.textContent = 'Browse';
    browseBtn.addEventListener('click', () => {
      const fi = document.createElement('input');
      fi.type = 'file';
      fi.addEventListener('change', () => {
        if (fi.files?.[0]) {
          const file = fi.files[0];
          pathInp.value = file.webkitRelativePath || `./assets/${file.name}`;
        }
      });
      fi.click();
    });

    const linkBtn = document.createElement('button');
    linkBtn.className   = 'xb-ald-link-btn';
    linkBtn.textContent = 'Link';
    linkBtn.addEventListener('click', () => {
      const path = pathInp.value.trim();
      if (!path) return;
      this._deps.client.send({
        type:           'asset_link',
        placeholder_id: ref.placeholder_id,
        asset_path:     path,
        actor_id:       ref.actor_id,
        component_name: ref.component_name,
        session_id:     this._deps.client.sessionId,
      });
      linkBtn.textContent = 'Linked';
      linkBtn.style.color   = 'var(--grn)';
      linkBtn.style.background = 'rgba(16,185,129,.12)';
      setTimeout(() => {
        linkBtn.textContent = 'Link';
        linkBtn.style.color = '';
        linkBtn.style.background = '';
      }, 3000);
    });

    pathRow.appendChild(pathInp);
    pathRow.appendChild(browseBtn);
    pathRow.appendChild(linkBtn);
    item.appendChild(pathRow);

    return item;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-ald-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-ald-styles'; s.textContent = DIALOG_STYLES;
    document.head.appendChild(s);
  }
}
