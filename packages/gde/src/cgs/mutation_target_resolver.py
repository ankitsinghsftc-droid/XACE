"""
mutation_target_resolver.py — MutationTargetResolver
======================================================
Resolves fully-qualified DSL paths to CGS nodes.

Every mutation in XACE targets a specific node in the CGS using a
fully-qualified dot-separated path. This resolver walks that path
against the actual CGS and returns the target node, its parent
container, and the key needed to apply the mutation.

## Path Format
Paths are dot-separated strings:

    "metadata.name"
    "global_systems.sys_input.phase"
    "modes.mode_default.actors.actor_player.components.100.defaults.current"
    "modes.mode_default.rules.rule_starvation.condition"

## Traversal Rules
The resolver must understand the CGS structure:

    Segment type            Traversal method
    ─────────────────────   ──────────────────────────────────────────
    "metadata"              dict key
    "global_systems"        dict key → arrives at a list
    "modes"                 dict key → arrives at a list
    <mode_id>               list lookup: find item where item["id"] == segment
    "actors"                dict key → arrives at a list
    <actor_id>              list lookup: find item where item["id"] == segment
    "systems"               dict key → arrives at a list
    <system_id>             list lookup: find item where item["id"] == segment
    "rules"                 dict key → arrives at a list
    <rule_id>               list lookup: find item where item["id"] == segment
    "components"            dict key → arrives at a list
    <type_id as int str>    list lookup: find item where item["type_id"] == int(segment)
    "defaults"              dict key → arrives at a dict
    <field_name>            dict key

## Partial and Implicit Paths
Partial paths ("modes.mode_default") and implicit paths ("player.health")
are rejected with a SchemaResolutionError. Every path must be resolvable
from the CGS root without assumptions.

## CREATE vs READ Targets
For SET/ADD operations on a NEW node, the leaf may not exist yet.
resolve_for_write() handles this: it resolves up to the parent and
returns (parent_container, key, None) when the leaf is absent.
resolve_for_read() requires the leaf to exist and raises if not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── Resolution Error ──────────────────────────────────────────────────────────

class SchemaResolutionError(Exception):
    """Raised when a DSL path cannot be resolved against the current CGS."""


# ── Resolution Result ─────────────────────────────────────────────────────────

@dataclass
class ResolutionResult:
    """
    Result of resolving a DSL path against a CGS.

    Attributes
    ----------
    path : str
        The original path string that was resolved.
    parent : dict | list
        The container that holds the target node.
        For dict targets: parent[key] == node.
        For list targets: parent is the list, key is the integer index.
    key : str | int
        The key or index within parent that addresses the target node.
    node : Any
        The resolved node value. None if the path targets a new node
        that doesn't exist yet (write-only resolution).
    exists : bool
        True if the node was found in the CGS. False for new-node targets.
    segments : list[str]
        The path split into its component segments.
    """

    path:     str
    parent:   Any
    key:      str | int
    node:     Any
    exists:   bool
    segments: list[str]

    @property
    def is_leaf_dict(self) -> bool:
        """True if the parent is a dict (key-value mutation)."""
        return isinstance(self.parent, dict)

    @property
    def is_leaf_list(self) -> bool:
        """True if the parent is a list (positional mutation)."""
        return isinstance(self.parent, list)

    def __repr__(self) -> str:
        status = "EXISTS" if self.exists else "NEW"
        return (
            f"ResolutionResult(path={self.path!r}, "
            f"key={self.key!r}, status={status})"
        )


# ── List-by-ID segments ───────────────────────────────────────────────────────

# These segments, when encountered, expect the NEXT segment to be an ID
# that will be used to find a matching item in the list.
_LIST_CONTAINER_KEYS: frozenset[str] = frozenset({
    "modes",
    "global_systems",
    "actors",
    "systems",
    "rules",
    "components",
})

# Segments that contain sub-lists identified by "type_id" (int) rather than "id" (str)
_TYPE_ID_KEYED_LISTS: frozenset[str] = frozenset({
    "components",
})


# ── Mutation Target Resolver ──────────────────────────────────────────────────

class MutationTargetResolver:
    """
    Resolves fully-qualified DSL paths against a CGS dict.

    Stateless — inject the current CGS at call time. CGSManager always
    passes a deep copy so the resolver cannot accidentally mutate state.

    Usage
    -----
        resolver = MutationTargetResolver()

        # Read: the node must exist
        result = resolver.resolve_for_read("modes.mode_default.actors.actor_player", cgs)

        # Write: new node allowed (leaf may be absent)
        result = resolver.resolve_for_write(
            "modes.mode_default.actors.actor_player.components.200.defaults.speed",
            cgs
        )
        if not result.exists:
            # target is new — parent is the defaults dict, key is "speed"
            result.parent[result.key] = new_value
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve_for_read(
        self, path: str, cgs: dict[str, Any]
    ) -> ResolutionResult:
        """
        Resolves a path that must point to an existing CGS node.

        Raises
        ------
        SchemaResolutionError
            If the path is invalid, partially qualified, or the target
            node does not exist in the CGS.
        """
        result = self._resolve(path, cgs, allow_missing_leaf=False)
        if not result.exists:
            raise SchemaResolutionError(
                f"Path '{path}' does not resolve to an existing node in the CGS. "
                f"Check the path segments: {result.segments}"
            )
        return result

    def resolve_for_write(
        self, path: str, cgs: dict[str, Any]
    ) -> ResolutionResult:
        """
        Resolves a path for a write operation. The leaf may or may not exist.
        If the leaf is absent, result.exists=False and result.node=None.

        The parent must exist — only the leaf may be new.

        Raises
        ------
        SchemaResolutionError
            If any segment OTHER than the final one cannot be resolved.
        """
        return self._resolve(path, cgs, allow_missing_leaf=True)

    def path_exists(self, path: str, cgs: dict[str, Any]) -> bool:
        """Returns True if the path resolves to an existing node."""
        try:
            result = self._resolve(path, cgs, allow_missing_leaf=False)
            return result.exists
        except SchemaResolutionError:
            return False

    def resolve_parent(
        self, path: str, cgs: dict[str, Any]
    ) -> ResolutionResult:
        """
        Resolves to the PARENT of the target node.
        Useful when you need the container to iterate or replace wholesale.
        Returns the result for path[:-1_segment].
        """
        segments = _split_path(path)
        if len(segments) < 2:
            raise SchemaResolutionError(
                f"Path '{path}' has only one segment — no parent to resolve."
            )
        parent_path = ".".join(segments[:-1])
        return self.resolve_for_read(parent_path, cgs)

    # ── Resolution Engine ─────────────────────────────────────────────────────

    def _resolve(
        self,
        path:               str,
        cgs:                dict[str, Any],
        allow_missing_leaf: bool,
    ) -> ResolutionResult:
        """
        Core traversal: walks the CGS following path segments.

        Supports:
        - dict key traversal
        - list-by-id traversal (find item where item["id"] == segment)
        - list-by-type_id traversal (find item where item["type_id"] == int(segment))
        """
        _validate_path(path)
        segments = _split_path(path)

        current:   Any = cgs
        parent:    Any = None
        last_key:  str | int = segments[-1]

        for i, segment in enumerate(segments):
            is_last = (i == len(segments) - 1)

            # ── Dict traversal ────────────────────────────────────────────────
            if isinstance(current, dict):
                if segment not in current:
                    if is_last and allow_missing_leaf:
                        return ResolutionResult(
                            path=path, parent=current, key=segment,
                            node=None, exists=False, segments=segments,
                        )
                    raise SchemaResolutionError(
                        f"Path '{path}' failed at segment '{segment}' "
                        f"(position {i}): key not found in dict. "
                        f"Available keys: {sorted(current.keys())}"
                    )
                parent = current
                last_key = segment
                current = current[segment]
                continue

            # ── List traversal ────────────────────────────────────────────────
            if isinstance(current, list):
                # Determine lookup key type from the PREVIOUS segment
                prev_segment = segments[i - 1] if i > 0 else ""
                if prev_segment in _TYPE_ID_KEYED_LISTS:
                    # Lookup by type_id (int)
                    try:
                        target_id = int(segment)
                    except ValueError:
                        raise SchemaResolutionError(
                            f"Path '{path}' segment '{segment}' (position {i}) "
                            f"must be an integer type_id for components list."
                        )
                    idx, item = _find_by_type_id(current, target_id)
                else:
                    # Lookup by id (str)
                    idx, item = _find_by_id(current, segment)

                if item is None:
                    if is_last and allow_missing_leaf:
                        return ResolutionResult(
                            path=path, parent=current, key=idx if idx is not None else len(current),
                            node=None, exists=False, segments=segments,
                        )
                    id_key = "type_id" if prev_segment in _TYPE_ID_KEYED_LISTS else "id"
                    existing = [
                        str(it.get(id_key, "?")) for it in current
                        if isinstance(it, dict)
                    ]
                    raise SchemaResolutionError(
                        f"Path '{path}' failed at segment '{segment}' "
                        f"(position {i}): no item with {id_key}='{segment}' "
                        f"in list. Existing {id_key}s: {existing}"
                    )
                parent = current
                last_key = idx   # type: ignore[assignment]
                current = item
                continue

            # ── Neither dict nor list ─────────────────────────────────────────
            raise SchemaResolutionError(
                f"Path '{path}' failed at segment '{segment}' (position {i}): "
                f"cannot traverse into a {type(current).__name__} value. "
                f"Path segments beyond this point are invalid."
            )

        return ResolutionResult(
            path=path,
            parent=parent,
            key=last_key,
            node=current,
            exists=True,
            segments=segments,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_path(path: str) -> None:
    """
    Validates that a path string is non-empty and contains no empty segments.
    Does NOT validate that the path resolves — that is the resolver's job.
    """
    if not path or not path.strip():
        raise SchemaResolutionError(
            "DSL path must not be empty. "
            "Provide a fully-qualified path like "
            "'modes.mode_default.actors.actor_player.components.100.defaults.current'."
        )
    segments = path.split(".")
    for i, seg in enumerate(segments):
        if not seg:
            raise SchemaResolutionError(
                f"DSL path '{path}' has an empty segment at position {i}. "
                f"Paths must not have consecutive dots or leading/trailing dots."
            )


def _split_path(path: str) -> list[str]:
    """Splits a dot-separated path into a list of non-empty segments."""
    return [s for s in path.split(".") if s]


def _find_by_id(
    lst: list[Any], target_id: str
) -> tuple[int | None, Any]:
    """
    Finds the first item in a list where item["id"] == target_id.
    Returns (index, item) or (None, None) if not found.
    """
    for i, item in enumerate(lst):
        if isinstance(item, dict) and item.get("id") == target_id:
            return i, item
    return None, None


def _find_by_type_id(
    lst: list[Any], target_type_id: int
) -> tuple[int | None, Any]:
    """
    Finds the first item in a list where item["type_id"] == target_type_id.
    Returns (index, item) or (None, None) if not found.
    """
    for i, item in enumerate(lst):
        if isinstance(item, dict) and item.get("type_id") == target_type_id:
            return i, item
    return None, None