"""
structural_memory.py — StructuralMemory
=========================================
Layer 2 of the 5-layer memory model. CACHED PREFIX.

Tracks the schema-level facts: which actors, components, systems, and
rules exist, and what their key properties are. Provides path resolution
assistance and duplicate prevention for the LLM mutation pipeline.

## Contents

    actors_known   : dict[actor_id → actor_type_str]
    components_known: dict[type_id → (name, fields)]
    systems_known  : dict[system_id → (reads, writes)]
    rules_known    : dict[rule_id → condition_summary]

## Why This Matters

    Without structural memory, the LLM has to re-learn from the CGS
    every call. With it, the cached prefix carries a stable fact table
    that helps the model:
        - Write correct actor_id references ("actor_zombie" not "zombie")
        - Know which component type_ids exist
        - Avoid proposing a new actor with an existing ID
        - Understand system R/W contracts at a glance

## Sync with CGS

    StructuralMemory is updated by MemoryLifecycleManager after each
    successful commit. It is NOT updated mid-pipeline.

## IN CACHED PREFIX (II9)
"""

from __future__ import annotations

from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
from memory_store import MemoryStore, MemoryLayer


class StructuralMemory:
    """
    Tracks the game's structural schema facts.

    Usage
    -----
        sm = StructuralMemory(store)
        sm.sync_from_cgs(cgs)
        sm.has_actor("actor_zombie")   # True
        sm.has_component_type(100)     # True
        prefix = sm.to_prefix_text()
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        # In-memory caches for fast lookup
        self._actors:     dict[str, str]             = {}   # actor_id → actor_type
        self._components: dict[int, dict[str, Any]]  = {}   # type_id → {name, fields}
        self._systems:    dict[str, dict[str, Any]]  = {}   # system_id → {reads, writes}
        self._rules:      dict[str, str]             = {}   # rule_id → condition_summary

    # ── Sync ─────────────────────────────────────────────────────────────────

    def sync_from_cgs(self, cgs: dict[str, Any]) -> None:
        """
        Rebuilds structural memory from the current CGS.
        Called by MemoryLifecycleManager after each successful commit.
        Clears the structural layer first, then re-populates.
        """
        # Clear existing structural entries
        self._store.clear_layer(MemoryLayer.STRUCTURAL)
        self._actors.clear()
        self._components.clear()
        self._systems.clear()
        self._rules.clear()

        # Index actors and components
        for mode in cgs.get("modes", []):
            mid = mode.get("id", "")
            for actor in mode.get("actors", []):
                aid    = actor.get("id", "")
                atype  = actor.get("actor_type", "")
                ctrl   = actor.get("control_type", "")
                self._actors[aid] = atype

                comp_ids = [c.get("type_id") for c in actor.get("components", [])]
                comp_names = [c.get("name", "") for c in actor.get("components", [])]
                self._store.add(
                    layer           = MemoryLayer.STRUCTURAL,
                    content         = (
                        f"Actor '{aid}' (type={atype}, control={ctrl}) "
                        f"in mode '{mid}' has components: "
                        f"{', '.join(f'{n}(id={i})' for i, n in zip(comp_ids, comp_names))}"
                    ),
                    relevance_score = 0.85,
                    tags            = {"actor", aid, mid},
                    metadata        = {"kind": "actor", "actor_id": aid, "mode_id": mid},
                )

                for comp in actor.get("components", []):
                    tid    = comp.get("type_id")
                    name   = comp.get("name", "")
                    fields = list(comp.get("defaults", {}).keys())
                    self._components[tid] = {"name": name, "fields": fields}

            # Index systems
            for sys in mode.get("systems", []):
                sid    = sys.get("id", "")
                reads  = sys.get("reads",  [])
                writes = sys.get("writes", [])
                deps   = sys.get("depends_on", [])
                self._systems[sid] = {"reads": reads, "writes": writes}
                self._store.add(
                    layer           = MemoryLayer.STRUCTURAL,
                    content         = (
                        f"System '{sid}' in mode '{mid}': "
                        f"reads=[{','.join(str(r) for r in reads)}] "
                        f"writes=[{','.join(str(w) for w in writes)}] "
                        f"depends_on=[{','.join(deps)}]"
                    ),
                    relevance_score = 0.80,
                    tags            = {"system", sid, mid},
                    metadata        = {"kind": "system", "system_id": sid},
                )

            # Index rules
            for rule in mode.get("rules", []):
                rid       = rule.get("id", "")
                condition = rule.get("condition", "")[:80]
                effect    = rule.get("effect",    "")[:60]
                self._rules[rid] = condition
                self._store.add(
                    layer           = MemoryLayer.STRUCTURAL,
                    content         = (
                        f"Rule '{rid}': when [{condition}] → {effect}"
                    ),
                    relevance_score = 0.75,
                    tags            = {"rule", rid, mid},
                    metadata        = {"kind": "rule", "rule_id": rid},
                )

        # Index global systems
        for gs in cgs.get("global_systems", []):
            sid = gs.get("id", "")
            self._systems[sid] = {
                "reads":  gs.get("reads",  []),
                "writes": gs.get("writes", []),
            }

    # ── Lookup ────────────────────────────────────────────────────────────────

    def has_actor(self, actor_id: str) -> bool:
        return actor_id in self._actors

    def has_component_type(self, type_id: int) -> bool:
        return type_id in self._components

    def has_system(self, system_id: str) -> bool:
        return system_id in self._systems

    def has_rule(self, rule_id: str) -> bool:
        return rule_id in self._rules

    @property
    def all_actor_ids(self) -> list[str]:
        return list(self._actors.keys())

    @property
    def all_component_type_ids(self) -> list[int]:
        return list(self._components.keys())

    @property
    def all_system_ids(self) -> list[str]:
        return list(self._systems.keys())

    @property
    def all_rule_ids(self) -> list[str]:
        return list(self._rules.keys())

    def component_fields(self, type_id: int) -> list[str]:
        return self._components.get(type_id, {}).get("fields", [])

    def component_name(self, type_id: int) -> str:
        return self._components.get(type_id, {}).get("name", "")

    # ── Prefix text ───────────────────────────────────────────────────────────

    def to_prefix_text(self) -> str:
        """Returns structural memory as formatted text for LLM cached prefix."""
        parts = ["=== STRUCTURAL MEMORY ==="]

        if self._actors:
            parts.append(f"Known actors: {', '.join(self._actors.keys())}")

        if self._components:
            comp_lines = [
                f"  type_id={tid}: {info['name']} "
                f"[fields: {', '.join(info['fields'][:5])}]"
                for tid, info in sorted(self._components.items())
            ]
            parts.append("Known components:\n" + "\n".join(comp_lines))

        if self._systems:
            parts.append(f"Known systems: {', '.join(sorted(self._systems.keys()))}")

        if self._rules:
            parts.append(f"Known rules: {', '.join(sorted(self._rules.keys()))}")

        parts.append("=== END STRUCTURAL MEMORY ===")
        return "\n".join(parts)

    @property
    def entry_count(self) -> int:
        return self._store.count(MemoryLayer.STRUCTURAL)