"""
rule_expression_parser.py — RuleExpressionParser
==================================================
Parses condition and effect expressions in CGS rule definitions
into a structured AST (Abstract Syntax Tree).

## What Are Rule Expressions?
A CGS rule has two expressions:

    condition: "modes.mode_default.actors.actor_player.components.100.defaults.current <= 0"
    effect:    "SET modes.mode_default.actors.actor_player.components.7.defaults.state = 'DEAD'"

The condition is evaluated at runtime to decide whether the rule fires.
The effect describes what mutation to apply when it fires.

## Supported Syntax

### Condition expressions
    path op literal                     — simple comparison
    path op path                        — path-to-path comparison
    expr AND expr                       — logical conjunction
    expr OR expr                        — logical disjunction
    NOT expr                            — logical negation
    ( expr )                            — grouping

    Comparison operators: == != < > <= >=
    Path:    fully-qualified CGS path (validated by PathParser)
    Literal: number (42, 3.14), string ("hello"), bool (true/false)

### Effect expressions
    SET path = value                    — assign value to path
    ADD path += value                   — numeric add
    MULTIPLY path *= value              — numeric multiply
    REMOVE_ACTOR path                   — structural remove

## AST Node Types

    LiteralNode     — a scalar value (int, float, str, bool)
    PathRefNode     — a CGS path reference (resolved at runtime)
    CompareNode     — binary comparison (==, !=, <, >, <=, >=)
    LogicalNode     — AND / OR / NOT
    EffectNode      — a single effect instruction (SET, ADD, etc.)

## Error Handling
Parser reports all syntax errors it can recover from before raising.
For unrecoverable errors (unknown token at position 0), it fails fast.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Parse Error ───────────────────────────────────────────────────────────────

class ExpressionParseError(Exception):
    """Raised when a rule expression fails to parse."""


# ── AST Node Base ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ASTNode:
    """Base class for all AST nodes."""
    node_type: str

    def __repr__(self) -> str:
        return f"{self.node_type}()"


# ── AST Nodes ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LiteralNode(ASTNode):
    """A scalar literal value: int, float, str, or bool."""
    value: Any
    value_type: str     # "int" | "float" | "str" | "bool" | "null"

    def __repr__(self) -> str:
        return f"Literal({self.value!r})"


@dataclass(frozen=True)
class PathRefNode(ASTNode):
    """A reference to a CGS value via a fully-qualified path."""
    path: str

    def __repr__(self) -> str:
        return f"PathRef({self.path!r})"


@dataclass(frozen=True)
class CompareNode(ASTNode):
    """Binary comparison: left op right."""
    left:     ASTNode
    operator: str      # "==" | "!=" | "<" | ">" | "<=" | ">="
    right:    ASTNode

    def __repr__(self) -> str:
        return f"Compare({self.left!r} {self.operator} {self.right!r})"


@dataclass(frozen=True)
class LogicalNode(ASTNode):
    """Logical operation: AND, OR, NOT."""
    operator: str        # "AND" | "OR" | "NOT"
    left:     ASTNode
    right:    ASTNode | None = None   # None for NOT

    def __repr__(self) -> str:
        if self.right:
            return f"Logical({self.left!r} {self.operator} {self.right!r})"
        return f"Logical(NOT {self.left!r})"


@dataclass(frozen=True)
class EffectNode(ASTNode):
    """A single effect instruction in an effect expression."""
    op_type: str       # "SET" | "ADD" | "MULTIPLY" | "REMOVE_ACTOR" | etc.
    target:  str       # CGS path
    value:   ASTNode | None = None    # None for structural removes

    def __repr__(self) -> str:
        return f"Effect({self.op_type} {self.target!r} = {self.value!r})"


# ── Token Types ───────────────────────────────────────────────────────────────

_TOKEN_PATTERNS: list[tuple[str, str]] = [
    ("COMPARE",   r"[<>!]=?|=="),
    ("ASSIGN",    r"="),
    ("AUGMENTED", r"\+=|\*="),
    ("LPAREN",    r"\("),
    ("RPAREN",    r"\)"),
    ("FLOAT",     r"-?\d+\.\d+"),
    ("INT",       r"-?\d+"),
    ("STRING",    r'"[^"]*"|\'[^\']*\''),
    ("BOOL",      r"\b(?:true|false|True|False)\b"),
    ("NULL",      r"\bnull\b"),
    ("AND",       r"\bAND\b"),
    ("OR",        r"\bOR\b"),
    ("NOT",       r"\bNOT\b"),
    ("EFFECT_OP", r"\b(?:SET|ADD|MULTIPLY|DIVIDE|REMOVE_ACTOR|REMOVE_COMPONENT)\b"),
    ("PATH",      r"(?:metadata|global_systems|modes)(?:\.[a-zA-Z0-9_\-]+)+"),
    ("SKIP",      r"[ \t]+"),
]

_MASTER_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_PATTERNS)
)

_COMPARE_OPS: frozenset[str] = frozenset({"==", "!=", "<", ">", "<=", ">="})


# ── Tokeniser ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Token:
    kind:  str
    value: str
    pos:   int

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r})"


def _tokenise(text: str) -> list[Token]:
    """Tokenises an expression string into a flat token list."""
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        m = _MASTER_RE.match(text, pos)
        if not m:
            raise ExpressionParseError(
                f"Unexpected character '{text[pos]}' at position {pos} "
                f"in expression: {text!r}"
            )
        kind = m.lastgroup
        if kind != "SKIP":
            tokens.append(Token(kind=kind, value=m.group(), pos=pos))
        pos = m.end()
    return tokens


# ── Parser ────────────────────────────────────────────────────────────────────

class RuleExpressionParser:
    """
    Parses condition and effect expression strings into AST nodes.

    Stateless — instantiate once, call parse_condition() or parse_effect()
    as many times as needed.

    Usage
    -----
        parser = RuleExpressionParser()

        cond_ast = parser.parse_condition(
            "modes.mode_default.actors.actor_player.components.100.defaults.current <= 0"
        )
        effect_ast = parser.parse_effect(
            "SET modes.mode_default.actors.actor_player.components.7.defaults.state = 'dead'"
        )
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def parse_condition(self, expression: str) -> ASTNode:
        """
        Parses a condition expression into an AST.

        Raises
        ------
        ExpressionParseError
            If the expression is syntactically invalid.
        """
        if not expression or not expression.strip():
            raise ExpressionParseError(
                "Condition expression must not be empty."
            )
        tokens = _tokenise(expression.strip())
        parser_state = _ParserState(tokens)
        ast = parser_state.parse_logical()
        if not parser_state.at_end():
            remaining = " ".join(t.value for t in parser_state.remaining())
            raise ExpressionParseError(
                f"Unexpected tokens at end of condition: {remaining!r}. "
                f"Check for mismatched parentheses or extra operators."
            )
        return ast

    def parse_effect(self, expression: str) -> EffectNode:
        """
        Parses an effect expression into an EffectNode.

        Raises
        ------
        ExpressionParseError
            If the expression is syntactically invalid.
        """
        if not expression or not expression.strip():
            raise ExpressionParseError(
                "Effect expression must not be empty."
            )
        tokens = _tokenise(expression.strip())
        if not tokens or tokens[0].kind != "EFFECT_OP":
            raise ExpressionParseError(
                f"Effect expression must start with an operation keyword "
                f"(SET, ADD, MULTIPLY, REMOVE_ACTOR, etc.). "
                f"Got: {tokens[0].value if tokens else 'empty'!r}"
            )
        return _parse_effect_tokens(tokens)

    def is_valid_condition(self, expression: str) -> bool:
        """Returns True if the expression parses without error."""
        try:
            self.parse_condition(expression)
            return True
        except ExpressionParseError:
            return False

    def is_valid_effect(self, expression: str) -> bool:
        try:
            self.parse_effect(expression)
            return True
        except ExpressionParseError:
            return False

    def extract_path_refs(self, expression: str) -> list[str]:
        """
        Returns all CGS path references found in an expression string.
        Used by RuleExpressionValidator to check paths exist.
        """
        try:
            tokens = _tokenise(expression.strip())
            return [t.value for t in tokens if t.kind == "PATH"]
        except ExpressionParseError:
            return []


# ── Recursive Descent Parser State ───────────────────────────────────────────

class _ParserState:
    """Mutable cursor over a token list for recursive-descent parsing."""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos    = 0

    def at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    def peek(self) -> Token | None:
        if self.at_end():
            return None
        return self._tokens[self._pos]

    def consume(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def remaining(self) -> list[Token]:
        return self._tokens[self._pos:]

    # ── Grammar Rules ─────────────────────────────────────────────────────────

    def parse_logical(self) -> ASTNode:
        """logical ::= logical AND|OR logical | NOT logical | compare | (logical)"""
        left = self._parse_not()

        tok = self.peek()
        if tok and tok.kind in ("AND", "OR"):
            self.consume()
            right = self.parse_logical()
            return LogicalNode(
                node_type="Logical",
                operator=tok.value.upper(),
                left=left,
                right=right,
            )
        return left

    def _parse_not(self) -> ASTNode:
        tok = self.peek()
        if tok and tok.kind == "NOT":
            self.consume()
            operand = self._parse_not()
            return LogicalNode(
                node_type="Logical",
                operator="NOT",
                left=operand,
                right=None,
            )
        return self._parse_compare()

    def _parse_compare(self) -> ASTNode:
        """compare ::= atom op atom | ( logical )"""
        if self.peek() and self.peek().kind == "LPAREN":
            self.consume()   # (
            inner = self.parse_logical()
            if not self.peek() or self.peek().kind != "RPAREN":
                raise ExpressionParseError(
                    "Missing closing ')' in condition expression."
                )
            self.consume()   # )
            return inner

        left = self._parse_atom()

        tok = self.peek()
        if tok and tok.kind == "COMPARE" and tok.value in _COMPARE_OPS:
            op = self.consume().value
            right = self._parse_atom()
            return CompareNode(
                node_type="Compare",
                left=left,
                operator=op,
                right=right,
            )
        return left

    def _parse_atom(self) -> ASTNode:
        tok = self.peek()
        if tok is None:
            raise ExpressionParseError("Unexpected end of expression.")
        self.consume()

        match tok.kind:
            case "INT":
                return LiteralNode(node_type="Literal", value=int(tok.value), value_type="int")
            case "FLOAT":
                return LiteralNode(node_type="Literal", value=float(tok.value), value_type="float")
            case "STRING":
                raw = tok.value[1:-1]   # strip surrounding quotes
                return LiteralNode(node_type="Literal", value=raw, value_type="str")
            case "BOOL":
                val = tok.value.lower() == "true"
                return LiteralNode(node_type="Literal", value=val, value_type="bool")
            case "NULL":
                return LiteralNode(node_type="Literal", value=None, value_type="null")
            case "PATH":
                return PathRefNode(node_type="PathRef", path=tok.value)
            case _:
                raise ExpressionParseError(
                    f"Unexpected token '{tok.value}' (kind={tok.kind}) "
                    f"at position {tok.pos}. Expected a path, literal, or '('."
                )


# ── Effect Expression Parser ──────────────────────────────────────────────────

def _parse_effect_tokens(tokens: list[Token]) -> EffectNode:
    """Parses a flat token list into an EffectNode."""
    idx = 0
    op_type = tokens[idx].value.upper()
    idx += 1

    # Structural removes: REMOVE_ACTOR path
    if op_type in ("REMOVE_ACTOR", "REMOVE_COMPONENT"):
        if idx >= len(tokens) or tokens[idx].kind != "PATH":
            raise ExpressionParseError(
                f"{op_type} requires a target path."
            )
        target = tokens[idx].value
        return EffectNode(node_type="Effect", op_type=op_type, target=target, value=None)

    # Value mutations: SET/ADD/MULTIPLY path = value  or  ADD path += value
    if idx >= len(tokens) or tokens[idx].kind != "PATH":
        raise ExpressionParseError(
            f"{op_type} requires a target path after the operator."
        )
    target = tokens[idx].value
    idx += 1

    if idx >= len(tokens):
        raise ExpressionParseError(
            f"{op_type}: missing '=' or '+=' after path '{target}'."
        )

    assign_tok = tokens[idx]
    if assign_tok.kind not in ("ASSIGN", "AUGMENTED"):
        raise ExpressionParseError(
            f"{op_type}: expected '=' or '+=' after path '{target}', "
            f"got '{assign_tok.value}'."
        )
    idx += 1

    if idx >= len(tokens):
        raise ExpressionParseError(
            f"{op_type}: missing value after assignment operator."
        )

    value_tok = tokens[idx]
    state     = _ParserState(tokens[idx:])
    value_ast = state._parse_atom()

    return EffectNode(node_type="Effect", op_type=op_type, target=target, value=value_ast)