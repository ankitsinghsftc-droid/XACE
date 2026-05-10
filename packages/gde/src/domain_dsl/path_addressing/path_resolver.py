"""
path_resolver.py — PathResolver
=================================
Resolves a ParsedPath (or raw path string) against the current CGS.

This is the single public entry point for all DSL path lookups in the GDE.
It combines PathParser + MutationTargetResolver into one clean call and
adds path-level caching to avoid redundant CGS traversals during a single
transaction's validation pass.

## Pipeline
    raw string
        → PathParser.parse()        → ParsedPath     (structural validation)
        → MutationTargetResolver    → ResolutionResult (CGS traversal)

## Caching
PathResolver maintains a per-CGS-hash cache of resolved paths. When the
CGS changes (new hash), the cache is invalidated. This means repeated reads
of the same path within one validation pass cost O(1) after the first call.

The cache is write-through: write-resolution results are NOT cached because
the write may change the CGS, making cached reads stale.

## Error Unification
Both PathParseError (structure) and SchemaResolutionError (not-found) are
unified into a single SchemaResolutionError at the PathResolver boundary.
Callers only need to catch one exception type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .path_parser import PathParser, ParsedPath, PathParseError
from ...cgs.mutation_target_resolver import (
    MutationTargetResolver,
    ResolutionResult,
    SchemaResolutionError,
)


# ── Path Resolver ─────────────────────────────────────────────────────────────

@dataclass
class PathResolver:
    """
    Unified entry point for DSL path parsing and CGS resolution.

    Combines PathParser + MutationTargetResolver with an optional
    per-CGS-hash read cache for performance during validation passes.

    Usage
    -----
        resolver = PathResolver()

        # Read — path must exist
        result = resolver.read("modes.mode_default.actors.actor_player", cgs)

        # Write — leaf may be new
        result = resolver.write(
            "modes.mode_default.actors.actor_player.components.200.defaults.speed",
            cgs
        )

        # Check existence without raising
        exists = resolver.exists("modes.mode_default.actors.actor_ghost", cgs)
    """

    _parser:   PathParser              = field(default_factory=PathParser, repr=False)
    _resolver: MutationTargetResolver  = field(default_factory=MutationTargetResolver, repr=False)

    # Read cache: cgs_hash → path_str → ResolutionResult
    _cache:      dict[str, dict[str, ResolutionResult]] = field(default_factory=dict, repr=False)
    _cache_hash: str                                     = field(default="", repr=False)

    # ── Public API ────────────────────────────────────────────────────────────

    def read(
        self,
        path: str,
        cgs:  dict[str, Any],
    ) -> ResolutionResult:
        """
        Resolves a path that must point to an existing CGS node.
        Result is cached by (cgs_hash, path).

        Raises
        ------
        SchemaResolutionError
            If the path is malformed or the node does not exist.
        """
        self._maybe_invalidate_cache(cgs)
        current_hash = _cgs_hash(cgs)

        if path in self._cache.get(current_hash, {}):
            return self._cache[current_hash][path]

        parsed = self._parse(path)
        result = self._resolver.resolve_for_read(parsed.raw, cgs)

        self._cache.setdefault(current_hash, {})[path] = result
        return result

    def write(
        self,
        path: str,
        cgs:  dict[str, Any],
    ) -> ResolutionResult:
        """
        Resolves a path for a write operation. The leaf may not exist yet.
        Results are NOT cached (writes may change the CGS).

        Raises
        ------
        SchemaResolutionError
            If the path is malformed or any non-leaf segment does not exist.
        """
        parsed = self._parse(path)
        return self._resolver.resolve_for_write(parsed.raw, cgs)

    def exists(
        self,
        path: str,
        cgs:  dict[str, Any],
    ) -> bool:
        """
        Returns True if the path resolves to an existing node.
        Never raises — returns False on any error.
        """
        try:
            self.read(path, cgs)
            return True
        except (SchemaResolutionError, PathParseError):
            return False

    def get_value(
        self,
        path: str,
        cgs:  dict[str, Any],
    ) -> Any:
        """
        Returns the value at the given path.

        Raises
        ------
        SchemaResolutionError
            If the path is malformed or the node does not exist.
        """
        result = self.read(path, cgs)
        return result.node

    def get_parent(
        self,
        path: str,
        cgs:  dict[str, Any],
    ) -> ResolutionResult:
        """
        Resolves to the parent of the target node.
        Useful when you need the containing dict or list.
        """
        parsed = self._parse(path)
        if parsed.depth < 2:
            raise SchemaResolutionError(
                f"Path '{path}' has only one segment — no parent to resolve."
            )
        return self.read(parsed.parent_path, cgs)

    def parsed(self, path: str) -> ParsedPath:
        """
        Returns the ParsedPath for a raw path string (structure only, no CGS).

        Raises
        ------
        SchemaResolutionError
            If the path is structurally invalid.
        """
        return self._parse(path)

    def invalidate_cache(self) -> None:
        """Clears the read cache. Call after any CGS mutation is committed."""
        self._cache.clear()
        self._cache_hash = ""

    # ── Batch Operations ──────────────────────────────────────────────────────

    def read_many(
        self,
        paths: list[str],
        cgs:   dict[str, Any],
    ) -> dict[str, ResolutionResult]:
        """
        Resolves multiple paths in one call. Collects all errors before raising.
        Returns a dict of path → ResolutionResult for all successful resolutions.

        Raises
        ------
        SchemaResolutionError
            If any path fails, with the full list of failures in the message.
        """
        errors:  list[str]                      = []
        results: dict[str, ResolutionResult]    = {}

        for path in paths:
            try:
                results[path] = self.read(path, cgs)
            except SchemaResolutionError as exc:
                errors.append(f"  '{path}': {exc}")

        if errors:
            raise SchemaResolutionError(
                f"Path resolution failed for {len(errors)} path(s):\n"
                + "\n".join(errors)
            )
        return results

    def all_exist(
        self,
        paths: list[str],
        cgs:   dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """
        Checks whether all paths exist in the CGS.
        Returns (all_exist: bool, missing_paths: list[str]).
        """
        missing = [p for p in paths if not self.exists(p, cgs)]
        return len(missing) == 0, missing

    # ── Internal ──────────────────────────────────────────────────────────────

    def _parse(self, path: str) -> ParsedPath:
        """Wraps PathParser.parse(), converting PathParseError → SchemaResolutionError."""
        try:
            return self._parser.parse(path)
        except PathParseError as exc:
            raise SchemaResolutionError(
                f"DSL path '{path}' failed structural validation: {exc}"
            ) from exc

    def _maybe_invalidate_cache(self, cgs: dict[str, Any]) -> None:
        """Invalidates the cache if the CGS has changed since last call."""
        current_hash = _cgs_hash(cgs)
        if current_hash != self._cache_hash:
            self._cache.clear()
            self._cache_hash = current_hash


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cgs_hash(cgs: dict[str, Any]) -> str:
    """
    Returns the cgs_hash from metadata, or empty string if absent.
    Used as cache key — avoids re-hashing the whole CGS every call.
    """
    return cgs.get("metadata", {}).get("cgs_hash", "")