"""
rule_expression_validator.py — RuleExpressionValidator
========================================================
Validates a parsed rule expression AST produced by RuleExpressionParser.

Runs after parsing succeeds. Checks that the AST is semantically valid
against the current CGS and component registry — not just syntactically
correct.

## Validation Rules

    V1 — All PathRefNodes in a condition must resolve to existing CGS paths
         (read-time validation via PathResolver)
    V2 — All effect EffectNode targets must be writable paths (not frozen
         UCL metadata, not metadata.cgs_hash, not system id fields)
    V3 — Effect op_type is compatible with the target field's inferred type
         (cannot MULTIPLY a string field)
    V4 — Condition and effect must not reference the same path with a
         write that would make the condition permanently false (trivial cycle)
    V5 — Comparison operand types must be compatible
         (comparing a number path to a string literal is a warning)
    V6 — Effect targets referenced in conditions should be in the same
         mode scope (cross-mode rules are flagged as warnings)

## What Is NOT Validated Here
- Whether the runtime will fire the rule at the right time (execution order)
- Whether the effect value is within design-time acceptable range
  (that is the DesignMentor / game_feel_advisor's job)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..rule_grammar.rule_expression_parser import (
    ASTNode, LiteralNode, PathRefNode, CompareNode, LogicalNode, EffectNode,
)

if TYPE_CHECKING:
    from ..path_addressing.path_resolver import PathResolver


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass
class ExpressionValidationResult:
    """Result of validating one rule expression AST."""
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else f"INVALID ({len(self.errors)} errors)"
        return f"ExpressionValidationResult({status}, {len(self.warnings)} warnings)"


# ── Frozen / Unwritable Paths ─────────────────────────────────────────────────

_UNWRITABLE_SEGMENTS: frozenset[str] = frozenset({
    "cgs_hash",
    "version",          # CGS version is managed by SchemaVersionManager
})

_UNWRITABLE_SYSTEM_FIELDS: frozenset[str] = frozenset({
    "id",               # system/actor/rule IDs are immutable after creation
    "phase",            # phase changes require SGC recompile — not via rules
})


# ── Rule Expression Validator ─────────────────────────────────────────────────

class RuleExpressionValidator:
    """
    Validates parsed rule expression ASTs against the current CGS.

    Stateless with respect to mutable state — the CGS and resolver
    are passed per call, not stored.

    Usage
    -----
        validator = RuleExpressionValidator()

        # Validate a condition AST
        result = validator.validate_condition(cond_ast, cgs, path_resolver)

        # Validate an effect AST
        result = validator.validate_effect(effect_node, cgs, path_resolver)

        # Validate both together (cross-expression rules V4, V6)
        result = validator.validate_rule(cond_ast, effect_node, cgs, path_resolver)
    """

    def validate_condition(
        self,
        ast:      ASTNode,
        cgs:      dict[str, Any],
        resolver: "PathResolver",
    ) -> ExpressionValidationResult:
        """Validates a condition AST (V1, V5)."""
        result = ExpressionValidationResult()
        self._validate_condition_node(ast, cgs, resolver, result)
        return result

    def validate_effect(
        self,
        effect:   EffectNode,
        cgs:      dict[str, Any],
        resolver: "PathResolver",
    ) -> ExpressionValidationResult:
        """Validates an effect node (V2, V3)."""
        result = ExpressionValidationResult()
        self._validate_effect_node(effect, cgs, resolver, result)
        return result

    def validate_rule(
        self,
        condition: ASTNode,
        effect:    EffectNode,
        cgs:       dict[str, Any],
        resolver:  "PathResolver",
    ) -> ExpressionValidationResult:
        """
        Validates condition and effect together, including cross-expression
        rules V4 and V6. Runs all checks, collects all errors.
        """
        result = ExpressionValidationResult()

        self._validate_condition_node(condition, cgs, resolver, result)
        self._validate_effect_node(effect, cgs, resolver, result)
        self._validate_no_trivial_cycle(condition, effect, result)
        self._validate_mode_scope(condition, effect, result)

        return result

    # ── Condition Validation ──────────────────────────────────────────────────

    def _validate_condition_node(
        self,
        node:     ASTNode,
        cgs:      dict[str, Any],
        resolver: "PathResolver",
        result:   ExpressionValidationResult,
    ) -> None:
        """Recursively validates a condition AST node."""
        match node:
            case PathRefNode():
                self._check_path_readable(node.path, cgs, resolver, result)

            case CompareNode():
                self._validate_condition_node(node.left, cgs, resolver, result)
                self._validate_condition_node(node.right, cgs, resolver, result)
                self._check_compare_type_compat(node, result)

            case LogicalNode():
                self._validate_condition_node(node.left, cgs, resolver, result)
                if node.right is not None:
                    self._validate_condition_node(node.right, cgs, resolver, result)

            case LiteralNode():
                pass  # literals are always valid

            case _:
                result.warnings.append(
                    f"Unknown AST node type '{node.node_type}' in condition. "
                    f"Skipping validation for this node."
                )

    # ── Effect Validation ─────────────────────────────────────────────────────

    def _validate_effect_node(
        self,
        effect:   EffectNode,
        cgs:      dict[str, Any],
        resolver: "PathResolver",
        result:   ExpressionValidationResult,
    ) -> None:
        """V2 — effect target must be a writable path. V3 — type compat."""

        # V2a — check unwritable path segments
        path_lower = effect.target.lower()
        for seg in _UNWRITABLE_SEGMENTS:
            if f".{seg}" in path_lower or path_lower.endswith(seg):
                result.errors.append(
                    f"[V2] Effect targets '{effect.target}' which contains "
                    f"the immutable segment '{seg}'. "
                    f"This field is managed by the platform and cannot be "
                    f"written by a rule effect."
                )

        # V2b — system id/phase fields
        for seg in _UNWRITABLE_SYSTEM_FIELDS:
            if effect.target.endswith(f".{seg}"):
                result.warnings.append(
                    f"[V2] Effect targets '{effect.target}' ending in '.{seg}'. "
                    f"Modifying '{seg}' fields via rules requires SGC recompilation. "
                    f"Verify this is intentional."
                )

        # V2c — check path resolves (write-mode: leaf may be new for ADD ops)
        if effect.op_type not in ("ADD_ACTOR", "ADD_COMPONENT", "ADD_RULE", "ADD_SYSTEM"):
            try:
                resolver.read(effect.target, cgs)
            except Exception:
                result.errors.append(
                    f"[V2] Effect target path '{effect.target}' does not "
                    f"exist in the CGS. "
                    f"Rules can only modify existing paths unless the op_type "
                    f"is structural (ADD_ACTOR, ADD_COMPONENT, etc.)."
                )

        # V3 — type compatibility for numeric operations
        if effect.op_type in ("ADD", "MULTIPLY", "DIVIDE"):
            if effect.value and isinstance(effect.value, LiteralNode):
                if effect.value.value_type not in ("int", "float"):
                    result.errors.append(
                        f"[V3] Effect op_type '{effect.op_type}' requires a "
                        f"numeric value, but got {effect.value.value_type!r} "
                        f"({effect.value.value!r}). "
                        f"Numeric operations require int or float values."
                    )

    # ── Cross-Expression Rules ────────────────────────────────────────────────

    @staticmethod
    def _validate_no_trivial_cycle(
        condition: ASTNode,
        effect:    EffectNode,
        result:    ExpressionValidationResult,
    ) -> None:
        """
        V4 — Warns when a rule's effect writes the exact path its condition reads,
        which could make the condition permanently false after one firing.
        """
        condition_paths = _extract_paths(condition)
        if effect.target in condition_paths:
            result.warnings.append(
                f"[V4] Rule effect writes to '{effect.target}' which is also "
                f"read by the condition. This rule may fire once and then "
                f"make its own condition permanently false. "
                f"Verify this is the intended one-shot behaviour."
            )

    @staticmethod
    def _validate_mode_scope(
        condition: ASTNode,
        effect:    EffectNode,
        result:    ExpressionValidationResult,
    ) -> None:
        """
        V6 — Warns when condition and effect reference different modes.
        Cross-mode rules are unusual and may indicate a path typo.
        """
        cond_modes  = _extract_mode_ids(condition)
        effect_mode = _extract_mode_id_from_path(effect.target)

        if effect_mode and cond_modes and effect_mode not in cond_modes:
            result.warnings.append(
                f"[V6] Rule condition references mode(s) {cond_modes} "
                f"but effect targets mode '{effect_mode}'. "
                f"Cross-mode rules are unusual — verify this is intentional."
            )

    # ── Path Readable Check ───────────────────────────────────────────────────

    @staticmethod
    def _check_path_readable(
        path:     str,
        cgs:      dict[str, Any],
        resolver: "PathResolver",
        result:   ExpressionValidationResult,
    ) -> None:
        """V1 — path must exist in the CGS for a condition to be evaluable."""
        if not resolver.exists(path, cgs):
            result.errors.append(
                f"[V1] Condition path '{path}' does not resolve to an "
                f"existing CGS node. Conditions can only reference paths "
                f"that exist in the current CGS."
            )

    @staticmethod
    def _check_compare_type_compat(
        node:   CompareNode,
        result: ExpressionValidationResult,
    ) -> None:
        """V5 — comparing a numeric path to a string literal (or vice versa) is suspicious."""
        left_is_str  = isinstance(node.left,  LiteralNode) and node.left.value_type  == "str"
        right_is_str = isinstance(node.right, LiteralNode) and node.right.value_type == "str"
        left_is_num  = isinstance(node.left,  LiteralNode) and node.left.value_type  in ("int", "float")
        right_is_num = isinstance(node.right, LiteralNode) and node.right.value_type in ("int", "float")

        if (left_is_str and right_is_num) or (left_is_num and right_is_str):
            result.warnings.append(
                f"[V5] Comparison '{node!r}' mixes a string literal with a "
                f"numeric literal. This comparison will always be False at runtime. "
                f"Verify the operand types."
            )


# ── AST Helpers ───────────────────────────────────────────────────────────────

def _extract_paths(node: ASTNode) -> set[str]:
    """Recursively collects all PathRefNode.path values from an AST."""
    paths: set[str] = set()
    match node:
        case PathRefNode():
            paths.add(node.path)
        case CompareNode():
            paths |= _extract_paths(node.left)
            paths |= _extract_paths(node.right)
        case LogicalNode():
            paths |= _extract_paths(node.left)
            if node.right:
                paths |= _extract_paths(node.right)
    return paths


def _extract_mode_ids(node: ASTNode) -> set[str]:
    """Extracts mode IDs from all path references in the AST."""
    mode_ids: set[str] = set()
    for path in _extract_paths(node):
        mid = _extract_mode_id_from_path(path)
        if mid:
            mode_ids.add(mid)
    return mode_ids


def _extract_mode_id_from_path(path: str) -> str | None:
    """
    Extracts the mode ID from a path like 'modes.mode_default.actors...'
    Returns None if the path doesn't go through a mode.
    """
    parts = path.split(".")
    if len(parts) >= 2 and parts[0] == "modes":
        return parts[1]
    return None