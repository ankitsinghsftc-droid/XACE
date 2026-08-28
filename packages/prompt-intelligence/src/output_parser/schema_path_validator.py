"""
schema_path_validator.py — SchemaPathValidator
================================================
Validates that every CGS path in a parsed mutation exists in the
current CGS. This is the safety boundary against hallucinated paths.

## Why This Matters

    The LLM may confidently write a path like:
        "modes[mode_default].actors[actor_boss].components[100].defaults.current"

    If actor_boss does not exist in the CGS, applying this mutation would
    either silently create garbage data or crash the engine. This validator
    rejects any path that does not resolve to a real node in the current CGS.

## Path Grammar (bracket notation)

    Full path format:
        modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults.{field}

    Supported path types:
        Type 1 — Component field:
            modes[mode_default].actors[actor_zombie].components[5].defaults.max_linear_speed

        Type 2 — Component defaults root:
            modes[mode_default].actors[actor_zombie].components[5].defaults

        Type 3 — Actor root:
            modes[mode_default].actors[actor_zombie]

        Type 4 — System field:
            modes[mode_default].systems[MovementSystem].reads

        Type 5 — Rule field:
            modes[mode_default].rules[rule_player_death].condition

        Type 6 — Global system:
            global_systems[InputSystem].reads

        Type 7 — Metadata (always forbidden — validated separately):
            metadata.name  ← will fail if in forbidden list

## Validation Result

    PathValidationResult:
        valid:          bool
        invalid_paths:  list[str]   — paths that do not resolve
        unknown_paths:  list[str]   — paths with unrecognised grammar
        reasons:        list[str]   — human-readable reason per invalid path
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Path Parsing Patterns ─────────────────────────────────────────────────────

# modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults.{field}
_COMP_FIELD_RE = re.compile(
    r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]\.components\[(\d+)\]\.defaults\.(\w+)$'
)
# modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults
_COMP_DEFAULTS_RE = re.compile(
    r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]\.components\[(\d+)\]\.defaults$'
)
# modes[{mode_id}].actors[{actor_id}].components[{type_id}]
_COMP_ROOT_RE = re.compile(
    r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]\.components\[(\d+)\]$'
)
# modes[{mode_id}].actors[{actor_id}]
_ACTOR_ROOT_RE = re.compile(
    r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]$'
)
# modes[{mode_id}].actors[{actor_id}].{field}
_ACTOR_FIELD_RE = re.compile(
    r'^modes\[([^\]]+)\]\.actors\[([^\]]+)\]\.(\w+)$'
)
# modes[{mode_id}].systems[{system_id}]
_SYSTEM_RE = re.compile(
    r'^modes\[([^\]]+)\]\.systems\[([^\]]+)\]'
)
# modes[{mode_id}].rules[{rule_id}]
_RULE_RE = re.compile(
    r'^modes\[([^\]]+)\]\.rules\[([^\]]+)\]'
)
# global_systems[{system_id}]
_GLOBAL_SYS_RE = re.compile(
    r'^global_systems\[([^\]]+)\]'
)
# metadata.*
_METADATA_RE = re.compile(r'^metadata\.')


# ── Permanent Forbidden Paths ─────────────────────────────────────────────────

_FORBIDDEN_PATH_PREFIXES: frozenset[str] = frozenset({
    "metadata.cgs_hash",
    "metadata.schema_version",
    "metadata.version",
})


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PathValidationResult:
    """
    Result of SchemaPathValidator.validate().

    Attributes
    ----------
    valid          : bool         — True if all paths resolve correctly
    invalid_paths  : tuple[str]   — paths that definitively do not exist
    unknown_paths  : tuple[str]   — paths with unrecognised grammar (hard failures)
    reasons        : tuple[str]   — one reason string per invalid path
    forbidden_paths: tuple[str]   — paths touching permanently forbidden fields
    """
    valid:           bool
    invalid_paths:   tuple[str, ...]
    unknown_paths:   tuple[str, ...]
    reasons:         tuple[str, ...]
    forbidden_paths: tuple[str, ...]

    @property
    def has_forbidden(self) -> bool:
        return len(self.forbidden_paths) > 0

    @property
    def all_errors(self) -> list[str]:
        return list(self.reasons)


# ── Schema Path Validator ─────────────────────────────────────────────────────

class SchemaPathValidator:
    """
    Validates CGS paths in a mutation against the current schema.

    Stateless — create once, call validate() many times.
    Deterministic — same path + cgs always produces the same result.

    Usage
    -----
        validator = SchemaPathValidator()
        result = validator.validate(
            paths = ["modes[mode_default].actors[actor_zombie].components[5].defaults.max_linear_speed"],
            cgs   = current_cgs_dict,
        )
        if not result.valid:
            raise PathError(result.reasons)
    """

    def validate(
        self,
        paths: list[str],
        cgs:   dict[str, Any],
    ) -> PathValidationResult:
        """
        Validates a list of CGS paths against the current schema.

        Parameters
        ----------
        paths : list[str]
            Paths from DraftMutationTransaction operations.
        cgs : dict
            Current CGS JSON dict.

        Returns
        -------
        PathValidationResult
        """
        invalid:   list[str] = []
        unknown:   list[str] = []
        reasons:   list[str] = []
        forbidden: list[str] = []

        # Pre-build lookup indexes
        mode_index   = self._build_mode_index(cgs)
        global_sys   = {gs.get("id", ""): gs
                        for gs in cgs.get("global_systems", [])}

        for path in paths:
            # ── Forbidden path check ──────────────────────────────────────────
            if self._is_forbidden(path):
                forbidden.append(path)
                reasons.append(f"Path '{path}' touches a permanently forbidden field.")
                continue

            # ── Try each pattern ──────────────────────────────────────────────
            result = self._validate_one(path, mode_index, global_sys)
            if result is None:
                # Unknown grammar is not a production mutation surface.
                unknown.append(path)
                reasons.append(
                    f"Path grammar unrecognised and not allowed in production mutation: {path!r}."
                )
            elif result is not True:
                # result is an error string
                invalid.append(path)
                reasons.append(result)
            # else: valid

        all_invalid = invalid + unknown + forbidden
        return PathValidationResult(
            valid           = len(all_invalid) == 0,
            invalid_paths   = tuple(invalid),
            unknown_paths   = tuple(unknown),
            reasons         = tuple(reasons),
            forbidden_paths = tuple(forbidden),
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _is_forbidden(path: str) -> bool:
        return any(path.startswith(fp) for fp in _FORBIDDEN_PATH_PREFIXES)

    @staticmethod
    def _validate_one(
        path:       str,
        mode_index: dict[str, dict],   # mode_id → {actors, systems, rules}
        global_sys: dict[str, dict],
    ) -> bool | str | None:
        """
        Returns:
            True       — path is valid
            str        — error message (path is invalid)
            None       — grammar unrecognised (unknown, hard failure)
        """

        # global_systems[{id}]
        m = _GLOBAL_SYS_RE.match(path)
        if m:
            sid = m.group(1)
            if sid not in global_sys:
                return f"global_systems[{sid}] does not exist in CGS."
            return True

        # modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults.{field}
        m = _COMP_FIELD_RE.match(path)
        if m:
            mid, aid, tid_str, field_name = m.groups()
            return _check_comp_field(path, mid, aid, int(tid_str), field_name, mode_index)

        # modes[{mode_id}].actors[{actor_id}].components[{type_id}].defaults
        m = _COMP_DEFAULTS_RE.match(path)
        if m:
            mid, aid, tid_str = m.groups()
            return _check_comp_defaults(path, mid, aid, int(tid_str), mode_index)

        # modes[{mode_id}].actors[{actor_id}].components[{type_id}]
        m = _COMP_ROOT_RE.match(path)
        if m:
            mid, aid, tid_str = m.groups()
            return _check_comp_defaults(path, mid, aid, int(tid_str), mode_index)

        # modes[{mode_id}].actors[{actor_id}]
        m = _ACTOR_ROOT_RE.match(path)
        if m:
            mid, aid = m.groups()
            return _check_actor(path, mid, aid, mode_index)

        # modes[{mode_id}].actors[{actor_id}].{field}
        m = _ACTOR_FIELD_RE.match(path)
        if m:
            mid, aid, _ = m.groups()
            return _check_actor(path, mid, aid, mode_index)

        # modes[{mode_id}].systems[{system_id}]
        m = _SYSTEM_RE.match(path)
        if m:
            mid, sid = m.group(1), m.group(2)
            return _check_system(path, mid, sid, mode_index)

        # modes[{mode_id}].rules[{rule_id}]
        m = _RULE_RE.match(path)
        if m:
            mid, rid = m.group(1), m.group(2)
            return _check_rule(path, mid, rid, mode_index)

        # metadata — allowed paths (not forbidden ones, already checked)
        if path.startswith("metadata."):
            return True   # metadata.name etc. are valid

        # modes[{mode_id}].actors / modes[{mode_id}].systems — container paths
        if re.match(r'^modes\[[^\]]+\]\.(actors|systems|rules)$', path):
            mid = re.match(r'^modes\[([^\]]+)\]', path).group(1)
            if mid not in mode_index:
                return f"Mode '{mid}' does not exist in CGS."
            return True

        # modes[{mode_id}] root
        if re.match(r'^modes\[[^\]]+\]$', path):
            mid = re.match(r'^modes\[([^\]]+)\]', path).group(1)
            if mid not in mode_index:
                return f"Mode '{mid}' does not exist in CGS."
            return True

        return None   # unrecognised grammar

    # ── Index builder ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_mode_index(cgs: dict[str, Any]) -> dict[str, dict]:
        """
        Builds a lookup index:
        mode_id → {
            "actors":  {actor_id: {type_id: component_dict}},
            "systems": {system_id: system_dict},
            "rules":   {rule_id: rule_dict},
        }
        """
        index: dict[str, dict] = {}
        for mode in cgs.get("modes", []):
            mid     = mode.get("id", "")
            actors  = {}
            for actor in mode.get("actors", []):
                aid  = actor.get("id", "")
                comps = {c.get("type_id"): c for c in actor.get("components", [])}
                actors[aid] = comps
            systems = {s.get("id", ""): s for s in mode.get("systems", [])}
            rules   = {r.get("id", ""): r for r in mode.get("rules", [])}
            index[mid] = {"actors": actors, "systems": systems, "rules": rules}
        return index


# ── Helper Functions ──────────────────────────────────────────────────────────

def _check_actor(path: str, mid: str, aid: str,
                 mode_index: dict) -> bool | str:
    if mid not in mode_index:
        return f"Mode '{mid}' does not exist in CGS (path: {path!r})."
    if aid not in mode_index[mid]["actors"]:
        return f"Actor '{aid}' does not exist in mode '{mid}' (path: {path!r})."
    return True


def _check_comp_defaults(path: str, mid: str, aid: str, tid: int,
                          mode_index: dict) -> bool | str:
    actor_check = _check_actor(path, mid, aid, mode_index)
    if actor_check is not True:
        return actor_check
    comps = mode_index[mid]["actors"][aid]
    if tid not in comps:
        return (
            f"Component type_id={tid} does not exist on actor '{aid}' "
            f"in mode '{mid}' (path: {path!r})."
        )
    return True


def _check_comp_field(path: str, mid: str, aid: str, tid: int,
                       field_name: str, mode_index: dict) -> bool | str:
    comp_check = _check_comp_defaults(path, mid, aid, tid, mode_index)
    if comp_check is not True:
        return comp_check
    comp     = mode_index[mid]["actors"][aid][tid]
    defaults = comp.get("defaults", {})
    if field_name not in defaults:
        return (
            f"Field '{field_name}' does not exist in component type_id={tid} "
            f"defaults on actor '{aid}' (path: {path!r}). "
            f"Available fields: {sorted(defaults.keys())}"
        )
    return True


def _check_system(path: str, mid: str, sid: str,
                   mode_index: dict) -> bool | str:
    if mid not in mode_index:
        return f"Mode '{mid}' does not exist in CGS (path: {path!r})."
    if sid not in mode_index[mid]["systems"]:
        return (
            f"System '{sid}' does not exist in mode '{mid}' (path: {path!r}). "
            f"Available: {sorted(mode_index[mid]['systems'].keys())}"
        )
    return True


def _check_rule(path: str, mid: str, rid: str,
                 mode_index: dict) -> bool | str:
    if mid not in mode_index:
        return f"Mode '{mid}' does not exist in CGS (path: {path!r})."
    if rid not in mode_index[mid]["rules"]:
        return (
            f"Rule '{rid}' does not exist in mode '{mid}' (path: {path!r}). "
            f"Available: {sorted(mode_index[mid]['rules'].keys())}"
        )
    return True
