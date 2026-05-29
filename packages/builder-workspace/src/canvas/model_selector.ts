/**
 * model_selector.ts - Model Selector Dropdown
 *
 * Local test surface:
 *   - Auto: server chooses the best available local Ollama model
 *   - llama3.2
 *   - llama3.1
 */

import type { BuilderClient } from '../api/builder_client';

const STYLES = `
.xb-ms-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: rgba(255,255,255,.04);
  border: 1px solid var(--bd);
  border-radius: 4px;
  cursor: pointer;
  font-size: 9.5px;
  color: var(--txt2);
  font-family: inherit;
  white-space: nowrap;
  transition: all var(--tr-f);
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  position: relative;
}
.xb-ms-btn:hover { border-color: var(--bdh); color: var(--txt); }
.xb-ms-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.xb-ms-dot.healthy { background: var(--grn); }
.xb-ms-dot.unhealthy { background: var(--red); }
.xb-ms-dot.loading { background: var(--amb); animation: pulse-dot 1s ease-in-out infinite; color: var(--amb); }
.xb-ms-drop {
  position: fixed;
  background: var(--bga);
  border: 1px solid var(--bdh);
  border-radius: var(--r);
  min-width: 240px;
  max-width: 300px;
  z-index: 600;
  padding: 6px;
  box-shadow: 0 8px 32px rgba(0,0,0,.5);
  animation: fade-in 100ms ease-out;
}
.xb-ms-section {
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--txt3);
  padding: 4px 6px 2px;
}
.xb-ms-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 7px;
  border-radius: var(--rs);
  cursor: pointer;
  transition: background var(--tr-f);
}
.xb-ms-row:hover { background: rgba(255,255,255,.05); }
.xb-ms-row.active { background: var(--cynd); }
.xb-ms-model-name {
  flex: 1;
  font-size: 10.5px;
  color: var(--txt);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
}
.xb-ms-row.active .xb-ms-model-name { color: var(--cyan); font-weight: 600; }
.xb-ms-model-sub {
  font-size: 9px;
  color: var(--txt3);
  white-space: nowrap;
}
.xb-ms-divider {
  height: 1px;
  background: var(--bd);
  margin: 5px 0;
}
.xb-ms-tip {
  font-size: 9px;
  color: var(--txt3);
  padding: 3px 7px 4px;
  line-height: 1.6;
}
.xb-ms-footer {
  padding: 4px 6px;
  font-size: 9px;
  color: var(--txt3);
  display: flex;
  align-items: center;
  gap: 5px;
}
.xb-ms-refresh {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--txt3);
  cursor: pointer;
  font-size: 9px;
  padding: 0 2px;
  transition: color var(--tr-f);
  font-family: inherit;
}
.xb-ms-refresh:hover { color: var(--txt2); }
`;

interface ModelInfo {
  provider: string;
  models: string[];
  current: string;
  healthy: boolean;
  url: string;
}

interface ModelRow {
  provider: string;
  model: string;
  sub: string;
}

export class ModelSelector {
  private readonly _client: BuilderClient;
  private _btn!: HTMLButtonElement;
  private _info: ModelInfo = {
    provider: 'auto',
    models: [],
    current: 'loading...',
    healthy: false,
    url: '',
  };
  private _open = false;
  private _drop: HTMLElement | null = null;

  constructor(client: BuilderClient) {
    this._client = client;
    this._injectStyles();
  }

  mount(container: HTMLElement): HTMLButtonElement {
    this._btn = document.createElement('button');
    this._btn.className = 'xb-ms-btn';
    this._renderBtn();
    this._btn.addEventListener('click', (e) => {
      e.stopPropagation();
      this._open ? this._close() : this._openDrop();
    });
    container.appendChild(this._btn);
    this._fetchModels();
    return this._btn;
  }

  private _renderBtn(): void {
    const dotClass = this._info.current === 'loading...'
      ? 'loading'
      : this._info.healthy ? 'healthy' : 'unhealthy';
    const label = this._info.current.length > 16
      ? this._info.current.slice(0, 15) + '...'
      : this._info.current;
    this._btn.innerHTML = `<div class="xb-ms-dot ${dotClass}"></div>${label}`;
    this._btn.title = `Model: ${this._info.current} (${this._info.provider})`;
  }

  private async _fetchModels(): Promise<void> {
    try {
      const resp = await fetch('/api/models');
      if (resp.ok) {
        this._info = await resp.json() as ModelInfo;
        this._renderBtn();
      }
    } catch {
      this._info.current = 'no server';
      this._renderBtn();
    }
  }

  private _openDrop(): void {
    this._open = true;
    const drop = document.createElement('div');
    drop.className = 'xb-ms-drop';

    const rect = this._btn.getBoundingClientRect();
    drop.style.bottom = `${window.innerHeight - rect.top + 6}px`;
    drop.style.left = `${rect.left}px`;

    this._renderDrop(drop);
    document.body.appendChild(drop);
    this._drop = drop;

    setTimeout(() => {
      document.addEventListener('click', this._onOutside, { once: true });
    }, 10);
  }

  private _renderDrop(drop: HTMLElement): void {
    drop.innerHTML = '';

    this._renderSection(drop, 'Auto', [
      { provider: 'auto', model: 'auto', sub: 'local best-fit' },
    ]);

    const div = document.createElement('div');
    div.className = 'xb-ms-divider';
    drop.appendChild(div);

    this._renderSection(
      drop,
      `Llama (Ollama)${!this._info.healthy ? ' - offline' : ''}`,
      this._localTestModels().map(model => ({
        provider: 'ollama',
        model,
        sub: 'local',
      })),
    );

    if (!this._info.healthy) {
      const tip = document.createElement('div');
      tip.className = 'xb-ms-tip';
      tip.innerHTML = `Install: <code style="color:var(--amb)">ollama pull llama3.2</code><br>Start: <code style="color:var(--amb)">ollama serve</code>`;
      drop.appendChild(tip);
    }

    const footer = document.createElement('div');
    footer.className = 'xb-ms-footer';
    footer.innerHTML = `<span>${this._info.provider} - ${this._info.url}</span>`;
    const refreshBtn = document.createElement('button');
    refreshBtn.className = 'xb-ms-refresh';
    refreshBtn.textContent = 'refresh';
    refreshBtn.title = 'Refresh model list';
    refreshBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      refreshBtn.style.color = 'var(--cyan)';
      await this._fetchModels();
      this._close();
      setTimeout(() => this._openDrop(), 50);
    });
    footer.appendChild(refreshBtn);
    drop.appendChild(footer);
  }

  private _renderSection(drop: HTMLElement, label: string, rows: ModelRow[]): void {
    const sec = document.createElement('div');
    sec.className = 'xb-ms-section';
    sec.textContent = label;
    drop.appendChild(sec);

    for (const item of rows) {
      const isActive = item.provider === this._info.provider && item.model === this._info.current;
      const row = document.createElement('div');
      row.className = `xb-ms-row${isActive ? ' active' : ''}`;

      const modelName = document.createElement('span');
      modelName.className = 'xb-ms-model-name';
      modelName.textContent = item.model;
      row.appendChild(modelName);

      const sub = document.createElement('span');
      sub.className = 'xb-ms-model-sub';
      sub.textContent = isActive ? 'active' : item.sub;
      row.appendChild(sub);

      row.addEventListener('click', () => this._selectModel(item.provider, item.model));
      drop.appendChild(row);
    }
  }

  private _localTestModels(): string[] {
    const installed = this._info.models.filter(model =>
      model.startsWith('llama3.2') || model.startsWith('llama3.1')
    );
    return Array.from(new Set(['llama3.2', 'llama3.1', ...installed]));
  }

  private _selectModel(provider: string, model: string): void {
    this._info.provider = provider;
    this._info.current = model;
    this._renderBtn();
    this._close();

    this._client.send({
      type: 'model_change',
      provider,
      model,
      session_id: this._client.sessionId,
    });

    window.dispatchEvent(new CustomEvent('xace:model-changed', {
      detail: { provider, model },
    }));
  }

  private _close(): void {
    this._open = false;
    this._drop?.remove();
    this._drop = null;
  }

  private _onOutside = (): void => { this._close(); };

  private _injectStyles(): void {
    if (document.getElementById('xb-ms-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-ms-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}
