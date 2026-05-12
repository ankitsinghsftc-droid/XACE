"""
cache_key_builder.py — CacheKeyBuilder
========================================
Builds stable, compact cache keys for the response cache.

## Stability Requirement
Cache keys must be stable across cosmetic CGS changes — changes that
do not affect gameplay logic or which mutations are valid. Examples of
cosmetic changes that must NOT bust the cache:
    ✗ metadata.cgs_hash changes after every commit (volatile — excluded)
    ✗ metadata.version bumps (volatile — excluded)
    ✗ metadata.name / display names (cosmetic — excluded)
    ✗ snapshot timestamps (volatile — excluded)

Changes that MUST bust the cache (included in structural hash):
    ✓ actors added/removed/renamed
    ✓ component type_ids or defaults changed
    ✓ systems added/removed or phase/reads/writes changed
    ✓ rules added/removed/modified
    ✓ global_systems changed
    ✓ mode structure changed

## Key Format
    {intent_class}:{mode_name}:{structural_hash_prefix}

Example:
    "SetValue:COLLABORATIVE:a3f2bc7d1e9f4521"

The structural_hash_prefix is the first 16 hex chars of a SHA-256 hash
over the normalised structural content. 16 chars = 64 bits of space —
collision probability is negligible for per-project caches.

## What Goes Into the Structural Hash
    - All modes[] with all actors, components, systems, rules (sorted)
    - global_systems (sorted by id)
    - Excluded: metadata entirely (volatile)
    - Excluded: component defaults that are AssetReference objects
      (asset linking changes shouldn't bust the gameplay cache)

## Mode Profile in Key
The assistance mode (COLLABORATIVE, ADVANCED, etc.) is included because
the same intent against the same CGS may produce different responses
depending on whether the system is in FULLY_ASSISTED (verbose) vs
ARCHITECT_MODE (terse) — they should not share a cache.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


# ── Key Builder ───────────────────────────────────────────────────────────────

class CacheKeyBuilder:
    """
    Builds stable cache keys for InferenceAdapter's response cache.

    Stateless — one instance shared across all calls.

    Usage
    -----
        builder = CacheKeyBuilder()

        key = builder.build(
            intent_class        = "SetValue",
            structural_cgs_hash = builder.structural_hash(cgs),
            logical_model       = "standard_mutation",
        )
        # "SetValue:standard_mutation:a3f2bc7d1e9f4521"

        # Or with full CGS:
        key = builder.build_from_cgs(
            intent_class  = "SetValue",
            cgs           = current_cgs,
            logical_model = "standard_mutation",
        )
    """

    # Maximum key length — long enough to be unique, short enough for dict keys
    KEY_HASH_PREFIX_LEN = 16

    # Fields to exclude from structural hash (volatile/cosmetic)
    _EXCLUDED_METADATA_FIELDS = frozenset({
        "cgs_hash", "version", "name", "created_at", "updated_at",
        "display_name", "description", "session_id", "author",
    })

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self,
        intent_class:        str,
        structural_cgs_hash: str,
        logical_model:       str = "",
    ) -> str:
        """
        Builds a cache key from pre-computed components.

        Parameters
        ----------
        intent_class : str
            GDEIntentType string: "SetValue", "ScaleValue", etc.
        structural_cgs_hash : str
            Structural hash from structural_hash() — call that first.
        logical_model : str
            Logical model name — included so different model configs
            don't share cache entries for the same CGS + intent.

        Returns
        -------
        str
            Cache key in format "{intent}:{model}:{hash_prefix}"
        """
        safe_intent = self._sanitise_component(intent_class or "unknown")
        safe_model  = self._sanitise_component(logical_model or "default")
        prefix      = structural_cgs_hash[:self.KEY_HASH_PREFIX_LEN]
        return f"{safe_intent}:{safe_model}:{prefix}"

    def build_from_cgs(
        self,
        intent_class:  str,
        cgs:           dict[str, Any],
        logical_model: str = "",
    ) -> str:
        """
        Convenience: computes structural hash inline then builds the key.
        Slightly slower than build() — use when you don't cache the hash.
        """
        sh = self.structural_hash(cgs)
        return self.build(intent_class, sh, logical_model)

    def structural_hash(self, cgs: dict[str, Any]) -> str:
        """
        Computes a stable SHA-256 hash over the structural content of a CGS.

        Excludes volatile metadata fields. Normalises the content by
        sorting all collections deterministically before hashing.

        Returns
        -------
        str
            64-character hex SHA-256 digest.
        """
        structural = self._extract_structural(cgs)
        canonical  = json.dumps(
            structural,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=self._json_default,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def structural_hash_prefix(self, cgs: dict[str, Any]) -> str:
        """Returns just the first KEY_HASH_PREFIX_LEN chars of the structural hash."""
        return self.structural_hash(cgs)[:self.KEY_HASH_PREFIX_LEN]

    def is_valid_key(self, key: str) -> bool:
        """Returns True if the key matches the expected format."""
        parts = key.split(":")
        return (
            len(parts) == 3
            and all(len(p) > 0 for p in parts)
            and len(parts[2]) >= 8
        )

    def parse_key(self, key: str) -> dict[str, str] | None:
        """
        Parses a cache key back into its components.
        Returns None if the key is malformed.
        """
        parts = key.split(":")
        if len(parts) != 3:
            return None
        return {
            "intent_class":  parts[0],
            "logical_model": parts[1],
            "hash_prefix":   parts[2],
        }

    # ── Structural Extraction ─────────────────────────────────────────────────

    def _extract_structural(self, cgs: dict[str, Any]) -> dict[str, Any]:
        """
        Extracts only the structural content from a CGS dict.
        Sorts all lists by id field for determinism (D11).
        Strips AssetReference objects (asset linking is cosmetic).
        """
        structural: dict[str, Any] = {}

        # global_systems — sorted by id
        if "global_systems" in cgs:
            structural["global_systems"] = self._normalise_system_list(
                cgs["global_systems"]
            )

        # modes — sorted by id
        if "modes" in cgs:
            structural["modes"] = sorted(
                [self._normalise_mode(m) for m in cgs["modes"]],
                key=lambda m: m.get("id", ""),
            )

        return structural

    def _normalise_mode(self, mode: dict[str, Any]) -> dict[str, Any]:
        """Normalises one mode dict for hashing."""
        return {
            "id":             mode.get("id", ""),
            "is_default":     mode.get("is_default", False),
            "actors":         sorted(
                [self._normalise_actor(a) for a in mode.get("actors", [])],
                key=lambda a: a.get("id", ""),
            ),
            "systems":        self._normalise_system_list(mode.get("systems", [])),
            "rules":          sorted(
                [self._normalise_rule(r) for r in mode.get("rules", [])],
                key=lambda r: r.get("id", ""),
            ),
        }

    def _normalise_actor(self, actor: dict[str, Any]) -> dict[str, Any]:
        """Normalises one actor dict for hashing. Strips AssetReference values."""
        components = sorted(
            [self._normalise_component(c) for c in actor.get("components", [])],
            key=lambda c: c.get("type_id", 0),
        )
        return {
            "id":           actor.get("id", ""),
            "actor_type":   actor.get("actor_type", ""),
            "control_type": actor.get("control_type", ""),
            "tags":         sorted(actor.get("tags", [])),
            "components":   components,
        }

    def _normalise_component(self, comp: dict[str, Any]) -> dict[str, Any]:
        """Normalises one component dict. Strips AssetReference values."""
        raw_defaults = comp.get("defaults", {})
        clean_defaults: dict[str, Any] = {}
        for key, val in sorted(raw_defaults.items()):
            if self._is_asset_reference(val):
                # Asset linking is cosmetic — include type but not the ref details
                clean_defaults[key] = "__asset_ref__"
            else:
                clean_defaults[key] = val
        return {
            "type_id":  comp.get("type_id", 0),
            "defaults": clean_defaults,
        }

    @staticmethod
    def _normalise_system_list(systems: list) -> list[dict[str, Any]]:
        """Normalises and sorts a list of system dicts."""
        normalised = [
            {
                "id":            s.get("id", ""),
                "phase":         s.get("phase", ""),
                "reads":         sorted(s.get("reads", [])),
                "writes":        sorted(s.get("writes", [])),
                "depends_on":    sorted(s.get("depends_on", [])),
                "deterministic": s.get("deterministic", True),
            }
            for s in systems
            if isinstance(s, dict)
        ]
        return sorted(normalised, key=lambda s: s.get("id", ""))

    @staticmethod
    def _normalise_rule(rule: dict[str, Any]) -> dict[str, Any]:
        return {
            "id":        rule.get("id", ""),
            "condition": rule.get("condition", ""),
            "effect":    rule.get("effect", ""),
            "priority":  rule.get("priority", 0),
            "is_active": rule.get("is_active", True),
        }

    @staticmethod
    def _is_asset_reference(value: Any) -> bool:
        """Returns True if value looks like an AssetReference dict."""
        return (
            isinstance(value, dict)
            and "status" in value
            and value.get("status") in ("PLACEHOLDER", "LINKED", "MISSING", "UNRESOLVED")
        )

    @staticmethod
    def _sanitise_component(text: str) -> str:
        """Strips characters that would break the colon-separated key format."""
        return re.sub(r'[^a-zA-Z0-9_\-]', '_', text)[:32]

    @staticmethod
    def _json_default(obj: Any) -> str:
        """Fallback serialiser for non-JSON-native types."""
        return str(obj)