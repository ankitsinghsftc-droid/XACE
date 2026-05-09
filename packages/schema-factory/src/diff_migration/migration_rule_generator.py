"""
migration_rule_generator.py — MigrationRuleGenerator
======================================================
Converts a SchemaDiff into an ordered MigrationPlan — the concrete set of
operations the SaveMigrationEngine (Phase 16) applies to old save files when
a player loads a save into a newer version of the game.

## Why Migration Matters
When a designer adds a new component to an actor or removes a field, any
existing save files encoded with the old schema become structurally
incompatible. Without migration, the game either crashes on load or silently
uses stale/missing data. The migration plan is what bridges the gap.

## Migration Rule Types
"add_component"    — actor now has a component it didn't before; add it with defaults
"remove_component" — actor no longer has a component; strip it from save data
"add_field"        — component has a new field; fill it with the new default value
"remove_field"     — component field was removed; drop it from save data
"modify_field"     — field default changed; update save data to new value (soft)
"tombstone_actor"  — actor was removed entirely; mark save data as invalid
"add_actor"        — actor added; no save action needed (new entities spawn fresh)
"add_system"       — system added; no save action needed (systems are not persisted)
"remove_system"    — system removed; no save action needed

## Rule Ordering
Rules in a MigrationPlan must be applied in declaration order.
The generator produces rules in a safe order:
    1. tombstone_actor (remove obsolete actors first)
    2. remove_component (strip obsolete component data)
    3. remove_field (strip obsolete fields)
    4. add_component (add new components with defaults)
    5. add_field (fill in new fields)
    6. modify_field (update changed defaults — lowest risk, applied last)

## Breaking vs Non-Breaking
A MigrationPlan is marked breaking=True if any rule cannot be applied
automatically with full fidelity — i.e. the migration may lose data or
require a designer decision. The SaveEngine surfaces this to the user.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .schema_diff_engine import (
    ADDED, REMOVED, MODIFIED,
    SchemaDiff, ActorDiff, ComponentChange, FieldChange,
)


# ── Migration Rule ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MigrationRule:
    """
    One atomic operation in a MigrationPlan.

    Attributes
    ----------
    rule_id : str
        Unique identifier for this rule within the plan (UUID4 hex).
    rule_type : str
        Operation type — see module docstring for vocabulary.
    target_path : str
        Dot-separated path to the affected node.
        Examples:
            "modes.mode_default.actors.actor_zombie"
            "modes.mode_default.actors.actor_player.components.100"
            "modes.mode_default.actors.actor_player.components.100.fields.current"
    params : dict[str, Any]
        Rule-specific parameters. Contents depend on rule_type:
            add_component:  {"type_id": int, "defaults": dict}
            remove_component: {"type_id": int}
            add_field:      {"field_name": str, "default_value": Any}
            remove_field:   {"field_name": str}
            modify_field:   {"field_name": str, "old_value": Any, "new_value": Any}
            tombstone_actor:{"actor_id": str, "mode_id": str}
    description : str
        Plain-English description for the builder UI migration review panel.
    is_breaking : bool
        True if this rule may lose data or requires a designer decision.
    is_reversible : bool
        True if the inverse rule can be auto-generated for rollback.
    """

    rule_id:        str
    rule_type:      str
    target_path:    str
    params:         dict[str, Any]
    description:    str
    is_breaking:    bool           = False
    is_reversible:  bool           = True

    def __repr__(self) -> str:
        return (
            f"MigrationRule(type={self.rule_type!r}, "
            f"target={self.target_path!r}, "
            f"breaking={self.is_breaking})"
        )


# ── Migration Plan ────────────────────────────────────────────────────────────

# Safe application order for migration rule types (lower = applied first)
_RULE_ORDER: dict[str, int] = {
    "tombstone_actor":  0,
    "remove_component": 1,
    "remove_field":     2,
    "add_component":    3,
    "add_field":        4,
    "modify_field":     5,
    "add_actor":        6,
    "add_system":       7,
    "remove_system":    8,
}


@dataclass
class MigrationPlan:
    """
    Ordered set of MigrationRules that transform save data from one CGS
    version to another.

    Attributes
    ----------
    plan_id : str
        Unique plan identifier (UUID4 hex). Stored in save metadata.
    from_version : str
        Source CGS version (save file's schema version).
    to_version : str
        Target CGS version (current game schema version).
    rules : list[MigrationRule]
        Migration rules in safe application order.
    is_breaking : bool
        True if any rule is breaking — user warned on load.
    requires_designer_review : bool
        True if auto-migration cannot fully recover — manual intervention needed.
    """

    plan_id:                   str
    from_version:              str
    to_version:                str
    rules:                     list[MigrationRule] = field(default_factory=list)
    is_breaking:               bool                = False
    requires_designer_review:  bool                = False

    @property
    def rule_count(self) -> int:
        return len(self.rules)

    def rules_of_type(self, rule_type: str) -> list[MigrationRule]:
        return [r for r in self.rules if r.rule_type == rule_type]

    def breaking_rules(self) -> list[MigrationRule]:
        return [r for r in self.rules if r.is_breaking]

    def summary(self) -> str:
        type_counts: dict[str, int] = {}
        for r in self.rules:
            type_counts[r.rule_type] = type_counts.get(r.rule_type, 0) + 1
        parts = ", ".join(f"{v}×{k}" for k, v in sorted(type_counts.items()))
        breaking = " [BREAKING]" if self.is_breaking else ""
        return (
            f"MigrationPlan v{self.from_version}→v{self.to_version}{breaking}: "
            f"{self.rule_count} rules ({parts})"
        )

    def __repr__(self) -> str:
        return f"MigrationPlan({self.summary()})"


# ── Migration Rule Generator ──────────────────────────────────────────────────

class MigrationRuleGenerator:
    """
    Converts a SchemaDiff into a MigrationPlan.

    Stateless — one call to generate() per diff. The generator does not
    read or write save files; it only produces the rule list that the
    SaveMigrationEngine (Phase 16) will execute.

    Usage
    -----
        diff = SchemaDiffEngine.compute(old_cgs, new_cgs, ...)
        plan = MigrationRuleGenerator.generate(diff)
        # plan.rules contains ordered migration steps
    """

    @classmethod
    def generate(cls, diff: SchemaDiff) -> MigrationPlan:
        """
        Generates a MigrationPlan from a SchemaDiff.

        Rules are sorted by _RULE_ORDER for safe application sequence.
        The plan is marked breaking if any rule is breaking.
        """
        if diff.is_empty:
            return MigrationPlan(
                plan_id=_new_id(),
                from_version=diff.from_version,
                to_version=diff.to_version,
                rules=[],
            )

        rules: list[MigrationRule] = []

        # Actor-level rules (in actor_diff sorted order — already D11)
        for actor_diff in diff.actor_diffs:
            rules.extend(cls._rules_for_actor_diff(actor_diff))

        # System-level rules
        for system_diff in diff.system_diffs:
            rules.extend(cls._rules_for_system_diff(system_diff))

        # Sort rules into safe application order, then by target_path (D11)
        rules.sort(key=lambda r: (
            _RULE_ORDER.get(r.rule_type, 99),
            r.target_path,
        ))

        is_breaking = any(r.is_breaking for r in rules)
        requires_review = any(
            r.rule_type == "tombstone_actor" for r in rules
        )

        return MigrationPlan(
            plan_id=_new_id(),
            from_version=diff.from_version,
            to_version=diff.to_version,
            rules=rules,
            is_breaking=is_breaking,
            requires_designer_review=requires_review,
        )

    # ── Actor Rules ───────────────────────────────────────────────────────────

    @classmethod
    def _rules_for_actor_diff(cls, actor_diff: ActorDiff) -> list[MigrationRule]:
        path_prefix = (
            f"modes.{actor_diff.mode_id}.actors.{actor_diff.actor_id}"
            if actor_diff.mode_id
            else f"actors.{actor_diff.actor_id}"
        )

        match actor_diff.change_kind:
            case "added":
                # New actors spawn fresh — no save data action needed
                return [MigrationRule(
                    rule_id=_new_id(),
                    rule_type="add_actor",
                    target_path=path_prefix,
                    params={"actor_id": actor_diff.actor_id},
                    description=(
                        f"Actor '{actor_diff.actor_id}' was added. "
                        f"No save migration needed — new actors spawn fresh."
                    ),
                    is_breaking=False,
                    is_reversible=True,
                )]

            case "removed":
                return [MigrationRule(
                    rule_id=_new_id(),
                    rule_type="tombstone_actor",
                    target_path=path_prefix,
                    params={"actor_id": actor_diff.actor_id, "mode_id": actor_diff.mode_id},
                    description=(
                        f"Actor '{actor_diff.actor_id}' was removed. "
                        f"Save data for this actor will be marked obsolete. "
                        f"Any saved state for this actor cannot be restored."
                    ),
                    is_breaking=True,
                    is_reversible=False,
                )]

            case "modified":
                rules: list[MigrationRule] = []
                for comp_change in actor_diff.component_changes:
                    rules.extend(
                        cls._rules_for_component_change(
                            comp_change, path_prefix
                        )
                    )
                return rules

            case _:
                return []

    @classmethod
    def _rules_for_component_change(
        cls,
        comp_change:  ComponentChange,
        actor_path:   str,
    ) -> list[MigrationRule]:
        comp_path = f"{actor_path}.components.{comp_change.type_id}"

        match comp_change.change_kind:
            case "added":
                return [MigrationRule(
                    rule_id=_new_id(),
                    rule_type="add_component",
                    target_path=comp_path,
                    params={
                        "type_id": comp_change.type_id,
                        "defaults": {},  # SaveEngine fills from component schema
                    },
                    description=(
                        f"Component type_id {comp_change.type_id} was added to "
                        f"this actor. Save data will be populated with schema defaults."
                    ),
                    is_breaking=False,
                    is_reversible=True,
                )]

            case "removed":
                return [MigrationRule(
                    rule_id=_new_id(),
                    rule_type="remove_component",
                    target_path=comp_path,
                    params={"type_id": comp_change.type_id},
                    description=(
                        f"Component type_id {comp_change.type_id} was removed. "
                        f"Save data for this component will be dropped."
                    ),
                    is_breaking=True,
                    is_reversible=False,
                )]

            case "modified":
                return [
                    cls._rule_for_field_change(fc, comp_path)
                    for fc in comp_change.field_changes
                ]

            case _:
                return []

    @staticmethod
    def _rule_for_field_change(
        fc:        FieldChange,
        comp_path: str,
    ) -> MigrationRule:
        field_path = f"{comp_path}.fields.{fc.field_name}"

        if fc.old_value is None and fc.new_value is not None:
            # Field added
            return MigrationRule(
                rule_id=_new_id(),
                rule_type="add_field",
                target_path=field_path,
                params={"field_name": fc.field_name, "default_value": fc.new_value},
                description=(
                    f"Field '{fc.field_name}' was added with default "
                    f"{fc.new_value!r}. Save data will be populated."
                ),
                is_breaking=False,
                is_reversible=True,
            )
        elif fc.old_value is not None and fc.new_value is None:
            # Field removed
            return MigrationRule(
                rule_id=_new_id(),
                rule_type="remove_field",
                target_path=field_path,
                params={"field_name": fc.field_name, "old_value": fc.old_value},
                description=(
                    f"Field '{fc.field_name}' was removed. "
                    f"Save data value ({fc.old_value!r}) will be dropped."
                ),
                is_breaking=True,
                is_reversible=False,
            )
        else:
            # Field default changed
            return MigrationRule(
                rule_id=_new_id(),
                rule_type="modify_field",
                target_path=field_path,
                params={
                    "field_name": fc.field_name,
                    "old_value":  fc.old_value,
                    "new_value":  fc.new_value,
                },
                description=(
                    f"Field '{fc.field_name}' default changed from "
                    f"{fc.old_value!r} to {fc.new_value!r}. "
                    f"Save data retains the player's actual saved value — "
                    f"this rule only updates entities that still have the old default."
                ),
                is_breaking=False,
                is_reversible=True,
            )

    # ── System Rules ──────────────────────────────────────────────────────────

    @staticmethod
    def _rules_for_system_diff(system_diff) -> list[MigrationRule]:
        """
        System changes never break save files — systems are not persisted.
        We generate informational rules so the migration log is complete.
        """
        mode_segment = f"modes.{system_diff.mode_id}." if system_diff.mode_id else ""
        target = f"{mode_segment}systems.{system_diff.system_id}"

        match system_diff.change_kind:
            case "added":
                return [MigrationRule(
                    rule_id=_new_id(),
                    rule_type="add_system",
                    target_path=target,
                    params={"system_id": system_diff.system_id},
                    description=(
                        f"System '{system_diff.system_id}' added. "
                        f"No save migration needed — system state is not persisted."
                    ),
                    is_breaking=False,
                    is_reversible=True,
                )]
            case "removed":
                return [MigrationRule(
                    rule_id=_new_id(),
                    rule_type="remove_system",
                    target_path=target,
                    params={"system_id": system_diff.system_id},
                    description=(
                        f"System '{system_diff.system_id}' removed. "
                        f"No save migration needed."
                    ),
                    is_breaking=False,
                    is_reversible=True,
                )]
            case _:
                return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_id() -> str:
    """Returns a compact UUID4 hex string for rule/plan IDs."""
    return uuid.uuid4().hex