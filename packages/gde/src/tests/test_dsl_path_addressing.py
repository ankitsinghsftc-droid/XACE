"""
tests/test_dsl_path_addressing.py
===================================
Tests for the DSL path addressing stack:
    PathParser, PathResolver, MutationTargetResolver
"""

from __future__ import annotations

import pytest
from typing import Any

from ..domain_dsl.path_addressing.path_parser import (
    PathParser, ParsedPath, PathParseError, SegmentKind,
)
from ..domain_dsl.path_addressing.path_resolver import PathResolver
from ..cgs.mutation_target_resolver import (
    MutationTargetResolver, SchemaResolutionError, ResolutionResult,
)


# ── Test CGS Fixture ──────────────────────────────────────────────────────────

def _cgs() -> dict[str, Any]:
    return {
        "metadata": {
            "name":     "Test Game",
            "version":  "0.1.0",
            "cgs_hash": "abc123",
        },
        "global_systems": [
            {
                "id":    "sys_input",
                "phase": "Input",
                "reads": [6], "writes": [5],
                "depends_on": [], "deterministic": True,
            }
        ],
        "modes": [
            {
                "id":             "mode_default",
                "display_name":   "Default",
                "is_default":     True,
                "schema_version": "0.1.0",
                "actors": [
                    {
                        "id":         "actor_player",
                        "actor_type": "PLAYER",
                        "components": [
                            {"type_id": 1,   "defaults": {"entity_name": "Player"}},
                            {"type_id": 100, "defaults": {"current": 80.0, "max": 100.0}},
                        ],
                    },
                    {
                        "id":         "actor_zombie",
                        "actor_type": "ENEMY",
                        "components": [
                            {"type_id": 100, "defaults": {"current": 30.0, "max": 30.0}},
                            {"type_id": 160, "defaults": {"detection_radius": 20.0}},
                        ],
                    },
                ],
                "systems": [
                    {"id": "sys_ai", "phase": "Simulation",
                     "reads": [160], "writes": [5], "depends_on": [], "deterministic": True},
                ],
                "rules": [
                    {"id": "rule_death", "condition": "health <= 0", "effect": "DESTROY"},
                ],
            }
        ],
    }


# ── PathParser Tests ──────────────────────────────────────────────────────────

class TestPathParser:

    def setup_method(self) -> None:
        self.parser = PathParser()

    # ── Valid paths ───────────────────────────────────────────────────────────

    def test_parse_metadata_name(self) -> None:
        parsed = self.parser.parse("metadata.name")
        assert parsed.root    == "metadata"
        assert parsed.depth   == 2
        assert parsed.leaf.value == "name"

    def test_parse_deep_actor_component_field(self) -> None:
        path   = "modes.mode_default.actors.actor_player.components.100.defaults.current"
        parsed = self.parser.parse(path)
        assert parsed.root  == "modes"
        assert parsed.depth == 8
        assert parsed.leaf.value == "current"

    def test_parse_global_system_field(self) -> None:
        parsed = self.parser.parse("global_systems.sys_input.phase")
        assert parsed.root == "global_systems"
        assert parsed.depth == 3

    def test_segment_kinds(self) -> None:
        parsed = self.parser.parse(
            "modes.mode_default.actors.actor_player.components.100.defaults.current"
        )
        kinds = [s.kind for s in parsed.segments]
        assert kinds[0] == SegmentKind.ROOT          # "modes"
        assert kinds[1] == SegmentKind.ENTITY_ID     # "mode_default"
        assert kinds[2] == SegmentKind.LIST_KEY      # "actors"
        assert kinds[3] == SegmentKind.ENTITY_ID     # "actor_player"
        assert kinds[4] == SegmentKind.LIST_KEY      # "components"
        assert kinds[5] == SegmentKind.TYPE_ID       # "100"
        assert kinds[6] == SegmentKind.FIELD_KEY     # "defaults"
        assert kinds[7] == SegmentKind.FIELD_KEY     # "current"

    def test_parent_path(self) -> None:
        parsed = self.parser.parse("modes.mode_default.actors.actor_player")
        assert parsed.parent_path == "modes.mode_default.actors"

    def test_values_list(self) -> None:
        parsed = self.parser.parse("metadata.name")
        assert parsed.values() == ["metadata", "name"]

    def test_contains_segment(self) -> None:
        parsed = self.parser.parse("modes.mode_default.actors.actor_player")
        assert parsed.contains_segment("actors")
        assert not parsed.contains_segment("systems")

    def test_is_valid_returns_true(self) -> None:
        assert self.parser.is_valid("metadata.name")
        assert self.parser.is_valid("modes.mode_default.actors.actor_player")

    # ── Invalid paths ─────────────────────────────────────────────────────────

    def test_empty_path_raises(self) -> None:
        with pytest.raises(PathParseError, match="empty"):
            self.parser.parse("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(PathParseError):
            self.parser.parse("   ")

    def test_leading_dot_raises(self) -> None:
        with pytest.raises(PathParseError, match="dot"):
            self.parser.parse(".metadata.name")

    def test_trailing_dot_raises(self) -> None:
        with pytest.raises(PathParseError, match="dot"):
            self.parser.parse("metadata.name.")

    def test_double_dot_raises(self) -> None:
        with pytest.raises(PathParseError, match="consecutive"):
            self.parser.parse("metadata..name")

    def test_unknown_root_raises(self) -> None:
        with pytest.raises(PathParseError, match="root"):
            self.parser.parse("actors.actor_player")

    def test_implicit_path_raises(self) -> None:
        with pytest.raises(PathParseError, match="root"):
            self.parser.parse("actor_player.health")

    def test_single_segment_raises(self) -> None:
        with pytest.raises(PathParseError, match="one segment"):
            self.parser.parse("metadata")

    def test_segment_with_whitespace_raises(self) -> None:
        with pytest.raises(PathParseError, match="whitespace"):
            self.parser.parse("modes.mode default.actors")

    def test_is_valid_false_for_invalid(self) -> None:
        assert not self.parser.is_valid("")
        assert not self.parser.is_valid("actor_player.health")
        assert not self.parser.is_valid("metadata")


# ── MutationTargetResolver Tests ──────────────────────────────────────────────

class TestMutationTargetResolver:

    def setup_method(self) -> None:
        self.resolver = MutationTargetResolver()
        self.cgs      = _cgs()

    def test_resolve_metadata_field(self) -> None:
        result = self.resolver.resolve_for_read("metadata.name", self.cgs)
        assert result.exists
        assert result.node == "Test Game"

    def test_resolve_nested_actor_field(self) -> None:
        path   = "modes.mode_default.actors.actor_player.components.100.defaults.current"
        result = self.resolver.resolve_for_read(path, self.cgs)
        assert result.exists
        assert result.node == 80.0

    def test_resolve_actor_by_id(self) -> None:
        result = self.resolver.resolve_for_read(
            "modes.mode_default.actors.actor_zombie", self.cgs
        )
        assert result.exists
        assert isinstance(result.node, dict)
        assert result.node["id"] == "actor_zombie"

    def test_resolve_component_by_type_id(self) -> None:
        result = self.resolver.resolve_for_read(
            "modes.mode_default.actors.actor_player.components.100", self.cgs
        )
        assert result.exists
        assert result.node["type_id"] == 100

    def test_resolve_system_in_mode(self) -> None:
        result = self.resolver.resolve_for_read(
            "modes.mode_default.systems.sys_ai", self.cgs
        )
        assert result.exists
        assert result.node["id"] == "sys_ai"

    def test_resolve_global_system(self) -> None:
        result = self.resolver.resolve_for_read(
            "global_systems.sys_input.phase", self.cgs
        )
        assert result.exists
        assert result.node == "Input"

    def test_resolve_rule(self) -> None:
        result = self.resolver.resolve_for_read(
            "modes.mode_default.rules.rule_death", self.cgs
        )
        assert result.exists
        assert result.node["id"] == "rule_death"

    def test_missing_actor_raises(self) -> None:
        with pytest.raises(SchemaResolutionError, match="actor_ghost"):
            self.resolver.resolve_for_read(
                "modes.mode_default.actors.actor_ghost", self.cgs
            )

    def test_missing_component_raises(self) -> None:
        with pytest.raises(SchemaResolutionError):
            self.resolver.resolve_for_read(
                "modes.mode_default.actors.actor_player.components.999", self.cgs
            )

    def test_missing_mode_raises(self) -> None:
        with pytest.raises(SchemaResolutionError, match="mode_arena"):
            self.resolver.resolve_for_read(
                "modes.mode_arena.actors.actor_player", self.cgs
            )

    def test_path_exists_true(self) -> None:
        assert self.resolver.path_exists("metadata.name", self.cgs)

    def test_path_exists_false(self) -> None:
        assert not self.resolver.path_exists(
            "modes.mode_default.actors.actor_ghost", self.cgs
        )

    def test_resolve_for_write_new_leaf(self) -> None:
        result = self.resolver.resolve_for_write(
            "modes.mode_default.actors.actor_player.components.100.defaults.regen_rate",
            self.cgs,
        )
        assert not result.exists
        assert result.key == "regen_rate"
        assert isinstance(result.parent, dict)

    def test_resolve_for_write_existing_leaf(self) -> None:
        result = self.resolver.resolve_for_write(
            "modes.mode_default.actors.actor_player.components.100.defaults.current",
            self.cgs,
        )
        assert result.exists
        assert result.node == 80.0


# ── PathResolver (Caching) Tests ──────────────────────────────────────────────

class TestPathResolver:

    def setup_method(self) -> None:
        self.resolver = PathResolver()
        self.cgs      = _cgs()

    def test_read_returns_value(self) -> None:
        result = self.resolver.read("metadata.name", self.cgs)
        assert result.node == "Test Game"

    def test_get_value_convenience(self) -> None:
        value = self.resolver.get_value("metadata.version", self.cgs)
        assert value == "0.1.0"

    def test_exists_true(self) -> None:
        assert self.resolver.exists("metadata.name", self.cgs)

    def test_exists_false(self) -> None:
        assert not self.resolver.exists("metadata.nonexistent", self.cgs)

    def test_write_new_leaf(self) -> None:
        result = self.resolver.write("metadata.new_field", self.cgs)
        assert not result.exists
        assert result.key == "new_field"

    def test_cache_hit_same_result(self) -> None:
        r1 = self.resolver.read("metadata.name", self.cgs)
        r2 = self.resolver.read("metadata.name", self.cgs)
        assert r1.node == r2.node

    def test_cache_invalidated_on_cgs_change(self) -> None:
        self.resolver.read("metadata.name", self.cgs)
        # Simulate CGS change — change hash
        modified = dict(self.cgs)
        modified["metadata"] = dict(self.cgs["metadata"])
        modified["metadata"]["cgs_hash"] = "newhash"
        modified["metadata"]["name"]     = "Changed"
        result = self.resolver.read("metadata.name", modified)
        assert result.node == "Changed"

    def test_read_many_success(self) -> None:
        paths   = ["metadata.name", "metadata.version"]
        results = self.resolver.read_many(paths, self.cgs)
        assert len(results) == 2
        assert results["metadata.name"].node == "Test Game"

    def test_read_many_partial_failure_raises(self) -> None:
        paths = ["metadata.name", "metadata.nonexistent"]
        with pytest.raises(SchemaResolutionError):
            self.resolver.read_many(paths, self.cgs)

    def test_all_exist_success(self) -> None:
        ok, missing = self.resolver.all_exist(
            ["metadata.name", "metadata.version"], self.cgs
        )
        assert ok
        assert missing == []

    def test_all_exist_failure(self) -> None:
        ok, missing = self.resolver.all_exist(
            ["metadata.name", "metadata.ghost"], self.cgs
        )
        assert not ok
        assert "metadata.ghost" in missing

    def test_invalid_path_raises_schema_resolution_error(self) -> None:
        with pytest.raises(SchemaResolutionError):
            self.resolver.read("actor_player.health", self.cgs)

    def test_get_parent(self) -> None:
        result = self.resolver.get_parent(
            "modes.mode_default.actors.actor_player", self.cgs
        )
        assert isinstance(result.node, list)  # actors list

    def test_parsed_returns_path_info(self) -> None:
        parsed = self.resolver.parsed("metadata.name")
        assert parsed.root == "metadata"
        assert parsed.depth == 2