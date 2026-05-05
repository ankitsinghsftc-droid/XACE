"""
test_asset_validation.py — Validation tests for the XACE Asset Registry (Audit 2).

Covers:
  - AssetNamingPolicy: generate, is_valid, parse, describe, normalisation
  - AssetType/AssetStatus enums: classification properties, from_string
  - AssetReference: construction, validation, transitions, serialization
  - AssetValidator: all four checks per asset_id, validate_no_unresolved (I12),
    validate_manifest, validate_reference
  - AssetValidationReport: blocks_commit, error/warning counts, summary
  - GameConfigLoader: valid config, required fields, domain validation,
    unknown engine, collect-all-errors behaviour
  - AnimationContract: sub-struct roundtrips, full contract serialization
  - AnimationContractGenerator: generate, cache hit/miss, invalidation,
    layer/parameter/event/IK extraction
  - I12 Invariant: UNRESOLVED always blocks commit, PLACEHOLDER never does
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_type_enum import AssetType
from asset_status_enum import AssetStatus
from asset_reference import AssetReference
from asset_naming_policy import AssetNamingPolicy
from asset_manifest import AssetManifest
from asset_validator import AssetValidator, AssetValidationReport
from game_config_loader import GameConfigLoader, GameConfigError, KNOWN_DCL_DOMAINS
from animation_contract import (
    AnimationContract,
    AnimationParameterType,
    BlendType,
    ContractAnimationEvent,
    ContractBlendTree,
    ContractIKConfig,
    ContractLayer,
    ContractParameter,
)
from animation_contract_generator import AnimationContractGenerator


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_placeholder(asset_id: str, asset_type: AssetType) -> AssetReference:
    return AssetReference.make_placeholder(asset_id, asset_type)

def make_linked(asset_id: str, asset_type: AssetType, path: str = "/a.fbx") -> AssetReference:
    ref = make_placeholder(asset_id, asset_type)
    ref.link(path)
    return ref

def make_unresolved(asset_id: str, asset_type: AssetType) -> AssetReference:
    return AssetReference.make_unresolved(asset_id, asset_type)

def manifest_with(*refs) -> AssetManifest:
    m = AssetManifest()
    for ref in refs:
        m.register(ref)
    return m


# =============================================================================
# AssetType Enum Tests
# =============================================================================

class TestAssetTypeEnum(unittest.TestCase):

    def test_all_ten_types_exist(self):
        self.assertEqual(len(AssetType.all_types()), 10)

    def test_from_string_valid(self):
        self.assertEqual(AssetType.from_string("MESH"), AssetType.MESH)
        self.assertEqual(AssetType.from_string("mesh"), AssetType.MESH)  # case-insensitive

    def test_from_string_invalid_raises(self):
        with self.assertRaises(ValueError):
            AssetType.from_string("INVALID_TYPE")

    def test_is_audio_correct(self):
        self.assertTrue(AssetType.AUDIO_CLIP.is_audio)
        self.assertTrue(AssetType.AUDIO_MUSIC.is_audio)
        self.assertFalse(AssetType.MESH.is_audio)

    def test_is_visual_correct(self):
        self.assertTrue(AssetType.MESH.is_visual)
        self.assertTrue(AssetType.TEXTURE.is_visual)
        self.assertTrue(AssetType.MATERIAL.is_visual)
        self.assertFalse(AssetType.AUDIO_CLIP.is_visual)
        self.assertFalse(AssetType.FONT.is_visual)

    def test_is_animation_related(self):
        self.assertTrue(AssetType.ANIMATION_CONTROLLER.is_animation_related)
        self.assertFalse(AssetType.MESH.is_animation_related)

    def test_placeholder_description_non_empty(self):
        for asset_type in AssetType:
            self.assertGreater(len(asset_type.placeholder_description), 0)

    def test_str_enum_serializes_to_value(self):
        # str, Enum means value is used in JSON dumps
        data = {"type": AssetType.MESH}
        json_str = json.dumps(data)
        self.assertIn("MESH", json_str)


# =============================================================================
# AssetStatus Enum Tests
# =============================================================================

class TestAssetStatusEnum(unittest.TestCase):

    def test_only_unresolved_blocks_commit(self):
        self.assertTrue(AssetStatus.UNRESOLVED.blocks_cgs_commit)
        self.assertFalse(AssetStatus.PLACEHOLDER.blocks_cgs_commit)
        self.assertFalse(AssetStatus.LINKED.blocks_cgs_commit)
        self.assertFalse(AssetStatus.MISSING.blocks_cgs_commit)

    def test_only_linked_is_renderable(self):
        self.assertTrue(AssetStatus.LINKED.is_renderable)
        self.assertFalse(AssetStatus.PLACEHOLDER.is_renderable)
        self.assertFalse(AssetStatus.MISSING.is_renderable)
        self.assertFalse(AssetStatus.UNRESOLVED.is_renderable)

    def test_unresolved_is_error_state(self):
        self.assertTrue(AssetStatus.UNRESOLVED.is_error_state)
        self.assertFalse(AssetStatus.MISSING.is_error_state)

    def test_missing_is_warning_state(self):
        self.assertTrue(AssetStatus.MISSING.is_warning_state)
        self.assertFalse(AssetStatus.PLACEHOLDER.is_warning_state)

    def test_from_string_valid(self):
        self.assertEqual(AssetStatus.from_string("LINKED"), AssetStatus.LINKED)
        self.assertEqual(AssetStatus.from_string("placeholder"), AssetStatus.PLACEHOLDER)

    def test_from_string_invalid_raises(self):
        with self.assertRaises(ValueError):
            AssetStatus.from_string("UNKNOWN_STATUS")

    def test_healthy_states(self):
        healthy = AssetStatus.healthy_states()
        self.assertIn(AssetStatus.PLACEHOLDER, healthy)
        self.assertIn(AssetStatus.LINKED, healthy)
        self.assertNotIn(AssetStatus.MISSING, healthy)
        self.assertNotIn(AssetStatus.UNRESOLVED, healthy)

    def test_problem_states(self):
        problems = AssetStatus.problem_states()
        self.assertIn(AssetStatus.MISSING, problems)
        self.assertIn(AssetStatus.UNRESOLVED, problems)


# =============================================================================
# AssetReference Tests
# =============================================================================

class TestAssetReference(unittest.TestCase):

    def test_placeholder_construction(self):
        ref = AssetReference.make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        self.assertEqual(ref.status, AssetStatus.PLACEHOLDER)
        self.assertIsNone(ref.resolved_path)
        self.assertTrue(ref.is_placeholder)
        self.assertFalse(ref.is_linked)

    def test_unresolved_construction(self):
        ref = AssetReference.make_unresolved("character_knight_mesh_v1", AssetType.MESH)
        self.assertEqual(ref.status, AssetStatus.UNRESOLVED)
        self.assertTrue(ref.is_unresolved)
        self.assertTrue(ref.blocks_cgs_commit)

    def test_link_transitions_to_linked(self):
        ref = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        ref.link("/knight.fbx")
        self.assertTrue(ref.is_linked)
        self.assertEqual(ref.resolved_path, "/knight.fbx")
        self.assertTrue(ref.is_renderable)

    def test_link_with_empty_path_raises(self):
        ref = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        with self.assertRaises(ValueError):
            ref.link("")

    def test_link_unresolved_raises(self):
        ref = make_unresolved("character_knight_mesh_v1", AssetType.MESH)
        with self.assertRaises(ValueError):
            ref.link("/knight.fbx")

    def test_mark_missing(self):
        ref = make_linked("character_knight_mesh_v1", AssetType.MESH, "/knight.fbx")
        ref.mark_missing()
        self.assertTrue(ref.is_missing)
        self.assertIsNone(ref.resolved_path)

    def test_mark_missing_non_linked_raises(self):
        ref = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        with self.assertRaises(ValueError):
            ref.mark_missing()

    def test_revert_to_placeholder(self):
        ref = make_linked("character_knight_mesh_v1", AssetType.MESH, "/knight.fbx")
        ref.revert_to_placeholder()
        self.assertTrue(ref.is_placeholder)
        self.assertIsNone(ref.resolved_path)

    def test_linked_without_path_raises_at_construction(self):
        with self.assertRaises(ValueError):
            AssetReference(
                asset_id="character_knight_mesh_v1",
                asset_type=AssetType.MESH,
                status=AssetStatus.LINKED,
                resolved_path=None,
            )

    def test_non_linked_with_path_raises_at_construction(self):
        with self.assertRaises(ValueError):
            AssetReference(
                asset_id="character_knight_mesh_v1",
                asset_type=AssetType.MESH,
                status=AssetStatus.PLACEHOLDER,
                resolved_path="/some/path.fbx",
            )

    def test_empty_asset_id_raises(self):
        with self.assertRaises(ValueError):
            AssetReference.make_placeholder("", AssetType.MESH)

    def test_serialization_roundtrip_placeholder(self):
        ref = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        data = ref.to_dict()
        restored = AssetReference.from_dict(data)
        self.assertEqual(restored.asset_id, ref.asset_id)
        self.assertEqual(restored.status, ref.status)
        self.assertEqual(restored.asset_type, ref.asset_type)

    def test_serialization_roundtrip_linked(self):
        ref = make_linked("character_knight_mesh_v1", AssetType.MESH, "/knight.fbx")
        restored = AssetReference.from_dict(ref.to_dict())
        self.assertEqual(restored.status, AssetStatus.LINKED)
        self.assertEqual(restored.resolved_path, "/knight.fbx")

    def test_equality_by_asset_id(self):
        ref1 = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        ref2 = make_linked("character_knight_mesh_v1", AssetType.MESH, "/a.fbx")
        self.assertEqual(ref1, ref2)  # Same asset_id

    def test_inequality_different_id(self):
        ref1 = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        ref2 = make_placeholder("enemy_dragon_mesh_v1", AssetType.MESH)
        self.assertNotEqual(ref1, ref2)

    def test_hashable(self):
        ref = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        s = {ref}
        self.assertEqual(len(s), 1)


# =============================================================================
# AssetNamingPolicy Tests
# =============================================================================

class TestAssetNamingPolicy(unittest.TestCase):

    def test_generate_basic(self):
        asset_id = AssetNamingPolicy.generate("character", "knight", AssetType.MESH)
        self.assertEqual(asset_id, "character_knight_mesh_v1")

    def test_generate_with_version(self):
        asset_id = AssetNamingPolicy.generate("enemy", "dragon", AssetType.AUDIO_CLIP, version=3)
        self.assertEqual(asset_id, "enemy_dragon_sfx_v3")

    def test_generate_all_asset_types(self):
        for asset_type in AssetType:
            asset_id = AssetNamingPolicy.generate("prop", "crate", asset_type)
            self.assertTrue(AssetNamingPolicy.is_valid(asset_id),
                            f"Generated ID for {asset_type} is invalid: {asset_id}")

    def test_generate_normalises_spaces(self):
        asset_id = AssetNamingPolicy.generate("character", "my knight", AssetType.MESH)
        self.assertNotIn(" ", asset_id)

    def test_generate_normalises_hyphens(self):
        asset_id = AssetNamingPolicy.generate("character", "knight-hero", AssetType.MESH)
        self.assertNotIn("-", asset_id)

    def test_generate_empty_type_raises(self):
        with self.assertRaises(ValueError):
            AssetNamingPolicy.generate("", "knight", AssetType.MESH)

    def test_generate_empty_name_raises(self):
        with self.assertRaises(ValueError):
            AssetNamingPolicy.generate("character", "", AssetType.MESH)

    def test_generate_version_zero_raises(self):
        with self.assertRaises(ValueError):
            AssetNamingPolicy.generate("character", "knight", AssetType.MESH, version=0)

    def test_is_valid_canonical_ids(self):
        valid_ids = [
            "character_knight_mesh_v1",
            "enemy_dragon_sfx_v3",
            "prop_wooden_crate_prefab_v2",
            "ui_main_menu_font_v1",
        ]
        for asset_id in valid_ids:
            self.assertTrue(AssetNamingPolicy.is_valid(asset_id), f"Should be valid: {asset_id}")

    def test_is_valid_rejects_invalid(self):
        invalid_ids = [
            "",
            "mesh_v1",                      # missing entity_name
            "character_knight_v1",          # missing type suffix
            "character_knight_mesh",        # missing version
            "character_knight_mesh_v0",     # version 0 invalid
            "character knight mesh v1",     # spaces
            "CHARACTER_KNIGHT_MESH_V1",     # uppercase
        ]
        for asset_id in invalid_ids:
            self.assertFalse(AssetNamingPolicy.is_valid(asset_id),
                             f"Should be invalid: {asset_id}")

    def test_parse_roundtrip(self):
        original = "character_knight_mesh_v1"
        parsed = AssetNamingPolicy.parse(original)
        self.assertIsNotNone(parsed)
        entity_type, entity_name, asset_type, version = parsed
        self.assertEqual(entity_type, "character")
        self.assertEqual(entity_name, "knight")
        self.assertEqual(asset_type, AssetType.MESH)
        self.assertEqual(version, 1)

    def test_parse_compound_entity_name(self):
        asset_id = AssetNamingPolicy.generate("prop", "wooden_crate", AssetType.PREFAB, 2)
        parsed = AssetNamingPolicy.parse(asset_id)
        self.assertIsNotNone(parsed)
        _, entity_name, asset_type, version = parsed
        self.assertEqual(entity_name, "wooden_crate")
        self.assertEqual(asset_type, AssetType.PREFAB)
        self.assertEqual(version, 2)

    def test_parse_invalid_returns_none(self):
        self.assertIsNone(AssetNamingPolicy.parse("not_a_valid_id"))
        self.assertIsNone(AssetNamingPolicy.parse(""))

    def test_extract_asset_type(self):
        self.assertEqual(
            AssetNamingPolicy.extract_asset_type("character_knight_mesh_v1"),
            AssetType.MESH
        )
        self.assertEqual(
            AssetNamingPolicy.extract_asset_type("enemy_dragon_sfx_v3"),
            AssetType.AUDIO_CLIP
        )

    def test_extract_version(self):
        self.assertEqual(
            AssetNamingPolicy.extract_version("character_knight_mesh_v5"),
            5
        )

    def test_generate_next_version(self):
        next_id = AssetNamingPolicy.generate_next_version(
            "character_knight_mesh_v1", AssetType.MESH
        )
        self.assertEqual(next_id, "character_knight_mesh_v2")

    def test_describe_human_readable(self):
        description = AssetNamingPolicy.describe("character_knight_mesh_v1")
        self.assertIn("Knight", description)
        self.assertIn("Character", description)
        self.assertIn("Mesh", description)
        self.assertIn("1", description)

    def test_describe_invalid_returns_raw(self):
        self.assertEqual(AssetNamingPolicy.describe("not_valid"), "not_valid")


# =============================================================================
# AssetValidator Tests
# =============================================================================

class TestAssetValidator(unittest.TestCase):

    def test_valid_linked_asset_passes(self):
        m = manifest_with(make_linked("character_knight_mesh_v1", AssetType.MESH, "/a.fbx"))
        v = AssetValidator(m)
        report = v.validate_asset_id("character_knight_mesh_v1")
        self.assertFalse(report.blocks_commit)
        self.assertTrue(report.is_clean)

    def test_valid_placeholder_gives_warning_not_error(self):
        m = manifest_with(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        v = AssetValidator(m)
        report = v.validate_asset_id("character_knight_mesh_v1")
        self.assertFalse(report.blocks_commit)
        self.assertEqual(report.warning_count(), 1)
        self.assertEqual(report.error_count(), 0)

    def test_unregistered_asset_id_is_unresolved_error(self):
        m = AssetManifest()  # empty
        v = AssetValidator(m)
        report = v.validate_asset_id("character_knight_mesh_v1")
        self.assertTrue(report.blocks_commit)
        self.assertEqual(report.error_count(), 1)
        self.assertEqual(report.errors[0].code, "UNRESOLVED_REF")

    def test_unresolved_status_in_manifest_is_error(self):
        m = manifest_with(make_unresolved("character_knight_mesh_v1", AssetType.MESH))
        v = AssetValidator(m)
        report = v.validate_asset_id("character_knight_mesh_v1")
        self.assertTrue(report.blocks_commit)
        self.assertEqual(report.errors[0].code, "UNRESOLVED_REF")

    def test_missing_asset_gives_warning_not_error(self):
        ref = make_linked("character_knight_mesh_v1", AssetType.MESH, "/a.fbx")
        m = manifest_with(ref)
        m.mark_missing("character_knight_mesh_v1")
        v = AssetValidator(m)
        report = v.validate_asset_id("character_knight_mesh_v1")
        self.assertFalse(report.blocks_commit)
        self.assertEqual(report.warning_count(), 1)
        self.assertEqual(report.warnings[0].code, "MISSING_ASSET")

    def test_malformed_asset_id_is_error(self):
        m = AssetManifest()
        v = AssetValidator(m)
        report = v.validate_asset_id("NOT_A_VALID_ID")
        self.assertTrue(report.blocks_commit)
        self.assertEqual(report.errors[0].code, "MALFORMED_ASSET_ID")

    def test_type_mismatch_is_error(self):
        m = manifest_with(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        v = AssetValidator(m)
        # Expect AUDIO_CLIP but manifest has MESH
        report = v.validate_asset_id(
            "character_knight_mesh_v1",
            expected_type=AssetType.AUDIO_CLIP,
        )
        self.assertTrue(report.blocks_commit)
        self.assertEqual(report.errors[0].code, "ASSET_TYPE_MISMATCH")

    def test_type_match_no_type_error(self):
        m = manifest_with(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        v = AssetValidator(m)
        report = v.validate_asset_id(
            "character_knight_mesh_v1",
            expected_type=AssetType.MESH,
        )
        # Should get warning (placeholder) but not type mismatch error
        type_errors = [i for i in report.errors if i.code == "ASSET_TYPE_MISMATCH"]
        self.assertEqual(len(type_errors), 0)

    def test_validate_no_unresolved_clean(self):
        m = manifest_with(
            make_placeholder("character_knight_mesh_v1", AssetType.MESH),
            make_linked("character_knight_anim_v1", AssetType.ANIMATION_CONTROLLER, "/a"),
        )
        v = AssetValidator(m)
        report = v.validate_no_unresolved()
        self.assertFalse(report.blocks_commit)

    def test_validate_no_unresolved_blocked(self):
        m = manifest_with(
            make_placeholder("character_knight_mesh_v1", AssetType.MESH),
            make_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB),
        )
        v = AssetValidator(m)
        report = v.validate_no_unresolved()
        self.assertTrue(report.blocks_commit)
        self.assertEqual(report.error_count(), 1)

    def test_validate_asset_id_list(self):
        m = manifest_with(
            make_placeholder("character_knight_mesh_v1", AssetType.MESH),
            make_linked("character_knight_anim_v1", AssetType.ANIMATION_CONTROLLER, "/a"),
            make_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB),
        )
        v = AssetValidator(m)
        report = v.validate_asset_id_list([
            "character_knight_mesh_v1",
            "character_knight_anim_v1",
            "prop_barrel_prefab_v1",
        ])
        self.assertEqual(report.asset_ids_checked, 3)
        self.assertTrue(report.blocks_commit)

    def test_validate_manifest_full_scan(self):
        m = manifest_with(
            make_placeholder("character_knight_mesh_v1", AssetType.MESH),
            make_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB),
        )
        v = AssetValidator(m)
        report = v.validate_manifest()
        self.assertEqual(report.asset_ids_checked, 2)
        self.assertTrue(report.blocks_commit)

    def test_i12_invariant_placeholder_never_blocks(self):
        """I12: Only UNRESOLVED blocks commit. PLACEHOLDER must never block."""
        m = AssetManifest()
        for i in range(10):
            m.register(make_placeholder(f"character_unit{i}_mesh_v1", AssetType.MESH))
        v = AssetValidator(m)
        report = v.validate_no_unresolved()
        self.assertFalse(
            report.blocks_commit,
            "PLACEHOLDER refs must NEVER block CGS commit (I12 — only UNRESOLVED blocks)"
        )

    def test_i12_invariant_unresolved_always_blocks(self):
        """I12: UNRESOLVED must always block CGS commit, no exceptions."""
        m = manifest_with(make_unresolved("character_knight_mesh_v1", AssetType.MESH))
        v = AssetValidator(m)
        report = v.validate_no_unresolved()
        self.assertTrue(
            report.blocks_commit,
            "UNRESOLVED refs must ALWAYS block CGS commit (I12)"
        )


# =============================================================================
# AssetValidationReport Tests
# =============================================================================

class TestAssetValidationReport(unittest.TestCase):

    def test_empty_report_is_clean(self):
        report = AssetValidationReport()
        self.assertTrue(report.is_clean)
        self.assertFalse(report.blocks_commit)

    def test_report_summary_clean(self):
        report = AssetValidationReport(asset_ids_checked=5)
        summary = report.summary()
        self.assertIn("passed", summary)
        self.assertIn("5", summary)

    def test_report_summary_with_issues(self):
        from asset_validator import AssetValidationIssue
        report = AssetValidationReport(asset_ids_checked=3)
        report.add_issue(AssetValidationIssue(
            asset_id="character_knight_mesh_v1",
            severity="error",
            code="UNRESOLVED_REF",
            message="test",
        ))
        summary = report.summary()
        self.assertIn("error", summary)

    def test_to_dict_structure(self):
        report = AssetValidationReport(asset_ids_checked=2)
        data = report.to_dict()
        self.assertIn("blocks_commit", data)
        self.assertIn("asset_ids_checked", data)
        self.assertIn("error_count", data)
        self.assertIn("warning_count", data)
        self.assertIn("issues", data)


# =============================================================================
# GameConfigLoader Tests
# =============================================================================

class TestGameConfigLoader(unittest.TestCase):

    def _loader(self):
        return GameConfigLoader()

    def _valid_config(self) -> dict:
        return {
            "world_id": "my_game_session",
            "game_name": "My XACE Game",
            "schema_version": "0.1.0",
            "domains": ["combat", "character", "world"],
            "engine_target": "unity",
            "asset_registry": {
                "auto_register": True,
                "placeholder_threshold_hours": 24.0,
            },
            "gcl_path": "gcl",
        }

    def test_valid_config_loads(self):
        loader = self._loader()
        config = loader.load_from_dict(self._valid_config())
        self.assertEqual(config.world_id, "my_game_session")
        self.assertEqual(config.game_name, "My XACE Game")
        self.assertEqual(config.schema_version, "0.1.0")
        self.assertEqual(len(config.domains), 3)
        self.assertEqual(config.engine_target, "unity")

    def test_domains_loaded_correctly(self):
        loader = self._loader()
        config = loader.load_from_dict(self._valid_config())
        self.assertIn("combat", config.domains)
        self.assertIn("character", config.domains)
        self.assertIn("world", config.domains)
        self.assertTrue(config.has_combat)
        self.assertFalse(config.has_rpg)

    def test_missing_world_id_raises(self):
        loader = self._loader()
        data = self._valid_config()
        del data["world_id"]
        with self.assertRaises(GameConfigError) as ctx:
            loader.load_from_dict(data)
        self.assertIn("world_id", str(ctx.exception))

    def test_missing_game_name_raises(self):
        loader = self._loader()
        data = self._valid_config()
        del data["game_name"]
        with self.assertRaises(GameConfigError):
            loader.load_from_dict(data)

    def test_unknown_domain_raises(self):
        loader = self._loader()
        data = self._valid_config()
        data["domains"] = ["combat", "nonexistent_domain"]
        with self.assertRaises(GameConfigError) as ctx:
            loader.load_from_dict(data)
        self.assertIn("nonexistent_domain", str(ctx.exception))

    def test_unknown_engine_target_raises(self):
        loader = self._loader()
        data = self._valid_config()
        data["engine_target"] = "unknown_engine"
        with self.assertRaises(GameConfigError) as ctx:
            loader.load_from_dict(data)
        self.assertIn("engine_target", str(ctx.exception).lower() + "unknown_engine")

    def test_collects_all_errors_before_raising(self):
        """Validation must collect all errors, not fail-fast on first."""
        loader = self._loader()
        data = {
            # missing world_id AND game_name AND bad domain
            "schema_version": "0.1.0",
            "domains": ["invalid_domain"],
            "engine_target": "unity",
        }
        with self.assertRaises(GameConfigError) as ctx:
            loader.load_from_dict(data)
        error_text = str(ctx.exception)
        # Should mention both missing fields
        self.assertIn("world_id", error_text)
        self.assertIn("game_name", error_text)

    def test_all_known_domains_valid(self):
        loader = self._loader()
        errors = loader.validate_domains(list(KNOWN_DCL_DOMAINS))
        self.assertEqual(errors, [])

    def test_empty_domains_list_is_valid(self):
        loader = self._loader()
        data = self._valid_config()
        data["domains"] = []
        config = loader.load_from_dict(data)
        self.assertEqual(config.domains, [])

    def test_asset_registry_config_defaults(self):
        loader = self._loader()
        data = self._valid_config()
        del data["asset_registry"]
        config = loader.load_from_dict(data)
        self.assertTrue(config.asset_registry.auto_register)

    def test_has_domain_method(self):
        loader = self._loader()
        config = loader.load_from_dict(self._valid_config())
        self.assertTrue(config.has_domain("combat"))
        self.assertFalse(config.has_domain("rpg"))

    def test_to_dict_serialization(self):
        loader = self._loader()
        config = loader.load_from_dict(self._valid_config())
        data = config.to_dict()
        self.assertIn("world_id", data)
        self.assertIn("domains", data)
        self.assertIn("engine_target", data)
        self.assertEqual(data["domains"], sorted(config.domains))  # D11


# =============================================================================
# AnimationContract Tests
# =============================================================================

class TestAnimationContract(unittest.TestCase):

    def _make_contract(self) -> AnimationContract:
        return AnimationContract(
            actor_id="character_knight",
            controller_asset_id="character_knight_anim_v1",
            contract_version=1,
            schema_version="0.1.0",
            layers=[
                ContractLayer(
                    layer_name="base",
                    default_state="Idle",
                    required_states=["Idle", "Run", "Attack"],
                )
            ],
            parameters=[
                ContractParameter("speed", AnimationParameterType.FLOAT, default_value=0.0),
                ContractParameter("is_attacking", AnimationParameterType.BOOL, default_value=False),
                ContractParameter("jump", AnimationParameterType.TRIGGER),
            ],
            blend_trees=[
                ContractBlendTree("locomotion", "speed_x", "speed_y", BlendType.SIMPLE_DIRECTIONAL)
            ],
            animation_events=[
                ContractAnimationEvent("sword_hit", "Attack", "base", 0.5, "combat.hit_landed")
            ],
            ik_config=ContractIKConfig(
                ik_mode="HANDS",
                has_right_hand=True,
                solve_order="FABRIK",
            ),
        )

    def test_contract_construction(self):
        c = self._make_contract()
        self.assertEqual(c.actor_id, "character_knight")
        self.assertEqual(len(c.layers), 1)
        self.assertEqual(len(c.parameters), 3)
        self.assertEqual(len(c.blend_trees), 1)
        self.assertEqual(c.event_count(), 1)
        self.assertTrue(c.has_ik())

    def test_layer_names(self):
        c = self._make_contract()
        self.assertIn("base", c.layer_names)

    def test_parameter_names_sorted(self):
        c = self._make_contract()
        names = c.parameter_names
        self.assertEqual(names, sorted(names))  # D11

    def test_get_layer(self):
        c = self._make_contract()
        layer = c.get_layer("base")
        self.assertIsNotNone(layer)
        self.assertEqual(layer.default_state, "Idle")

    def test_get_layer_missing_returns_none(self):
        c = self._make_contract()
        self.assertIsNone(c.get_layer("nonexistent"))

    def test_get_parameter(self):
        c = self._make_contract()
        param = c.get_parameter("speed")
        self.assertIsNotNone(param)
        self.assertEqual(param.param_type, AnimationParameterType.FLOAT)

    def test_serialization_roundtrip(self):
        c = self._make_contract()
        json_str = c.to_json()
        restored = AnimationContract.from_json(json_str)
        self.assertEqual(restored.actor_id, c.actor_id)
        self.assertEqual(restored.contract_version, c.contract_version)
        self.assertEqual(len(restored.layers), len(c.layers))
        self.assertEqual(len(restored.parameters), len(c.parameters))
        self.assertEqual(len(restored.blend_trees), len(c.blend_trees))
        self.assertEqual(len(restored.animation_events), len(c.animation_events))
        self.assertTrue(restored.has_ik())
        self.assertEqual(restored.ik_config.ik_mode, "HANDS")

    def test_contract_layer_roundtrip(self):
        layer = ContractLayer("base", "Idle", ["Idle", "Run"], weight=0.5, additive=False)
        restored = ContractLayer.from_dict(layer.to_dict())
        self.assertEqual(restored.layer_name, "base")
        self.assertEqual(restored.default_state, "Idle")
        self.assertAlmostEqual(restored.weight, 0.5)

    def test_contract_parameter_roundtrip(self):
        param = ContractParameter("speed", AnimationParameterType.FLOAT, 1.5)
        restored = ContractParameter.from_dict(param.to_dict())
        self.assertEqual(restored.name, "speed")
        self.assertEqual(restored.param_type, AnimationParameterType.FLOAT)
        self.assertAlmostEqual(restored.default_value, 1.5)

    def test_contract_event_roundtrip(self):
        evt = ContractAnimationEvent("hit", "Attack", "base", 0.5, "combat.hit")
        restored = ContractAnimationEvent.from_dict(evt.to_dict())
        self.assertEqual(restored.event_id, "hit")
        self.assertAlmostEqual(restored.trigger_at_normalized_time, 0.5)

    def test_ik_config_roundtrip(self):
        ik = ContractIKConfig("FULL_BODY", has_foot_placement=True, solve_order="FABRIK")
        restored = ContractIKConfig.from_dict(ik.to_dict())
        self.assertEqual(restored.ik_mode, "FULL_BODY")
        self.assertTrue(restored.has_foot_placement)


# =============================================================================
# AnimationContractGenerator Tests
# =============================================================================

class TestAnimationContractGenerator(unittest.TestCase):

    def _make_anim_data(self) -> dict:
        """Sample COMP_ANIMATION_V2 data dict."""
        return {
            "controller_ref": "character_knight_anim_v1",
            "playback_speed": 1.0,
            "layers": {
                "base": {"current_state": "Idle", "weight": 1.0, "additive": False},
                "upper": {"current_state": "Idle", "weight": 0.5, "additive": True},
            },
            "parameters": {
                "speed":       {"value": 0.0, "type": "FLOAT"},
                "is_jumping":  {"value": False, "type": "BOOL"},
                "jump_trigger": {"value": None, "type": "TRIGGER"},
            },
            "blend_parameters": {
                "locomotion": {
                    "x_parameter": "speed_x",
                    "y_parameter": "speed_y",
                    "blend_type": "SIMPLE_DIRECTIONAL",
                }
            },
            "pending_events": [
                {
                    "event_id": "footstep",
                    "state_name": "Run",
                    "trigger_at_normalized_time": 0.3,
                    "game_event_type": "audio.footstep",
                    "is_consumed": False,
                },
                {
                    "event_id": "already_consumed",
                    "state_name": "Run",
                    "trigger_at_normalized_time": 0.7,
                    "game_event_type": "audio.footstep",
                    "is_consumed": True,   # should be skipped
                },
            ],
            "ik_enabled": False,
        }

    def _make_ik_data(self) -> dict:
        """Sample COMP_IK_V1 data dict."""
        return {
            "ik_mode": "HANDS",
            "right_hand_target_entity": 42,
            "right_hand_weight": 1.0,
            "foot_placement_enabled": True,
            "solve_order": "FABRIK",
        }

    def test_generate_returns_contract(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        self.assertIsNotNone(contract)
        self.assertEqual(contract.actor_id, "character_knight")

    def test_generate_no_animation_component_returns_none(self):
        gen = AnimationContractGenerator("0.1.0")
        # No COMP_ANIMATION_V2 (type_id 121)
        components = {1: {"position": {"x": 0}}}
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        self.assertIsNone(contract)

    def test_layers_extracted_correctly(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        self.assertEqual(len(contract.layers), 2)
        layer_names = [l.layer_name for l in contract.layers]
        self.assertEqual(layer_names, sorted(layer_names))  # D11

    def test_parameters_extracted_correctly(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        self.assertEqual(len(contract.parameters), 3)
        param_names = [p.name for p in contract.parameters]
        self.assertEqual(param_names, sorted(param_names))  # D11
        speed_param = contract.get_parameter("speed")
        self.assertEqual(speed_param.param_type, AnimationParameterType.FLOAT)

    def test_blend_trees_extracted(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        self.assertEqual(len(contract.blend_trees), 1)
        self.assertEqual(contract.blend_trees[0].tree_name, "locomotion")

    def test_consumed_events_excluded(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        # Only non-consumed events should be extracted (1 of 2)
        self.assertEqual(contract.event_count(), 1)
        self.assertEqual(contract.animation_events[0].event_id, "footstep")

    def test_ik_config_extracted_when_present(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data(), 122: self._make_ik_data()}
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        self.assertTrue(contract.has_ik())
        self.assertEqual(contract.ik_config.ik_mode, "HANDS")
        self.assertTrue(contract.ik_config.has_foot_placement)

    def test_no_ik_component_means_no_ik_in_contract(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}  # no IK
        contract = gen.generate("character_knight", "character_knight_anim_v1", components)
        self.assertFalse(contract.has_ik())

    def test_cache_hit_on_second_call(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        c1 = gen.generate("character_knight", "character_knight_anim_v1", components)
        c2 = gen.generate("character_knight", "character_knight_anim_v1", components)
        # Same object from cache
        self.assertEqual(gen.generation_count(), 1)  # only generated once
        self.assertEqual(c1.contract_version, c2.contract_version)

    def test_force_regenerate_bypasses_cache(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        gen.generate("character_knight", "character_knight_anim_v1", components)
        gen.generate("character_knight", "character_knight_anim_v1", components,
                     force_regenerate=True)
        self.assertEqual(gen.generation_count(), 2)

    def test_version_increments_on_force_regenerate(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        c1 = gen.generate("character_knight", "character_knight_anim_v1", components)
        c2 = gen.generate("character_knight", "character_knight_anim_v1", components,
                          force_regenerate=True)
        self.assertEqual(c2.contract_version, c1.contract_version + 1)

    def test_invalidate_cache_clears_entry(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        gen.generate("character_knight", "character_knight_anim_v1", components)
        gen.invalidate_cache("character_knight")
        self.assertNotIn("character_knight", gen.cached_actor_ids())

    def test_invalidate_all_clears_all(self):
        gen = AnimationContractGenerator("0.1.0")
        components = {121: self._make_anim_data()}
        gen.generate("character_knight", "character_knight_anim_v1", components)
        gen.generate("enemy_dragon", "enemy_dragon_anim_v1", components)
        gen.invalidate_all()
        self.assertEqual(gen.cached_actor_ids(), [])

    def test_generate_from_component_json_direct(self):
        gen = AnimationContractGenerator("0.1.0")
        anim_data = self._make_anim_data()
        contract = gen.generate_from_component_json(
            "character_knight", "character_knight_anim_v1", anim_data
        )
        self.assertIsNotNone(contract)
        self.assertEqual(contract.actor_id, "character_knight")

    def test_invalid_parameter_type_raises(self):
        gen = AnimationContractGenerator("0.1.0")
        anim_data = self._make_anim_data()
        anim_data["parameters"]["bad"] = {"value": 0, "type": "INVALID_TYPE"}
        with self.assertRaises(ValueError):
            gen.generate_from_component_json(
                "character_knight", "character_knight_anim_v1", anim_data
            )

    def test_event_out_of_range_time_raises(self):
        gen = AnimationContractGenerator("0.1.0")
        anim_data = self._make_anim_data()
        anim_data["pending_events"].append({
            "event_id": "bad_event",
            "state_name": "Run",
            "trigger_at_normalized_time": 1.5,  # out of range
            "game_event_type": "test",
            "is_consumed": False,
        })
        with self.assertRaises(ValueError):
            gen.generate_from_component_json(
                "character_knight", "character_knight_anim_v1", anim_data
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)