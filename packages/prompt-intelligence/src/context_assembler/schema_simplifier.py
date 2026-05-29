"""
schema_simplifier.py — SchemaSimplifier
==========================================
Produces a compact CGS slice for LLM context from the full CGS.

## Purpose

    The full CGS (Zombie Chase: ~2KB, large games: potentially hundreds of KB)
    must never be transmitted in full to the LLM (Audit 9: full schema
    transmission forbidden). SchemaSimplifier reduces it to only what is
    needed for the current intent, targeting ≥60% size reduction.

## Simplification Strategy

    1. Metadata — keep only name, version, schema_version.
       Strip cgs_hash (LLM doesn't need it; it's in the constraint prefix).

    2. Actors — for each actor relevant to the intent:
       - Keep actor_id, actor_type, control_type
       - For each component: keep type_id, name, and a FLAT summary of
         defaults (no nested objects — just key: value at top level)
       - Strip runtime-irrelevant fields (prefab_id, is_runtime_spawned,
         large nested quaternions reduced to a single rotation summary)

    3. Systems — keep system_id, phase, reads, writes, depends_on.
       Strip: description fields, extended metadata.

    4. Rules — keep rule_id, condition (truncated to 120 chars), effect
       (truncated to 80 chars), priority, is_active.

    5. Global systems — same simplification as per-mode systems.

    6. Non-relevant actors/systems/rules are OMITTED ENTIRELY.
       "Relevant" is determined by the relevance_extractor; SchemaSimplifier
       receives a pre-filtered list of IDs to include.

## Size Reduction Targets

    Component defaults:
        - Nested objects (position, rotation, scale) → one-line string summary
        - Boolean fields → kept as-is
        - Numeric fields → kept as-is (they are the mutation targets)
        - String fields longer than 40 chars → truncated

    Rotation quaternions:
        {"x":0.0,"y":0.0,"z":0.0,"w":1.0} → "identity"

    Zero vectors:
        {"x":0.0,"y":0.0,"z":0.0} → "zero"

## Output

    SimplifiedSchema dict with keys:
        metadata, actors, systems, rules, global_systems
    Each key contains only the simplified relevant elements.
"""

from __future__ import annotations

from typing import Any


# ── Simplification Constants ──────────────────────────────────────────────────

_MAX_CONDITION_LEN  = 120
_MAX_EFFECT_LEN     = 80
_MAX_STRING_LEN     = 40

# Known zero/identity patterns for compaction
_ZERO_VECTOR        = {"x": 0.0, "y": 0.0, "z": 0.0}
_IDENTITY_QUAT      = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
_UNIT_SCALE         = {"x": 1.0, "y": 1.0, "z": 1.0}


# ── Schema Simplifier ─────────────────────────────────────────────────────────

class SchemaSimplifier:
    """
    Reduces a full CGS to a compact slice for LLM context.

    Stateless — safe to share across sessions.
    Deterministic — same inputs always produce the same output.

    Usage
    -----
        simplifier = SchemaSimplifier()
        slim = simplifier.simplify(
            cgs,
            relevant_actor_ids={"actor_zombie"},
            relevant_system_ids={"AISystem", "MovementSystem"},
            relevant_rule_ids={"rule_zombie_death"},
        )
        # slim["actors"] → list of compacted actor dicts
    """

    def simplify(
        self,
        cgs:                  dict[str, Any],
        relevant_actor_ids:   set[str] | None = None,
        relevant_system_ids:  set[str] | None = None,
        relevant_rule_ids:    set[str] | None = None,
        include_all:          bool            = False,
    ) -> dict[str, Any]:
        """
        Produces a simplified CGS slice.

        Parameters
        ----------
        cgs : dict
            Full CGS JSON.
        relevant_actor_ids : set[str] | None
            Actor IDs to include. None or empty = include all.
        relevant_system_ids : set[str] | None
            System IDs to include. None or empty = include all.
        relevant_rule_ids : set[str] | None
            Rule IDs to include. None or empty = include all.
        include_all : bool
            If True, ignore relevance filters and include everything
            (used by ARCHITECT_MODE for full-context calls).

        Returns
        -------
        dict
            Simplified CGS slice.
        """
        # Normalise filter sets
        actor_filter  = None if (include_all or not relevant_actor_ids)  else relevant_actor_ids
        system_filter = None if (include_all or not relevant_system_ids) else relevant_system_ids
        rule_filter   = None if (include_all or not relevant_rule_ids)   else relevant_rule_ids

        simplified: dict[str, Any] = {}

        # ── Metadata ──────────────────────────────────────────────────────────
        meta = cgs.get("metadata", {})
        simplified["metadata"] = {
            "name":           meta.get("name", ""),
            "version":        meta.get("version", ""),
            "schema_version": meta.get("schema_version", ""),
            # cgs_hash intentionally omitted — in constraint prefix
        }

        # ── Global systems ────────────────────────────────────────────────────
        simplified["global_systems"] = [
            self._simplify_system(s)
            for s in cgs.get("global_systems", [])
            if system_filter is None or s.get("id") in system_filter
        ]

        # ── Modes ─────────────────────────────────────────────────────────────
        simplified["modes"] = []
        for mode in cgs.get("modes", []):
            slim_mode = self._simplify_mode(
                mode, actor_filter, system_filter, rule_filter
            )
            simplified["modes"].append(slim_mode)

        return simplified

    # ── Mode simplification ───────────────────────────────────────────────────

    def _simplify_mode(
        self,
        mode:          dict[str, Any],
        actor_filter:  set[str] | None,
        system_filter: set[str] | None,
        rule_filter:   set[str] | None,
    ) -> dict[str, Any]:
        slim: dict[str, Any] = {
            "id":         mode.get("id", ""),
            "is_default": mode.get("is_default", False),
        }

        slim["actors"] = [
            self._simplify_actor(a)
            for a in mode.get("actors", [])
            if actor_filter is None or a.get("id") in actor_filter
        ]
        slim["systems"] = [
            self._simplify_system(s)
            for s in mode.get("systems", [])
            if system_filter is None or s.get("id") in system_filter
        ]
        slim["rules"] = [
            self._simplify_rule(r)
            for r in mode.get("rules", [])
            if rule_filter is None or r.get("id") in rule_filter
        ]
        return slim

    # ── Actor simplification ──────────────────────────────────────────────────

    def _simplify_actor(self, actor: dict[str, Any]) -> dict[str, Any]:
        return {
            "id":           actor.get("id", ""),
            "actor_type":   actor.get("actor_type", ""),
            "control_type": actor.get("control_type", ""),
            "components":   [
                self._simplify_component(c)
                for c in actor.get("components", [])
            ],
        }

    def _simplify_component(self, comp: dict[str, Any]) -> dict[str, Any]:
        return {
            "type_id":  comp.get("type_id"),
            "name":     comp.get("name", ""),
            "defaults": self._simplify_defaults(comp.get("defaults", {})),
        }

    def _simplify_defaults(self, defaults: dict[str, Any]) -> dict[str, Any]:
        """
        Flattens and compacts component defaults.
        Nested vector/quaternion objects → short string summaries.
        Strings longer than _MAX_STRING_LEN → truncated.
        """
        slim: dict[str, Any] = {}
        for key, val in defaults.items():
            slim[key] = self._compact_value(val)
        return slim

    # ── System and Rule simplification ───────────────────────────────────────

    @staticmethod
    def _simplify_system(sys: dict[str, Any]) -> dict[str, Any]:
        return {
            "id":           sys.get("id", ""),
            "phase":        sys.get("phase", ""),
            "reads":        sys.get("reads",  []),
            "writes":       sys.get("writes", []),
            "depends_on":   sys.get("depends_on", []),
            "deterministic": sys.get("deterministic", True),
        }

    @staticmethod
    def _simplify_rule(rule: dict[str, Any]) -> dict[str, Any]:
        condition = rule.get("condition", "")
        effect    = rule.get("effect",    "")
        return {
            "id":        rule.get("id", ""),
            "condition": condition[:_MAX_CONDITION_LEN] + ("…" if len(condition) > _MAX_CONDITION_LEN else ""),
            "effect":    effect[:_MAX_EFFECT_LEN]       + ("…" if len(effect)    > _MAX_EFFECT_LEN    else ""),
            "priority":  rule.get("priority",  0),
            "is_active": rule.get("is_active", True),
        }

    # ── Value compaction ──────────────────────────────────────────────────────

    def _compact_value(self, val: Any) -> Any:
        """
        Compacts a single value from a component defaults dict.
        """
        if isinstance(val, dict):
            return self._compact_dict(val)
        if isinstance(val, str) and len(val) > _MAX_STRING_LEN:
            return val[:_MAX_STRING_LEN] + "…"
        if isinstance(val, list):
            # Compact list items (tags, arrays)
            return [self._compact_value(v) for v in val[:10]]  # cap at 10 items
        return val

    @staticmethod
    def _compact_dict(d: dict[str, Any]) -> Any:
        """
        Compacts a nested dict. Returns a short string for known patterns,
        or a compacted dict for unrecognised structures.
        """
        # Exact zero vector (before generic xyz branch)
        if d == _ZERO_VECTOR:
            return "zero"

        # Unit scale (before generic xyz branch)
        if d == _UNIT_SCALE:
            return "unit"

        # Generic xyz vector
        if set(d.keys()) == {"x", "y", "z"}:
            if all(isinstance(d[k], (int, float)) for k in ("x", "y", "z")):
                if all(d[k] == 0.0 for k in ("x", "y", "z")):
                    return "zero"
                return f"({d['x']}, {d['y']}, {d['z']})"

        # Identity quaternion
        if set(d.keys()) == {"x", "y", "z", "w"}:
            if d == _IDENTITY_QUAT:
                return "identity"
            return f"({d['x']}, {d['y']}, {d['z']}, {d['w']})"

        # Unit scale
        if d == _UNIT_SCALE:
            return "unit"

        # Generic dict — keep keys but compact values, cap depth
        return {
            k: (str(v)[:_MAX_STRING_LEN] if isinstance(v, str) and len(v) > _MAX_STRING_LEN else v)
            for k, v in d.items()
        }

    # ── Size estimation ───────────────────────────────────────────────────────

    @staticmethod
    def estimate_size_reduction(
        original_cgs:    dict[str, Any],
        simplified_cgs:  dict[str, Any],
    ) -> float:
        """
        Returns the size reduction ratio as a float in [0.0, 1.0].
        1.0 = 100% reduction (nothing left). 0.6 = 60% reduction.
        """
        import json as _json
        original_len   = len(_json.dumps(original_cgs))
        simplified_len = len(_json.dumps(simplified_cgs))
        if original_len == 0:
            return 0.0
        return 1.0 - (simplified_len / original_len)