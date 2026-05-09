"""
schema_diff_engine.py — SchemaDiffEngine
=========================================
Computes a structured diff between two CGS versions.

The diff is the authoritative input for MigrationRuleGenerator.
It is also surfaced in the builder UI version timeline so designers
can see exactly what changed between any two CGS snapshots.

## CGS Structure Assumed
The engine operates on the canonical CGS dict format produced by the GDE:

    {
        "metadata": {"version": "0.1.0", "name": "My Game", ...},
        "global_systems": [{"id": "sys_x", ...}, ...],
        "modes": [
            {
                "id": "mode_default",
                "actors": [{"id": "actor_player", "components": [...], ...}],
                "systems": [{"id": "sys_y", ...}],
                "rules":   [{"id": "rule_z", ...}],
            },
            ...
        ],
    }

## Breaking vs Non-Breaking Changes
A diff is marked breaking=True when it contains any change that could
render existing save files incompatible:
    - Actor removed (save data references a missing actor)
    - Component removed from actor (save data has orphaned component data)
    - Required field removed from component (save data has unknown field)
    - Actor ID renamed (save data can't find the actor)

Non-breaking changes (no migration needed):
    - Actor added (new entities don't exist in old saves — safe)
    - Component added with defaults (default fills the gap — safe)
    - Optional field added (default fills the gap — safe)
    - System or rule added/removed (save data does not store system state)
    - Description or display_name changes

## Determinism (D11)
All diff collections are sorted by ID before being stored in the result.
Same pair of CGS dicts always produces an identical SchemaDiff.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Change Kinds ──────────────────────────────────────────────────────────────

ADDED    = "added"
REMOVED  = "removed"
MODIFIED = "modified"


# ── Diff Data Classes ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FieldChange:
    """A single field value change within a component."""
    field_name: str
    old_value:  Any
    new_value:  Any

    def __repr__(self) -> str:
        return f"FieldChange({self.field_name!r}: {self.old_value!r} → {self.new_value!r})"


@dataclass(frozen=True)
class ComponentChange:
    """
    A change to one component within an actor.

    change_kind : "added" | "removed" | "modified"
    field_changes: populated only for "modified" — lists per-field deltas.
    """
    type_id:       int
    change_kind:   str
    field_changes: tuple[FieldChange, ...] = ()

    @property
    def is_breaking(self) -> bool:
        """
        Component removal is breaking — save data may have orphaned fields.
        Component addition is non-breaking if defaults exist.
        Field removal is breaking — save data references a gone field.
        """
        if self.change_kind == REMOVED:
            return True
        if self.change_kind == MODIFIED:
            return any(fc.new_value is None for fc in self.field_changes)
        return False


@dataclass(frozen=True)
class ActorDiff:
    """Diff record for one actor across two CGS versions."""
    actor_id:          str
    mode_id:           str
    change_kind:       str
    component_changes: tuple[ComponentChange, ...] = ()

    @property
    def is_breaking(self) -> bool:
        if self.change_kind == REMOVED:
            return True
        return any(cc.is_breaking for cc in self.component_changes)


@dataclass(frozen=True)
class SystemDiff:
    """Diff record for one system definition across two CGS versions."""
    system_id:     str
    mode_id:       str          # "" for global_systems
    change_kind:   str
    # field_name → (old_value, new_value) for modified systems
    field_changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def is_breaking(self) -> bool:
        # System changes never break save files (systems aren't persisted)
        return False


@dataclass(frozen=True)
class RuleDiff:
    """Diff record for one rule definition across two CGS versions."""
    rule_id:     str
    mode_id:     str
    change_kind: str

    @property
    def is_breaking(self) -> bool:
        return False


@dataclass
class SchemaDiff:
    """
    Complete structural diff between two CGS versions.

    Produced by SchemaDiffEngine.compute(). Consumed by
    MigrationRuleGenerator to build a MigrationPlan.

    All list fields are sorted by (mode_id, entity_id) ascending (D11).
    """
    from_version:  str
    to_version:    str
    from_hash:     str
    to_hash:       str
    actor_diffs:   list[ActorDiff]  = field(default_factory=list)
    system_diffs:  list[SystemDiff] = field(default_factory=list)
    rule_diffs:    list[RuleDiff]   = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.actor_diffs and not self.system_diffs and not self.rule_diffs

    @property
    def is_breaking(self) -> bool:
        """True if any change could break existing save files."""
        return (
            any(d.is_breaking for d in self.actor_diffs)
            or any(d.is_breaking for d in self.system_diffs)
            or any(d.is_breaking for d in self.rule_diffs)
        )

    def actor_diffs_by_kind(self, kind: str) -> list[ActorDiff]:
        return [d for d in self.actor_diffs if d.change_kind == kind]

    def system_diffs_by_kind(self, kind: str) -> list[SystemDiff]:
        return [d for d in self.system_diffs if d.change_kind == kind]

    def summary(self) -> str:
        added_a   = len(self.actor_diffs_by_kind(ADDED))
        removed_a = len(self.actor_diffs_by_kind(REMOVED))
        modified_a= len(self.actor_diffs_by_kind(MODIFIED))
        added_s   = len(self.system_diffs_by_kind(ADDED))
        removed_s = len(self.system_diffs_by_kind(REMOVED))
        breaking  = " [BREAKING — migration required]" if self.is_breaking else ""
        return (
            f"v{self.from_version} → v{self.to_version}{breaking}: "
            f"actors +{added_a}/-{removed_a}/~{modified_a}, "
            f"systems +{added_s}/-{removed_s}"
        )

    def __repr__(self) -> str:
        return f"SchemaDiff({self.summary()})"


# ── Schema Diff Engine ────────────────────────────────────────────────────────

class SchemaDiffEngine:
    """
    Computes the structural diff between two CGS dicts.

    Stateless — one call to compute() per diff needed.
    The engine does not mutate either input dict.

    Usage
    -----
        diff = SchemaDiffEngine.compute(
            old_cgs, new_cgs,
            from_version="0.1.0", from_hash="abc...",
            to_version="0.2.0",   to_hash="def...",
        )
    """

    @classmethod
    def compute(
        cls,
        old_cgs:       dict[str, Any],
        new_cgs:       dict[str, Any],
        from_version:  str,
        from_hash:     str,
        to_version:    str,
        to_hash:       str,
    ) -> SchemaDiff:
        """
        Computes a full structural diff between two CGS dicts.

        Parameters
        ----------
        old_cgs, new_cgs : dict
            The before and after CGS content dicts.
        from_version, to_version : str
            MAJOR.MINOR.PATCH version strings for labelling.
        from_hash, to_hash : str
            SHA-256 hashes of the respective CGS dicts.

        Returns
        -------
        SchemaDiff
            Fully populated diff with sorted, deterministic collections (D11).
        """
        diff = SchemaDiff(
            from_version=from_version,
            to_version=to_version,
            from_hash=from_hash,
            to_hash=to_hash,
        )

        # Collect all mode IDs from both versions (union)
        old_modes = {m["id"]: m for m in old_cgs.get("modes", [])}
        new_modes = {m["id"]: m for m in new_cgs.get("modes", [])}
        all_mode_ids = sorted(set(old_modes) | set(new_modes))  # D11

        for mode_id in all_mode_ids:
            old_mode = old_modes.get(mode_id, {})
            new_mode = new_modes.get(mode_id, {})

            diff.actor_diffs.extend(
                cls._diff_actors(old_mode, new_mode, mode_id)
            )
            diff.system_diffs.extend(
                cls._diff_systems(old_mode, new_mode, mode_id)
            )
            diff.rule_diffs.extend(
                cls._diff_rules(old_mode, new_mode, mode_id)
            )

        # Global systems diff
        diff.system_diffs.extend(
            cls._diff_systems(
                {"systems": old_cgs.get("global_systems", [])},
                {"systems": new_cgs.get("global_systems", [])},
                mode_id="",
            )
        )

        # Sort for determinism (D11)
        diff.actor_diffs.sort(key=lambda d: (d.mode_id, d.actor_id))
        diff.system_diffs.sort(key=lambda d: (d.mode_id, d.system_id))
        diff.rule_diffs.sort(key=lambda d: (d.mode_id, d.rule_id))

        return diff

    # ── Actor Diffing ─────────────────────────────────────────────────────────

    @classmethod
    def _diff_actors(
        cls,
        old_mode: dict[str, Any],
        new_mode: dict[str, Any],
        mode_id:  str,
    ) -> list[ActorDiff]:
        old_actors = {a["id"]: a for a in old_mode.get("actors", [])}
        new_actors = {a["id"]: a for a in new_mode.get("actors", [])}
        diffs: list[ActorDiff] = []

        added_ids   = sorted(set(new_actors) - set(old_actors))
        removed_ids = sorted(set(old_actors) - set(new_actors))
        common_ids  = sorted(set(old_actors) & set(new_actors))

        for aid in added_ids:
            diffs.append(ActorDiff(actor_id=aid, mode_id=mode_id, change_kind=ADDED))
        for aid in removed_ids:
            diffs.append(ActorDiff(actor_id=aid, mode_id=mode_id, change_kind=REMOVED))
        for aid in common_ids:
            comp_changes = cls._diff_components(old_actors[aid], new_actors[aid])
            if comp_changes:
                diffs.append(ActorDiff(
                    actor_id=aid,
                    mode_id=mode_id,
                    change_kind=MODIFIED,
                    component_changes=tuple(sorted(comp_changes, key=lambda c: c.type_id)),
                ))

        return diffs

    @classmethod
    def _diff_components(
        cls,
        old_actor: dict[str, Any],
        new_actor: dict[str, Any],
    ) -> list[ComponentChange]:
        old_comps = {c["type_id"]: c for c in old_actor.get("components", [])}
        new_comps = {c["type_id"]: c for c in new_actor.get("components", [])}
        changes:   list[ComponentChange] = []

        for tid in sorted(set(new_comps) - set(old_comps)):
            changes.append(ComponentChange(type_id=tid, change_kind=ADDED))
        for tid in sorted(set(old_comps) - set(new_comps)):
            changes.append(ComponentChange(type_id=tid, change_kind=REMOVED))
        for tid in sorted(set(old_comps) & set(new_comps)):
            field_changes = cls._diff_component_fields(
                old_comps[tid].get("defaults", {}),
                new_comps[tid].get("defaults", {}),
            )
            if field_changes:
                changes.append(ComponentChange(
                    type_id=tid,
                    change_kind=MODIFIED,
                    field_changes=tuple(sorted(field_changes, key=lambda f: f.field_name)),
                ))

        return changes

    @staticmethod
    def _diff_component_fields(
        old_defaults: dict[str, Any],
        new_defaults: dict[str, Any],
    ) -> list[FieldChange]:
        changes: list[FieldChange] = []
        all_fields = sorted(set(old_defaults) | set(new_defaults))
        for fname in all_fields:
            old_val = old_defaults.get(fname)
            new_val = new_defaults.get(fname)
            if old_val != new_val:
                changes.append(FieldChange(
                    field_name=fname,
                    old_value=old_val,
                    new_value=new_val,
                ))
        return changes

    # ── System Diffing ────────────────────────────────────────────────────────

    @staticmethod
    def _diff_systems(
        old_mode: dict[str, Any],
        new_mode: dict[str, Any],
        mode_id:  str,
    ) -> list[SystemDiff]:
        old_sys = {s["id"]: s for s in old_mode.get("systems", [])}
        new_sys = {s["id"]: s for s in new_mode.get("systems", [])}
        diffs:   list[SystemDiff] = []

        for sid in sorted(set(new_sys) - set(old_sys)):
            diffs.append(SystemDiff(system_id=sid, mode_id=mode_id, change_kind=ADDED))
        for sid in sorted(set(old_sys) - set(new_sys)):
            diffs.append(SystemDiff(system_id=sid, mode_id=mode_id, change_kind=REMOVED))
        for sid in sorted(set(old_sys) & set(new_sys)):
            _track = ("phase", "reads", "writes", "depends_on", "deterministic")
            field_changes = {
                k: (old_sys[sid].get(k), new_sys[sid].get(k))
                for k in _track
                if old_sys[sid].get(k) != new_sys[sid].get(k)
            }
            if field_changes:
                diffs.append(SystemDiff(
                    system_id=sid,
                    mode_id=mode_id,
                    change_kind=MODIFIED,
                    field_changes=field_changes,
                ))

        return diffs

    # ── Rule Diffing ──────────────────────────────────────────────────────────

    @staticmethod
    def _diff_rules(
        old_mode: dict[str, Any],
        new_mode: dict[str, Any],
        mode_id:  str,
    ) -> list[RuleDiff]:
        old_rules = {r["id"]: r for r in old_mode.get("rules", [])}
        new_rules = {r["id"]: r for r in new_mode.get("rules", [])}
        diffs:     list[RuleDiff] = []

        for rid in sorted(set(new_rules) - set(old_rules)):
            diffs.append(RuleDiff(rule_id=rid, mode_id=mode_id, change_kind=ADDED))
        for rid in sorted(set(old_rules) - set(new_rules)):
            diffs.append(RuleDiff(rule_id=rid, mode_id=mode_id, change_kind=REMOVED))
        for rid in sorted(set(old_rules) & set(new_rules)):
            if old_rules[rid] != new_rules[rid]:
                diffs.append(RuleDiff(rule_id=rid, mode_id=mode_id, change_kind=MODIFIED))

        return diffs