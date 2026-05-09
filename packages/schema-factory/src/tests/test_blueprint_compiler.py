"""
tests/test_blueprint_compiler.py
=================================
Tests for the entity blueprint pipeline:
    EntityBlueprint, EntityBlueprintBuilder,
    BlueprintRegistry, BlueprintCompiler

All tests use a minimal StubRegistry that satisfies ComponentRegistryProtocol.
This decouples the tests from the concrete DCL registry (Phase 1).
"""

from __future__ import annotations

import pytest
from typing import Any

from ..entity_blueprint.entity_blueprint import EntityBlueprint, EntityBlueprintBuilder
from ..entity_blueprint.blueprint_registry import BlueprintRegistry, BlueprintRegistryError
from ..entity_blueprint.blueprint_compiler import (
    BlueprintCompiler,
    BlueprintCompilationError,
    ComponentRegistryProtocol,
)


# ── Stub Registry ─────────────────────────────────────────────────────────────

class StubRegistry:
    """Minimal ComponentRegistryProtocol implementation for tests."""

    def __init__(self, registered: dict[int, set[str]] | None = None) -> None:
        # type_id → valid field names (empty set = any field allowed)
        self._data: dict[int, set[str]] = registered or {
            1:   {"entity_name", "entity_type", "tags"},       # COMP_IDENTITY_V1
            100: {"current", "max", "regen_rate", "is_invincible"},  # COMP_HEALTH_V1
            160: {"behavior_model", "detection_radius", "aggression_level"},  # COMP_AI_V1
            5:   {"linear", "angular", "max_linear_speed"},    # COMP_VELOCITY_V1
        }

    def has_component(self, type_id: int) -> bool:
        return type_id in self._data

    def get_field_names(self, type_id: int) -> set[str]:
        return self._data.get(type_id, set())


_REGISTRY = StubRegistry()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _actor(
    actor_id:     str = "actor_zombie",
    actor_type:   str = "ENEMY",
    control_type: str = "AI_PROXY",
    components:   list | None = None,
    tags:         list | None = None,
    mode_scope:   list | None = None,
) -> dict[str, Any]:
    return {
        "id":           actor_id,
        "actor_type":   actor_type,
        "control_type": control_type,
        "components":   components or [],
        "tags":         tags or [],
        "mode_scope":   mode_scope or [],
    }


def _comp(type_id: int, defaults: dict | None = None) -> dict[str, Any]:
    return {"type_id": type_id, "defaults": defaults or {}}


# ── EntityBlueprint ───────────────────────────────────────────────────────────

class TestEntityBlueprint:

    def test_frozen_after_creation(self) -> None:
        bp = EntityBlueprint(
            id="actor_a",
            actor_type="ENEMY",
            component_defaults={100: {"current": 80}},
        )
        with pytest.raises(Exception):
            bp.id = "mutated"  # type: ignore[misc]

    def test_has_component_true(self) -> None:
        bp = EntityBlueprint(
            id="actor_a", actor_type="PLAYER",
            component_defaults={1: {}, 100: {"current": 80}},
        )
        assert bp.has_component(100)
        assert bp.has_component(1)
        assert not bp.has_component(999)

    def test_component_ids_sorted(self) -> None:
        bp = EntityBlueprint(
            id="actor_a", actor_type="ENEMY",
            component_defaults={160: {}, 1: {}, 100: {}},
        )
        assert bp.component_ids() == [1, 100, 160]

    def test_defaults_for_returns_copy(self) -> None:
        original = {"current": 80}
        bp = EntityBlueprint(
            id="actor_a", actor_type="ENEMY",
            component_defaults={100: original},
        )
        returned = bp.defaults_for(100)
        returned["current"] = 999
        # Original inside blueprint must be untouched
        assert bp.defaults_for(100)["current"] == 80

    def test_defaults_for_missing_returns_empty(self) -> None:
        bp = EntityBlueprint(id="actor_a", actor_type="ENEMY", component_defaults={})
        assert bp.defaults_for(999) == {}

    def test_is_active_in_mode_empty_scope_is_all(self) -> None:
        bp = EntityBlueprint(id="a", actor_type="ENEMY", component_defaults={}, mode_scope=())
        assert bp.is_active_in_mode("mode_survival")
        assert bp.is_active_in_mode("mode_creative")

    def test_is_active_in_mode_scoped(self) -> None:
        bp = EntityBlueprint(
            id="a", actor_type="ENEMY",
            component_defaults={},
            mode_scope=("mode_survival",),
        )
        assert bp.is_active_in_mode("mode_survival")
        assert not bp.is_active_in_mode("mode_creative")

    def test_is_player_controlled(self) -> None:
        human_bp = EntityBlueprint(
            id="a", actor_type="PLAYER", component_defaults={}, control_type="HUMAN"
        )
        ai_bp = EntityBlueprint(
            id="b", actor_type="ENEMY", component_defaults={}, control_type="AI_PROXY"
        )
        assert human_bp.is_player_controlled()
        assert not ai_bp.is_player_controlled()


# ── EntityBlueprintBuilder ────────────────────────────────────────────────────

class TestEntityBlueprintBuilder:

    def test_build_produces_frozen_blueprint(self) -> None:
        bp = (
            EntityBlueprintBuilder("actor_x", "PLAYER")
            .set_component_defaults(1, {"entity_name": "Player"})
            .add_tag("hero")
            .build()
        )
        assert isinstance(bp, EntityBlueprint)
        assert bp.id == "actor_x"
        assert bp.has_component(1)

    def test_tags_are_sorted_for_determinism(self) -> None:
        bp = (
            EntityBlueprintBuilder("a", "PLAYER")
            .add_tag("zeta")
            .add_tag("alpha")
            .add_tag("mid")
            .build()
        )
        assert bp.tags == ("alpha", "mid", "zeta")

    def test_duplicate_tags_deduplicated(self) -> None:
        bp = (
            EntityBlueprintBuilder("a", "ENEMY")
            .add_tag("hostile")
            .add_tag("hostile")
            .build()
        )
        assert bp.tags.count("hostile") == 1

    def test_mode_scope_stored_correctly(self) -> None:
        bp = (
            EntityBlueprintBuilder("a", "ENEMY")
            .set_mode_scope(["mode_survival", "mode_arena"])
            .build()
        )
        assert "mode_survival" in bp.mode_scope
        assert "mode_arena" in bp.mode_scope


# ── BlueprintRegistry ─────────────────────────────────────────────────────────

class TestBlueprintRegistry:

    def _make_bp(self, bp_id: str, actor_type: str = "ENEMY") -> EntityBlueprint:
        return EntityBlueprint(
            id=bp_id, actor_type=actor_type, component_defaults={100: {"current": 80}}
        )

    def test_register_and_get(self) -> None:
        registry = BlueprintRegistry()
        bp = self._make_bp("actor_zombie")
        registry.register(bp)
        assert registry.get("actor_zombie") is bp

    def test_get_missing_returns_none(self) -> None:
        registry = BlueprintRegistry()
        assert registry.get("actor_ghost") is None

    def test_get_required_raises_on_missing(self) -> None:
        registry = BlueprintRegistry()
        with pytest.raises(BlueprintRegistryError, match="actor_ghost"):
            registry.get_required("actor_ghost")

    def test_duplicate_registration_raises(self) -> None:
        registry = BlueprintRegistry()
        registry.register(self._make_bp("actor_zombie"))
        with pytest.raises(BlueprintRegistryError, match="already registered"):
            registry.register(self._make_bp("actor_zombie"))

    def test_register_all_atomic_on_duplicate(self) -> None:
        registry = BlueprintRegistry()
        blueprints = [
            self._make_bp("actor_a"),
            self._make_bp("actor_b"),
            self._make_bp("actor_a"),  # duplicate — causes failure
        ]
        with pytest.raises(BlueprintRegistryError):
            registry.register_all(blueprints)
        # Atomicity: nothing should have been registered
        assert len(registry) == 0

    def test_all_blueprints_sorted_by_id(self) -> None:
        registry = BlueprintRegistry()
        for bp_id in ["actor_z", "actor_a", "actor_m"]:
            registry.register(self._make_bp(bp_id))
        ids = [bp.id for bp in registry.all_blueprints()]
        assert ids == sorted(ids)

    def test_get_by_actor_type(self) -> None:
        registry = BlueprintRegistry()
        registry.register(self._make_bp("actor_zombie", "ENEMY"))
        registry.register(self._make_bp("actor_skeleton", "ENEMY"))
        registry.register(
            EntityBlueprint(id="actor_player", actor_type="PLAYER", component_defaults={})
        )
        enemies = registry.get_by_actor_type("ENEMY")
        assert len(enemies) == 2
        assert all(b.actor_type == "ENEMY" for b in enemies)
        assert [b.id for b in enemies] == sorted(b.id for b in enemies)

    def test_get_with_component(self) -> None:
        registry = BlueprintRegistry()
        registry.register(EntityBlueprint(
            id="actor_a", actor_type="ENEMY",
            component_defaults={100: {}, 160: {}}
        ))
        registry.register(EntityBlueprint(
            id="actor_b", actor_type="ENEMY",
            component_defaults={100: {}}
        ))
        registry.register(EntityBlueprint(
            id="actor_c", actor_type="PLAYER",
            component_defaults={1: {}}
        ))
        with_health  = registry.get_with_component(100)
        with_ai      = registry.get_with_component(160)
        assert len(with_health) == 2
        assert len(with_ai)     == 1

    def test_validate_no_orphaned_components(self) -> None:
        registry = BlueprintRegistry()
        registry.register(EntityBlueprint(
            id="actor_a", actor_type="ENEMY",
            component_defaults={100: {}, 99999: {}}  # 99999 = unregistered
        ))
        errors = registry.validate_no_orphaned_components(valid_component_type_ids={1, 100, 160})
        assert len(errors) == 1
        assert "99999" in errors[0]

    def test_len_and_contains(self) -> None:
        registry = BlueprintRegistry()
        assert len(registry) == 0
        registry.register(self._make_bp("actor_a"))
        assert len(registry) == 1
        assert registry.contains("actor_a")
        assert not registry.contains("actor_ghost")


# ── BlueprintCompiler ─────────────────────────────────────────────────────────

class TestBlueprintCompiler:

    def setup_method(self) -> None:
        self.compiler = BlueprintCompiler(_REGISTRY)

    # ── compile_one — success ─────────────────────────────────────────────────

    def test_compile_one_minimal_valid(self) -> None:
        defn = _actor("actor_zombie", components=[_comp(100, {"current": 80, "max": 80})])
        bp = self.compiler.compile_one(defn)
        assert bp.id == "actor_zombie"
        assert bp.actor_type == "ENEMY"
        assert bp.has_component(100)
        assert bp.defaults_for(100)["current"] == 80

    def test_compile_one_sets_control_type(self) -> None:
        defn = _actor("actor_player", actor_type="PLAYER", control_type="HUMAN")
        bp = self.compiler.compile_one(defn)
        assert bp.is_player_controlled()

    def test_compile_one_sets_tags(self) -> None:
        defn = _actor("actor_zombie", tags=["hostile", "undead"])
        bp = self.compiler.compile_one(defn)
        assert "hostile" in bp.tags
        assert "undead" in bp.tags

    def test_compile_one_sets_mode_scope(self) -> None:
        defn = _actor("actor_a", mode_scope=["mode_survival"])
        bp = self.compiler.compile_one(defn)
        assert bp.is_active_in_mode("mode_survival")
        assert not bp.is_active_in_mode("mode_creative")

    def test_compile_one_schema_version_stored(self) -> None:
        defn = _actor("actor_a")
        bp = self.compiler.compile_one(defn, schema_version="0.2.0")
        assert bp.schema_version == "0.2.0"

    # ── compile_one — failure ─────────────────────────────────────────────────

    def test_empty_id_rejected(self) -> None:
        defn = _actor("")
        with pytest.raises(BlueprintCompilationError) as exc_info:
            self.compiler.compile_one(defn)
        assert exc_info.value.errors

    def test_unknown_actor_type_rejected(self) -> None:
        defn = _actor("actor_a", actor_type="SPACESHIP")
        with pytest.raises(BlueprintCompilationError, match="SPACESHIP"):
            self.compiler.compile_one(defn)

    def test_unregistered_component_type_id_rejected(self) -> None:
        defn = _actor("actor_a", components=[_comp(9999)])
        with pytest.raises(BlueprintCompilationError, match="9999"):
            self.compiler.compile_one(defn)

    def test_invalid_field_name_rejected(self) -> None:
        # COMP_HEALTH_V1 (100) does not have field "nonexistent_field"
        defn = _actor("actor_a", components=[_comp(100, {"nonexistent_field": 42})])
        with pytest.raises(BlueprintCompilationError, match="nonexistent_field"):
            self.compiler.compile_one(defn)

    def test_duplicate_component_type_id_rejected(self) -> None:
        defn = _actor("actor_a", components=[_comp(100), _comp(100)])
        with pytest.raises(BlueprintCompilationError, match="Duplicate"):
            self.compiler.compile_one(defn)

    def test_invalid_control_type_rejected(self) -> None:
        defn = _actor("actor_a", control_type="ROBOT")
        with pytest.raises(BlueprintCompilationError, match="ROBOT"):
            self.compiler.compile_one(defn)

    # ── compile_all — batch ───────────────────────────────────────────────────

    def test_compile_all_returns_registry(self) -> None:
        defs = [
            _actor("actor_a"),
            _actor("actor_b", actor_type="PLAYER", control_type="HUMAN"),
        ]
        registry = self.compiler.compile_all(defs)
        assert len(registry) == 2
        assert registry.contains("actor_a")
        assert registry.contains("actor_b")

    def test_compile_all_collects_all_errors(self) -> None:
        defs = [
            _actor(""),               # error: empty id
            _actor("actor_a", actor_type="LASER_CANNON"),   # error: unknown type
            _actor("actor_b"),        # valid
        ]
        with pytest.raises(BlueprintCompilationError) as exc_info:
            self.compiler.compile_all(defs)
        # Both errors collected, not just the first
        assert len(exc_info.value.errors) >= 2

    def test_compile_all_duplicate_id_raises_registry_error(self) -> None:
        defs = [_actor("actor_a"), _actor("actor_a")]
        with pytest.raises(BlueprintCompilationError):
            self.compiler.compile_all(defs)

    def test_compile_all_empty_input_returns_empty_registry(self) -> None:
        registry = self.compiler.compile_all([])
        assert len(registry) == 0

    # ── UCL component ref validation ──────────────────────────────────────────

    def test_ucl_component_accepted_when_registered(self) -> None:
        # type_id=1 is registered in StubRegistry (COMP_IDENTITY_V1)
        defn = _actor("actor_a", components=[_comp(1, {"entity_name": "Player"})])
        bp = self.compiler.compile_one(defn)
        assert bp.has_component(1)

    def test_registry_with_no_field_enforcement_accepts_any_field(self) -> None:
        # A registry that returns empty field_names allows any field
        permissive = StubRegistry(registered={500: set()})
        compiler   = BlueprintCompiler(permissive)
        defn       = _actor("actor_a", components=[_comp(500, {"any_field": True})])
        bp         = compiler.compile_one(defn)
        assert bp.has_component(500)