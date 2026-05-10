"""
path_parser.py — PathParser
==============================
Parses a fully-qualified DSL path string into a structured ParsedPath.

This is a pure string operation — no CGS is needed. The parser validates
that the path string is structurally correct (non-empty, no empty segments,
valid segment characters) but does NOT check whether the path resolves
to an existing node. That is PathResolver's job.

## Why a Separate Parser Layer?
The three-stage pipeline — parse → validate-structure → resolve-against-CGS —
gives clean error messages at each stage and enables path manipulation
(e.g. parent extraction, sibling generation) without needing the full CGS.

## Valid Path Grammar
    path        ::= segment ("." segment)*
    segment     ::= id_segment | type_id_segment | field_segment
    id_segment  ::= [a-z][a-z0-9_]*         (snake_case identifiers)
    type_id_seg ::= [0-9]+                   (positive integer, components)
    field_seg   ::= any non-empty string without dots

## Structural Rules Enforced by the Parser
    R1 — Path must not be empty or whitespace-only.
    R2 — Path must not start or end with a dot.
    R3 — No two consecutive dots (empty segment).
    R4 — Each segment must be non-empty.
    R5 — Segments must not contain whitespace.
    R6 — Path must start with a known root key.
    R7 — Path must have at least 2 segments (root alone is too partial).

## Known Root Keys
    "metadata", "global_systems", "modes"

Paths starting with anything else are rejected as implicit/partial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ── Parse Error ───────────────────────────────────────────────────────────────

class PathParseError(Exception):
    """Raised when a DSL path string fails structural validation."""


# ── Segment Types ─────────────────────────────────────────────────────────────

class SegmentKind(str):
    """Marker strings for segment classification."""
    ROOT       = "root"
    ENTITY_ID  = "entity_id"     # string ID for actors/systems/rules/modes
    TYPE_ID    = "type_id"       # integer ID for components
    FIELD_KEY  = "field_key"     # leaf field name in a defaults dict
    LIST_KEY   = "list_key"      # "actors", "systems", "rules", "components"


@dataclass(frozen=True)
class PathSegment:
    """One segment of a parsed DSL path."""
    value: str
    kind:  str   # one of SegmentKind constants
    index: int   # 0-based position in the path

    @property
    def is_integer(self) -> bool:
        return self.value.isdigit()

    @property
    def as_int(self) -> int:
        return int(self.value)

    def __repr__(self) -> str:
        return f"PathSegment({self.value!r}, {self.kind})"


# ── Parsed Path ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParsedPath:
    """
    Structured representation of a validated DSL path string.

    Attributes
    ----------
    raw : str
        The original unmodified path string.
    segments : tuple[PathSegment, ...]
        All segments in order.
    root : str
        The first segment value ("metadata", "global_systems", "modes").
    depth : int
        Number of segments (len(segments)).
    """

    raw:      str
    segments: tuple[PathSegment, ...]
    root:     str

    @property
    def depth(self) -> int:
        return len(self.segments)

    @property
    def leaf(self) -> PathSegment:
        """The last segment — the mutation target."""
        return self.segments[-1]

    @property
    def parent_path(self) -> str:
        """Returns the path string for the parent node (all but last segment)."""
        if self.depth <= 1:
            raise PathParseError(
                f"Path '{self.raw}' has only one segment — no parent."
            )
        return ".".join(s.value for s in self.segments[:-1])

    def sub_path(self, start: int, end: int | None = None) -> str:
        """Returns a sub-path from segment index start to end (exclusive)."""
        sliced = self.segments[start:end]
        if not sliced:
            raise PathParseError(
                f"sub_path({start}, {end}) on '{self.raw}' produces empty result."
            )
        return ".".join(s.value for s in sliced)

    def values(self) -> list[str]:
        """Returns all segment values as a plain list."""
        return [s.value for s in self.segments]

    def find_segment(self, value: str) -> PathSegment | None:
        """Returns the first segment with the given value, or None."""
        for seg in self.segments:
            if seg.value == value:
                return seg
        return None

    def contains_segment(self, value: str) -> bool:
        return any(s.value == value for s in self.segments)

    def __repr__(self) -> str:
        return f"ParsedPath({self.raw!r}, depth={self.depth})"


# ── Path Grammar Constants ────────────────────────────────────────────────────

_KNOWN_ROOT_KEYS: frozenset[str] = frozenset({
    "metadata",
    "global_systems",
    "modes",
})

_LIST_CONTAINER_KEYS: frozenset[str] = frozenset({
    "global_systems",
    "modes",
    "actors",
    "systems",
    "rules",
    "components",
})

_VALID_SEGMENT_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


# ── Path Parser ───────────────────────────────────────────────────────────────

class PathParser:
    """
    Parses and structurally validates DSL path strings.

    Stateless — safe to instantiate once and reuse.

    Usage
    -----
        parser = PathParser()
        parsed = parser.parse("modes.mode_default.actors.actor_player.components.100.defaults.current")
        print(parsed.depth)   # 8
        print(parsed.leaf)    # PathSegment("current", "field_key", 7)
        print(parsed.root)    # "modes"
    """

    def parse(self, path: str) -> ParsedPath:
        """
        Parses a DSL path string into a ParsedPath.

        Raises
        ------
        PathParseError
            If the path violates any structural rule R1–R7.
        """
        # R1 — Non-empty
        if not path or not path.strip():
            raise PathParseError(
                "DSL path must not be empty. "
                "Provide a fully-qualified path starting with "
                "'metadata', 'global_systems', or 'modes'."
            )

        stripped = path.strip()

        # R2 — No leading/trailing dots
        if stripped.startswith(".") or stripped.endswith("."):
            raise PathParseError(
                f"DSL path '{stripped}' must not start or end with a dot."
            )

        # R3 — No consecutive dots
        if ".." in stripped:
            raise PathParseError(
                f"DSL path '{stripped}' contains consecutive dots. "
                f"Each segment must be non-empty."
            )

        raw_segments = stripped.split(".")

        # R4+R5 — Each segment non-empty and no whitespace
        for i, seg in enumerate(raw_segments):
            if not seg:
                raise PathParseError(
                    f"DSL path '{stripped}' has an empty segment at position {i}."
                )
            if any(c in seg for c in (" ", "\t", "\n")):
                raise PathParseError(
                    f"DSL path '{stripped}' segment '{seg}' (position {i}) "
                    f"contains whitespace. Segments must not contain spaces."
                )

        # R6 — Must start with a known root key
        root = raw_segments[0]
        if root not in _KNOWN_ROOT_KEYS:
            raise PathParseError(
                f"DSL path '{stripped}' starts with '{root}' which is not a "
                f"known CGS root key. Valid roots: {sorted(_KNOWN_ROOT_KEYS)}. "
                f"Paths must be fully qualified from the CGS root — implicit "
                f"or partial paths are not permitted."
            )

        # R7 — At least 2 segments (root alone is too partial)
        if len(raw_segments) < 2:
            raise PathParseError(
                f"DSL path '{stripped}' has only one segment ('{root}'). "
                f"Paths must target a specific node, not just a root container. "
                f"Example: 'metadata.name' not 'metadata'."
            )

        # ── Classify segments ─────────────────────────────────────────────────
        segments = _classify_segments(raw_segments)

        return ParsedPath(
            raw=stripped,
            segments=tuple(segments),
            root=root,
        )

    def is_valid(self, path: str) -> bool:
        """Returns True if the path parses without error."""
        try:
            self.parse(path)
            return True
        except PathParseError:
            return False

    def parse_many(self, paths: list[str]) -> list[ParsedPath]:
        """Parses a list of paths, collecting all errors before raising."""
        errors: list[str] = []
        results: list[ParsedPath] = []
        for path in paths:
            try:
                results.append(self.parse(path))
            except PathParseError as exc:
                errors.append(str(exc))
        if errors:
            raise PathParseError(
                f"Path parsing failed for {len(errors)} path(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        return results


# ── Segment Classifier ────────────────────────────────────────────────────────

def _classify_segments(raw_segments: list[str]) -> list[PathSegment]:
    """
    Assigns a SegmentKind to each segment based on its position and value.

    Classification rules (applied in order):
    - Position 0 → ROOT
    - Segment is all digits → TYPE_ID (component lookup)
    - Previous segment is in _LIST_CONTAINER_KEYS → ENTITY_ID or TYPE_ID
    - Segment is in _LIST_CONTAINER_KEYS → LIST_KEY
    - Otherwise → FIELD_KEY
    """
    segments: list[PathSegment] = []
    prev = ""

    for i, value in enumerate(raw_segments):
        if i == 0:
            kind = SegmentKind.ROOT
        elif value.isdigit():
            kind = SegmentKind.TYPE_ID
        elif prev in _LIST_CONTAINER_KEYS:
            kind = SegmentKind.ENTITY_ID
        elif value in _LIST_CONTAINER_KEYS:
            kind = SegmentKind.LIST_KEY
        else:
            kind = SegmentKind.FIELD_KEY

        segments.append(PathSegment(value=value, kind=kind, index=i))
        prev = value

    return segments