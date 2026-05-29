/**
 * search_engine.ts — CGS Search Engine
 *
 * Indexes CGS nodes (actors, systems, rules, components, versions)
 * on load and on every CGS update. Provides fuzzy ranked search
 * for the command palette.
 *
 * No external dependencies — pure TypeScript string matching.
 * Fast enough for CGS graphs up to ~500 nodes without a worker.
 *
 * Ranking: exact prefix match > contains > fuzzy (edit distance).
 * Results capped at 12 for keyboard navigation performance.
 */

import type { CGS }         from '@/types/cgs';
import { allActors, allSystems } from '@/types/cgs';

// ── Result types ──────────────────────────────────────────────────────────────

export type SearchResultKind =
  | 'actor'
  | 'component'
  | 'system'
  | 'rule'
  | 'version'
  | 'action';

export interface SearchResult {
  readonly id:       string;
  readonly kind:     SearchResultKind;
  readonly label:    string;
  readonly subLabel: string;
  readonly score:    number;
  readonly modeId?:  string;
  /** Pre-built action — what happens when this result is selected */
  readonly action:   () => void;
}

// ── Indexed item ──────────────────────────────────────────────────────────────

interface IndexedItem {
  id:         string;
  kind:       SearchResultKind;
  label:      string;
  subLabel:   string;
  keywords:   string[];   // all searchable strings, lowercased
  modeId?:    string;
  action:     () => void;
}

// ── Search Engine ─────────────────────────────────────────────────────────────

export class CGSSearchEngine {
  private _index: IndexedItem[] = [];

  /**
   * Rebuilds the full search index from a CGS.
   * Call on session_init and on every cgs_update.
   */
  buildIndex(
    cgs:              CGS,
    onSelect:         (result: SearchResult) => void,
    prefillPromptFn?: (text: string) => void,
  ): void {
    const items: IndexedItem[] = [];

    // ── Built-in actions ──────────────────────────────────────────────────
    const actions: Array<{ label: string; subLabel: string; text: string }> = [
      { label: 'Add actor',        subLabel: 'action', text: 'Add a new actor: ' },
      { label: 'Add system',       subLabel: 'action', text: 'Add a new system: ' },
      { label: 'Add rule',         subLabel: 'action', text: 'Add a new rule: ' },
      { label: 'Explain CGS',      subLabel: 'action', text: 'Explain how the current CGS works' },
      { label: 'Balance difficulty', subLabel: 'action', text: 'Adjust the overall game difficulty: ' },
    ];
    for (const a of actions) {
      items.push({
        id:       `action:${a.label}`,
        kind:     'action',
        label:    a.label,
        subLabel: a.subLabel,
        keywords: [a.label.toLowerCase()],
        action:   () => prefillPromptFn?.(a.text),
      });
    }

    // ── Actors ───────────────────────────────────────────────────────────
    for (const { actor, modeId } of allActors(cgs)) {
      const nodeId = `actor:${modeId}:${actor.id}`;
      items.push({
        id:       nodeId,
        kind:     'actor',
        label:    actor.id,
        subLabel: `${actor.actor_type} · ${modeId}`,
        modeId,
        keywords: [actor.id.toLowerCase(), actor.actor_type.toLowerCase()],
        action:   () => onSelect({
          id: nodeId, kind: 'actor', label: actor.id,
          subLabel: actor.actor_type, score: 1, modeId,
          action: () => {},
        }),
      });

      // Components
      for (const comp of actor.components) {
        const compId = `comp:${comp.type_id}`;
        items.push({
          id:       compId,
          kind:     'component',
          label:    comp.name,
          subLabel: `type_id=${comp.type_id} on ${actor.id}`,
          modeId,
          keywords: [comp.name.toLowerCase(), `type_id:${comp.type_id}`],
          action:   () => onSelect({
            id: compId, kind: 'component', label: comp.name,
            subLabel: actor.id, score: 1,
            action: () => {},
          }),
        });
      }
    }

    // ── Systems ───────────────────────────────────────────────────────────
    for (const { system, modeId } of allSystems(cgs)) {
      const nodeId = `sys:${modeId}:${system.id}`;
      items.push({
        id:       nodeId,
        kind:     'system',
        label:    system.id,
        subLabel: `${system.phase} · ${modeId}`,
        modeId,
        keywords: [system.id.toLowerCase(), system.phase.toLowerCase()],
        action:   () => onSelect({
          id: nodeId, kind: 'system', label: system.id,
          subLabel: system.phase, score: 1, modeId,
          action: () => {},
        }),
      });
    }

    // ── Rules ─────────────────────────────────────────────────────────────
    for (const mode of cgs.modes) {
      for (const rule of mode.rules) {
        const nodeId = `rule:${mode.id}:${rule.id}`;
        items.push({
          id:       nodeId,
          kind:     'rule',
          label:    rule.id,
          subLabel: `when ${rule.condition}`,
          modeId:   mode.id,
          keywords: [rule.id.toLowerCase(), rule.condition.toLowerCase(), rule.effect.toLowerCase()],
          action:   () => onSelect({
            id: nodeId, kind: 'rule', label: rule.id,
            subLabel: rule.condition, score: 1, modeId: mode.id,
            action: () => {},
          }),
        });
      }
    }

    this._index = items;
  }

  /**
   * Search the index. Returns up to 12 ranked results.
   * Empty query returns the top built-in actions.
   */
  search(query: string): SearchResult[] {
    if (!query.trim()) {
      return this._index
        .filter(i => i.kind === 'action')
        .slice(0, 6)
        .map(i => this._toResult(i, 1.0));
    }

    const q = query.toLowerCase().trim();

    const scored: Array<{ item: IndexedItem; score: number }> = [];

    for (const item of this._index) {
      let best = 0;
      for (const kw of item.keywords) {
        let s = 0;
        if (kw === q)                s = 1.00;
        else if (kw.startsWith(q))   s = 0.90;
        else if (kw.includes(q))     s = 0.75;
        else {
          const fuzz = fuzzyScore(q, kw);
          if (fuzz > 0.4) s = fuzz * 0.6;
        }
        if (s > best) best = s;
      }
      if (best > 0) scored.push({ item, score: best });
    }

    // Sort: score DESC, then label length ASC (shorter = more specific)
    scored.sort((a, b) =>
      b.score !== a.score
        ? b.score - a.score
        : a.item.label.length - b.item.label.length,
    );

    return scored.slice(0, 12).map(({ item, score }) => this._toResult(item, score));
  }

  private _toResult(item: IndexedItem, score: number): SearchResult {
    return {
      id:       item.id,
      kind:     item.kind,
      label:    item.label,
      subLabel: item.subLabel,
      score,
      modeId:   item.modeId,
      action:   item.action,
    };
  }

  get indexSize(): number { return this._index.length; }
}

// ── Fuzzy scoring (simplified Levenshtein ratio) ──────────────────────────────

function fuzzyScore(needle: string, haystack: string): number {
  if (needle.length > haystack.length + 2) return 0;
  let matches = 0;
  let hi = 0;
  for (let ni = 0; ni < needle.length; ni++) {
    const ch = needle[ni];
    while (hi < haystack.length && haystack[hi] !== ch) hi++;
    if (hi < haystack.length) { matches++; hi++; }
  }
  return matches / Math.max(needle.length, haystack.length);
}