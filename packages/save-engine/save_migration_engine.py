"""Schema-version migration for XACE save payloads.

The engine consumes MigrationPlan-like objects from schema-factory or plain
dict plans with the same fields. It applies only deterministic structural
operations and records an audit trail in the save envelope.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


class SaveMigrationError(RuntimeError):
    """Raised when a save cannot be migrated automatically."""


@dataclass(frozen=True)
class AppliedMigration:
    from_version: str
    to_version: str
    rule_count: int
    breaking: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "rule_count": self.rule_count,
            "breaking": self.breaking,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MigrationResult:
    envelope: dict[str, Any]
    applied: AppliedMigration


class SaveMigrationEngine:
    """Applies ordered migration plans to save envelopes."""

    def __init__(self, allow_breaking: bool = False) -> None:
        self.allow_breaking = allow_breaking

    def migrate_envelope(
        self,
        envelope: Mapping[str, Any],
        *,
        target_schema_version: str,
        migration_plan: Any,
    ) -> MigrationResult:
        if not isinstance(envelope, Mapping):
            raise SaveMigrationError("envelope must be a mapping")
        target = _non_empty_text(target_schema_version, "target_schema_version")
        source = _non_empty_text(envelope.get("schema_version", ""), "schema_version")
        plan = _normalise_plan(migration_plan, source, target)

        if plan["from_version"] != source:
            raise SaveMigrationError(
                f"migration plan source {plan['from_version']} does not match save schema {source}"
            )
        if plan["to_version"] != target:
            raise SaveMigrationError(
                f"migration plan target {plan['to_version']} does not match current schema {target}"
            )
        if plan["is_breaking"] and not self.allow_breaking:
            raise SaveMigrationError("migration plan is breaking and requires user confirmation")

        migrated = deepcopy(dict(envelope))
        payload = migrated.get("payload")
        if not isinstance(payload, Mapping):
            raise SaveMigrationError("envelope payload must be a mapping")
        payload_copy: dict[str, Any] = deepcopy(dict(payload))

        warnings: list[str] = []
        for rule in plan["rules"]:
            warning = self._apply_rule(payload_copy, rule)
            if warning:
                warnings.append(warning)

        migrated["payload"] = payload_copy
        migrated["schema_version"] = target
        history = list(migrated.get("migration_history", []))
        applied = AppliedMigration(
            from_version=source,
            to_version=target,
            rule_count=len(plan["rules"]),
            breaking=bool(plan["is_breaking"]),
            warnings=tuple(warnings),
        )
        history.append(applied.to_dict())
        migrated["migration_history"] = history
        return MigrationResult(envelope=migrated, applied=applied)

    def _apply_rule(self, payload: dict[str, Any], rule: Mapping[str, Any]) -> str | None:
        rule_type = str(rule.get("rule_type", ""))
        target_path = str(rule.get("target_path", ""))
        params = rule.get("params", {})
        if not isinstance(params, Mapping):
            raise SaveMigrationError(f"migration rule {rule_type} params must be a mapping")

        match rule_type:
            case "add_actor" | "add_system" | "remove_system":
                return None
            case "tombstone_actor":
                actor_id = str(params.get("actor_id", "")).strip()
                node = _get_path(payload, _path_segments(target_path))
                if isinstance(node, dict):
                    node["__tombstoned__"] = True
                    node["__tombstone_actor_id__"] = actor_id
                return None
            case "remove_component" | "remove_field":
                _delete_path(payload, _path_segments(target_path))
                return None
            case "add_component":
                defaults = params.get("defaults", {})
                if not isinstance(defaults, Mapping):
                    raise SaveMigrationError("add_component defaults must be a mapping")
                _set_path_if_missing(payload, _path_segments(target_path), deepcopy(dict(defaults)))
                return None
            case "add_field":
                default_value = deepcopy(params.get("default_value"))
                _set_path_if_missing(payload, _path_segments(target_path), default_value)
                return None
            case "modify_field":
                segments = _path_segments(target_path)
                current = _get_path(payload, segments)
                if current == params.get("old_value"):
                    _set_path(payload, segments, deepcopy(params.get("new_value")))
                return None
            case _:
                raise SaveMigrationError(f"unsupported migration rule type: {rule_type}")


def _normalise_plan(plan: Any, source: str, target: str) -> dict[str, Any]:
    if plan is None:
        raise SaveMigrationError("migration_plan is required for schema changes")
    if isinstance(plan, Mapping):
        rules = plan.get("rules", [])
        from_version = plan.get("from_version", source)
        to_version = plan.get("to_version", target)
        is_breaking = bool(plan.get("is_breaking", False))
    else:
        rules = getattr(plan, "rules", [])
        from_version = getattr(plan, "from_version", source)
        to_version = getattr(plan, "to_version", target)
        is_breaking = bool(getattr(plan, "is_breaking", False))
    return {
        "from_version": _non_empty_text(from_version, "from_version"),
        "to_version": _non_empty_text(to_version, "to_version"),
        "is_breaking": is_breaking,
        "rules": [_normalise_rule(rule) for rule in rules],
    }


def _normalise_rule(rule: Any) -> dict[str, Any]:
    if isinstance(rule, Mapping):
        return dict(rule)
    return {
        "rule_type": getattr(rule, "rule_type", ""),
        "target_path": getattr(rule, "target_path", ""),
        "params": getattr(rule, "params", {}),
        "is_breaking": getattr(rule, "is_breaking", False),
    }


def _path_segments(path: str) -> list[str]:
    return [segment for segment in path.split(".") if segment]


def _get_path(root: Mapping[str, Any], segments: Iterable[str]) -> Any:
    node: Any = root
    for segment in segments:
        if not isinstance(node, Mapping) or segment not in node:
            return None
        node = node[segment]
    return node


def _set_path(root: dict[str, Any], segments: list[str], value: Any) -> None:
    if not segments:
        raise SaveMigrationError("target_path must not be empty")
    parent = _ensure_parent(root, segments)
    parent[segments[-1]] = value


def _set_path_if_missing(root: dict[str, Any], segments: list[str], value: Any) -> None:
    if not segments:
        raise SaveMigrationError("target_path must not be empty")
    parent = _ensure_parent(root, segments)
    parent.setdefault(segments[-1], value)


def _delete_path(root: dict[str, Any], segments: list[str]) -> None:
    if not segments:
        raise SaveMigrationError("target_path must not be empty")
    parent = _get_path(root, segments[:-1])
    if isinstance(parent, dict):
        parent.pop(segments[-1], None)


def _ensure_parent(root: dict[str, Any], segments: list[str]) -> dict[str, Any]:
    node = root
    for segment in segments[:-1]:
        child = node.get(segment)
        if child is None:
            child = {}
            node[segment] = child
        if not isinstance(child, dict):
            raise SaveMigrationError(f"path segment {segment!r} is not a mapping")
        node = child
    return node


def _non_empty_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise SaveMigrationError(f"{field_name} must not be empty")
    return text
