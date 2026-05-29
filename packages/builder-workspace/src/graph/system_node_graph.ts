/**
 * system_node_graph.ts — System Dependency Graph
 *
 * Specialized graph showing ONLY systems, arranged in horizontal phase lanes.
 * Used in the center "Schema Graph" tab when the system filter is active.
 *
 * Shows:
 *   - Systems grouped into phase swim-lanes: Input → Simulation → PostSim → Render
 *   - depends_on arrows as directed edges
 *   - reads/writes listed inside each node box
 *   - Hazard badge (!) when cascade risk detected (≥3 downstream systems)
 *   - Non-deterministic systems highlighted in red
 *   - Clicking a system box selects it in uiStore → populates entity inspector
 */

import type { CGSGraph, CGSGraphNode, LocatedSystem } from '../types/cgs';
import type { UIStore } from '../state/ui_store';
import type { CGSStore } from '../state/cgs_store';
import { allSystems } from '../types/cgs';

const PHASES = ['Input', 'Simulation', 'PostSimulation', 'Render'] as const;

const STYLES = `
.xb-sng {
  display:         flex;
  flex-direction:  column;
  height:          100%;
  overflow:        auto;
  position:        relative;
  gap:             0;
}
.xb-phase-lane {
  display:         flex;
  align-items:     flex-start;
  gap:             10px;
  padding:         10px 14px;
  border-bottom:   1px solid var(--bd);
  min-height:      64px;
  flex-shrink:     0;
}
.xb-phase-lane:nth-child(even) { background: rgba(255,255,255,.01); }
.xb-phase-lbl {
  font-size:       9px;
  font-weight:     700;
  letter-spacing:  .12em;
  text-transform:  uppercase;
  color:           var(--txt3);
  width:           90px;
  flex-shrink:     0;
  padding-top:     12px;
}
.xb-phase-nodes {
  display:         flex;
  flex-wrap:       wrap;
  gap:             8px;
  flex:            1;
}
.xb-sys-node {
  background:      rgba(168,85,247,.07);
  border:          1px solid rgba(168,85,247,.22);
  border-radius:   var(--r);
  padding:         6px 10px;
  min-width:       120px;
  cursor:          pointer;
  transition:      all var(--tr);
  position:        relative;
}
.xb-sys-node:hover {
  background:      rgba(168,85,247,.14);
  border-color:    rgba(168,85,247,.45);
  transform:       translateY(-1px);
}
.xb-sys-node.selected {
  border-color:    var(--vlt);
  box-shadow:      0 0 0 2px rgba(168,85,247,.2);
}
.xb-sys-node.non-det {
  border-color:    rgba(239,68,68,.35);
  background:      rgba(239,68,68,.05);
}
.xb-sys-node.highlighted {
  border-color:    var(--amb);
  background:      rgba(255,159,67,.08);
  box-shadow:      0 0 8px rgba(255,159,67,.25);
}
.xb-sys-name {
  font-size:       11px;
  font-weight:     600;
  color:           var(--txt);
  margin-bottom:   4px;
  display:         flex;
  align-items:     center;
  gap:             5px;
}
.xb-hazard-badge {
  width:           14px;
  height:          14px;
  border-radius:   50%;
  background:      var(--amb);
  color:           #000;
  font-size:       8px;
  font-weight:     700;
  display:         flex;
  align-items:     center;
  justify-content: center;
  flex-shrink:     0;
}
.xb-sys-rw {
  display:         flex;
  gap:             8px;
  font-size:       9px;
  color:           var(--txt2);
  font-family:     var(--font-mono);
}
.xb-rw-reads  { color: rgba(59,139,212,.9); }
.xb-rw-writes { color: rgba(168,85,247,.9); }
.xb-sys-deps {
  font-size:       8.5px;
  color:           var(--txt3);
  margin-top:      3px;
}
.xb-empty-lane {
  font-size:       9.5px;
  color:           var(--txt3);
  font-style:      italic;
  padding-top:     12px;
}
.xb-sng-header {
  padding:         7px 14px;
  border-bottom:   1px solid var(--bd);
  display:         flex;
  align-items:     center;
  gap:             8px;
  flex-shrink:     0;
  font-size:       9px;
  color:           var(--txt2);
}
.xb-sng-title {
  font-weight:     700;
  letter-spacing:  .1em;
  text-transform:  uppercase;
  color:           var(--vlt);
}
.xb-sng-count { margin-left: auto; }
.xb-legend-item {
  display:         flex;
  align-items:     center;
  gap:             4px;
}
.xb-legend-dot {
  width:           7px;
  height:          7px;
  border-radius:   50%;
}
`;

interface SystemNodeGraphDeps {
  uiStore:  UIStore;
  cgsStore: CGSStore;
}

export class SystemNodeGraph {
  private readonly _deps: SystemNodeGraphDeps;
  private _el!:           HTMLElement;
  private _nodesContainer!: HTMLElement;
  private readonly _unsubs: Array<() => void> = [];
  private _highlightedIds: Set<string> = new Set();

  constructor(deps: SystemNodeGraphDeps) {
    this._deps = deps;
    this._injectStyles();
  }

  mount(container: HTMLElement): void {
    this._el = this._build();
    container.appendChild(this._el);

    this._unsubs.push(
      this._deps.cgsStore.subscribe(() => this._render()),
      this._deps.uiStore.subscribe(() => this._updateSelection()),
    );
  }

  unmount(): void {
    this._unsubs.forEach(fn => fn());
    this._el?.remove();
  }

  setHighlighted(ids: Set<string>): void {
    this._highlightedIds = ids;
    this._render();
  }

  private _build(): HTMLElement {
    const root = document.createElement('div');
    root.className = 'xb-sng';

    const header = document.createElement('div');
    header.className = 'xb-sng-header';
    header.innerHTML = `
      <span class="xb-sng-title">System Execution Graph</span>
      <div class="xb-legend-item">
        <div class="xb-legend-dot" style="background:rgba(168,85,247,.7)"></div>
        <span>System</span>
      </div>
      <div class="xb-legend-item">
        <div class="xb-legend-dot" style="background:var(--amb)"></div>
        <span>Cascade risk</span>
      </div>
      <div class="xb-legend-item">
        <div class="xb-legend-dot" style="background:var(--red)"></div>
        <span>Non-deterministic</span>
      </div>
      <span class="xb-sng-count" id="sng-count">0 systems</span>
    `;
    root.appendChild(header);

    this._nodesContainer = document.createElement('div');
    this._nodesContainer.style.cssText = 'flex:1;overflow-y:auto;display:flex;flex-direction:column';
    root.appendChild(this._nodesContainer);

    return root;
  }

  private _render(): void {
    const cgs          = this._deps.cgsStore.cgs;
    const allSys       = allSystems(cgs);
    const selectedId   = this._deps.uiStore.selectedEntity?.id;

    // Count downstream dependencies for cascade risk detection
    const downstreamCount = this._computeCascadeDepth(allSys);

    this._nodesContainer.innerHTML = '';

    let total = 0;

    for (const phase of PHASES) {
      const lane     = document.createElement('div');
      lane.className = 'xb-phase-lane';

      const lbl = document.createElement('div');
      lbl.className   = 'xb-phase-lbl';
      lbl.textContent = phase;
      lane.appendChild(lbl);

      const nodes = document.createElement('div');
      nodes.className = 'xb-phase-nodes';

      const phaseSystems = allSys.filter(
        ({ system }) => system.phase === phase
      );
      total += phaseSystems.length;

      if (phaseSystems.length === 0) {
        const empty = document.createElement('span');
        empty.className   = 'xb-empty-lane';
        empty.textContent = 'No systems in this phase';
        nodes.appendChild(empty);
      } else {
        for (const { system, modeId } of phaseSystems) {
          const nodeId     = `sys:${modeId}:${system.id}`;
          const cascade    = (downstreamCount.get(system.id) ?? 0) >= 3;
          const isNonDet   = !system.deterministic;
          const isSelected = selectedId === nodeId;
          const isHigh     = this._highlightedIds.has(nodeId);

          const box = document.createElement('div');
          box.className = [
            'xb-sys-node',
            isSelected ? 'selected'    : '',
            isNonDet   ? 'non-det'    : '',
            isHigh     ? 'highlighted' : '',
          ].filter(Boolean).join(' ');

          const name = document.createElement('div');
          name.className = 'xb-sys-name';
          name.textContent = system.id;

          if (cascade) {
            const badge = document.createElement('div');
            badge.className   = 'xb-hazard-badge';
            badge.textContent = '!';
            badge.title       = `${downstreamCount.get(system.id)} systems downstream — cascade risk`;
            name.appendChild(badge);
          }

          box.appendChild(name);

          const rw = document.createElement('div');
          rw.className = 'xb-sys-rw';
          rw.innerHTML = `
            <span class="xb-rw-reads">R: [${system.reads.join(',')}]</span>
            <span class="xb-rw-writes">W: [${system.writes.join(',')}]</span>
          `;
          box.appendChild(rw);

          if (system.depends_on.length > 0) {
            const deps = document.createElement('div');
            deps.className   = 'xb-sys-deps';
            deps.textContent = `→ ${system.depends_on.join(', ')}`;
            box.appendChild(deps);
          }

          box.addEventListener('click', () => {
            this._deps.uiStore.selectEntity({
              id:     nodeId,
              kind:   'system',
              label:  system.id,
              modeId: modeId,
            });
          });

          // Right-click
          box.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent('xace:explain-node', {
              detail: { nodeId, nodeLabel: system.id },
            }));
          });

          nodes.appendChild(box);
        }
      }

      lane.appendChild(nodes);
      this._nodesContainer.appendChild(lane);
    }

    const countEl = document.getElementById('sng-count');
    if (countEl) countEl.textContent = `${total} system${total !== 1 ? 's' : ''}`;
  }

  private _updateSelection(): void {
    // Re-render to update selected state (lightweight enough)
    this._render();
  }

  private _computeCascadeDepth(
    systems: Array<import('../types/cgs').LocatedSystem>,
  ): Map<string, number> {
    // BFS from each system — count how many systems depend on it transitively
    const downstreamCount = new Map<string, number>();

    for (const { system } of systems) {
      let count = 0;
      const visited = new Set<string>();
      const queue   = [system.id];

      while (queue.length > 0) {
        const id  = queue.shift()!;
        if (visited.has(id)) continue;
        visited.add(id);
        for (const { system: other } of systems) {
          if ((other.depends_on as readonly string[]).includes(id) && !visited.has(other.id)) {
            count++;
            queue.push(other.id);
          }
        }
      }
      downstreamCount.set(system.id, count);
    }

    return downstreamCount;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-sng-styles')) return;
    const s = document.createElement('style');
    s.id = 'xb-sng-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }
}