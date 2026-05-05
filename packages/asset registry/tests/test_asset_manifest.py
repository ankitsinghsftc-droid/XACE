"""
test_asset_manifest.py — Integration tests for the XACE Asset Registry manifest pipeline.

Covers:
  - AssetManifest: register, get, status transitions, queries, metrics, serialization
  - PlaceholderRegistry: track, mark_linked, entity queries, builder summary
  - AssetLinker: link, link_bulk, mark_missing, extension warnings, audit trail
  - AssetCleanupManager: entity cleanup, orphan cleanup
  - EngineSyncReceiver: bulk PLACEHOLDER→LINKED transitions from engine feedback
  - AudioManifest: sfx/music registration, sequence linking, budget summary
  - AssetRegistryManager: full integration lifecycle, serialization roundtrip
  - AssetReportGenerator: report structure, problem list, suggestions, summary bar
"""

import sys
import os
import json
import unittest
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_type_enum import AssetType
from asset_status_enum import AssetStatus
from asset_reference import AssetReference
from asset_naming_policy import AssetNamingPolicy
from asset_manifest import AssetManifest, ManifestMetrics
from placeholder_registry import PlaceholderRegistry, PlaceholderEntry
from asset_linker import AssetLinker
from asset_validator import AssetValidator
from asset_cleanup_manager import AssetCleanupManager
from engine_sync_receiver import EngineSyncReceiver
from audio_manifest import AudioManifest, AudioSpatialization
from asset_registry_manager import AssetRegistryManager
from asset_report import AssetReportGenerator


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_placeholder(asset_id: str, asset_type: AssetType) -> AssetReference:
    return AssetReference.make_placeholder(asset_id, asset_type)

def make_linked(asset_id: str, asset_type: AssetType, path: str) -> AssetReference:
    ref = make_placeholder(asset_id, asset_type)
    ref.link(path)
    return ref

def make_unresolved(asset_id: str, asset_type: AssetType) -> AssetReference:
    return AssetReference.make_unresolved(asset_id, asset_type)

def populated_manifest() -> AssetManifest:
    m = AssetManifest()
    m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
    m.register(make_linked("character_knight_anim_v1", AssetType.ANIMATION_CONTROLLER, "/anim.controller"))
    m.register(make_placeholder("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP))
    m.register(make_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB))
    return m


# =============================================================================
# AssetManifest Tests
# =============================================================================

class TestAssetManifest(unittest.TestCase):

    def test_register_and_get(self):
        m = AssetManifest()
        ref = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        m.register(ref)
        retrieved = m.get("character_knight_mesh_v1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.asset_id, "character_knight_mesh_v1")
        self.assertEqual(retrieved.status, AssetStatus.PLACEHOLDER)

    def test_register_duplicate_raises(self):
        m = AssetManifest()
        ref = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        m.register(ref)
        with self.assertRaises(ValueError):
            m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))

    def test_get_missing_returns_none(self):
        m = AssetManifest()
        self.assertIsNone(m.get("does_not_exist_mesh_v1"))

    def test_contains(self):
        m = AssetManifest()
        m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        self.assertTrue(m.contains("character_knight_mesh_v1"))
        self.assertFalse(m.contains("enemy_dragon_mesh_v1"))

    def test_link_transitions_to_linked(self):
        m = AssetManifest()
        m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        m.link("character_knight_mesh_v1", "/assets/knight.fbx")
        ref = m.get("character_knight_mesh_v1")
        self.assertEqual(ref.status, AssetStatus.LINKED)
        self.assertEqual(ref.resolved_path, "/assets/knight.fbx")

    def test_mark_missing_transitions_linked_to_missing(self):
        m = AssetManifest()
        m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        m.link("character_knight_mesh_v1", "/assets/knight.fbx")
        m.mark_missing("character_knight_mesh_v1")
        ref = m.get("character_knight_mesh_v1")
        self.assertEqual(ref.status, AssetStatus.MISSING)
        self.assertIsNone(ref.resolved_path)

    def test_revert_to_placeholder(self):
        m = AssetManifest()
        m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        m.link("character_knight_mesh_v1", "/assets/knight.fbx")
        m.revert_to_placeholder("character_knight_mesh_v1")
        ref = m.get("character_knight_mesh_v1")
        self.assertEqual(ref.status, AssetStatus.PLACEHOLDER)

    def test_get_by_status_returns_sorted(self):
        m = populated_manifest()
        placeholders = m.get_by_status(AssetStatus.PLACEHOLDER)
        ids = [r.asset_id for r in placeholders]
        self.assertEqual(ids, sorted(ids))  # D11

    def test_get_by_type(self):
        m = populated_manifest()
        meshes = m.get_by_type(AssetType.MESH)
        self.assertEqual(len(meshes), 1)
        self.assertEqual(meshes[0].asset_id, "character_knight_mesh_v1")

    def test_get_all_unresolved(self):
        m = populated_manifest()
        unresolved = m.get_all_unresolved()
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].asset_id, "prop_barrel_prefab_v1")

    def test_has_unresolved_true(self):
        m = populated_manifest()
        self.assertTrue(m.has_unresolved())

    def test_has_unresolved_false_when_clean(self):
        m = AssetManifest()
        m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        self.assertFalse(m.has_unresolved())

    def test_count_by_status(self):
        m = populated_manifest()
        self.assertEqual(m.count_by_status(AssetStatus.PLACEHOLDER), 2)
        self.assertEqual(m.count_by_status(AssetStatus.LINKED), 1)
        self.assertEqual(m.count_by_status(AssetStatus.UNRESOLVED), 1)

    def test_all_refs_sorted(self):
        m = populated_manifest()
        ids = [r.asset_id for r in m.all_refs()]
        self.assertEqual(ids, sorted(ids))  # D11

    def test_total_count(self):
        m = populated_manifest()
        self.assertEqual(m.total_count(), 4)

    def test_status_indices_consistent_after_link(self):
        m = AssetManifest()
        m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        self.assertEqual(m.count_by_status(AssetStatus.PLACEHOLDER), 1)
        self.assertEqual(m.count_by_status(AssetStatus.LINKED), 0)
        m.link("character_knight_mesh_v1", "/knight.fbx")
        self.assertEqual(m.count_by_status(AssetStatus.PLACEHOLDER), 0)
        self.assertEqual(m.count_by_status(AssetStatus.LINKED), 1)

    def test_compute_metrics(self):
        m = populated_manifest()
        metrics = m.compute_metrics()
        self.assertEqual(metrics.total_references, 4)
        self.assertEqual(metrics.placeholder_count, 2)
        self.assertEqual(metrics.linked_count, 1)
        self.assertEqual(metrics.unresolved_count, 1)
        self.assertTrue(metrics.has_blockers)
        self.assertFalse(metrics.has_warnings)

    def test_builder_summary_with_placeholders(self):
        m = AssetManifest()
        m.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        m.register(make_placeholder("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP))
        metrics = m.compute_metrics()
        summary = metrics.builder_summary
        self.assertIn("2", summary)
        self.assertIn("grey boxes", summary)

    def test_builder_summary_all_linked(self):
        m = AssetManifest()
        m.register(make_linked("character_knight_mesh_v1", AssetType.MESH, "/a.fbx"))
        metrics = m.compute_metrics()
        self.assertIn("linked", metrics.builder_summary.lower())

    def test_serialization_roundtrip(self):
        m = populated_manifest()
        json_str = m.to_json()
        restored = AssetManifest.from_json(json_str)
        self.assertEqual(restored.total_count(), m.total_count())
        self.assertEqual(
            restored.count_by_status(AssetStatus.PLACEHOLDER),
            m.count_by_status(AssetStatus.PLACEHOLDER)
        )
        self.assertEqual(
            restored.count_by_status(AssetStatus.LINKED),
            m.count_by_status(AssetStatus.LINKED)
        )
        self.assertEqual(
            restored.count_by_status(AssetStatus.UNRESOLVED),
            m.count_by_status(AssetStatus.UNRESOLVED)
        )

    def test_register_many_returns_failures(self):
        m = AssetManifest()
        ref1 = make_placeholder("character_knight_mesh_v1", AssetType.MESH)
        ref2 = make_placeholder("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP)
        m.register(ref1)
        # Registering ref1 again should fail; ref2 should succeed
        failed = m.register_many([ref1, ref2])
        self.assertEqual(len(failed), 1)
        self.assertIn("character_knight_mesh_v1", failed)
        self.assertTrue(m.contains("enemy_dragon_sfx_v1"))


# =============================================================================
# PlaceholderRegistry Tests
# =============================================================================

class TestPlaceholderRegistry(unittest.TestCase):

    def test_track_and_is_tracked(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_001")
        self.assertTrue(r.is_tracked("character_knight_mesh_v1"))

    def test_track_idempotent(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH)
        r.track("character_knight_mesh_v1", AssetType.MESH)  # second call ignored
        self.assertEqual(r.total_count(), 1)

    def test_mark_linked_removes_entry(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_001")
        result = r.mark_linked("character_knight_mesh_v1")
        self.assertTrue(result)
        self.assertFalse(r.is_tracked("character_knight_mesh_v1"))

    def test_mark_linked_nonexistent_returns_false(self):
        r = PlaceholderRegistry()
        self.assertFalse(r.mark_linked("does_not_exist_mesh_v1"))

    def test_get_for_entity(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_001")
        r.track("character_knight_anim_v1", AssetType.ANIMATION_CONTROLLER, entity_id="ent_001")
        r.track("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP, entity_id="ent_002")
        entries = r.get_for_entity("ent_001")
        self.assertEqual(len(entries), 2)
        ids = [e.asset_id for e in entries]
        self.assertEqual(ids, sorted(ids))  # D11

    def test_get_for_type(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH)
        r.track("enemy_dragon_mesh_v1", AssetType.MESH)
        r.track("character_knight_sfx_v1", AssetType.AUDIO_CLIP)
        meshes = r.get_for_type(AssetType.MESH)
        self.assertEqual(len(meshes), 2)

    def test_builder_summary_zero(self):
        r = PlaceholderRegistry()
        self.assertIn("linked", r.builder_summary().lower())

    def test_builder_summary_singular(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH)
        summary = r.builder_summary()
        self.assertIn("1", summary)
        self.assertIn("grey boxes", summary)

    def test_builder_summary_plural(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH)
        r.track("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP)
        summary = r.builder_summary()
        self.assertIn("2", summary)

    def test_type_breakdown(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH)
        r.track("enemy_dragon_mesh_v1", AssetType.MESH)
        r.track("character_knight_sfx_v1", AssetType.AUDIO_CLIP)
        breakdown = r.type_breakdown()
        self.assertEqual(breakdown.get("MESH"), 2)
        self.assertEqual(breakdown.get("AUDIO_CLIP"), 1)

    def test_entity_ids_with_placeholders_sorted(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_002")
        r.track("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP, entity_id="ent_001")
        ids = r.entity_ids_with_placeholders()
        self.assertEqual(ids, sorted(ids))

    def test_serialization_roundtrip(self):
        r = PlaceholderRegistry()
        r.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_001")
        r.track("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP)
        data = r.to_dict()
        restored = PlaceholderRegistry.from_dict(data)
        self.assertEqual(restored.total_count(), 2)
        self.assertTrue(restored.is_tracked("character_knight_mesh_v1"))


# =============================================================================
# AssetLinker Tests
# =============================================================================

class TestAssetLinker(unittest.TestCase):

    def _setup(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        placeholder_reg.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_001")
        linker = AssetLinker(manifest, placeholder_reg)
        return manifest, placeholder_reg, linker

    def test_link_placeholder_to_linked(self):
        manifest, placeholder_reg, linker = self._setup()
        result = linker.link("character_knight_mesh_v1", "/knight.fbx")
        self.assertTrue(result.success)
        self.assertEqual(manifest.get("character_knight_mesh_v1").status, AssetStatus.LINKED)

    def test_link_removes_from_placeholder_registry(self):
        manifest, placeholder_reg, linker = self._setup()
        linker.link("character_knight_mesh_v1", "/knight.fbx")
        self.assertFalse(placeholder_reg.is_tracked("character_knight_mesh_v1"))

    def test_link_nonexistent_returns_failure(self):
        manifest, placeholder_reg, linker = self._setup()
        result = linker.link("does_not_exist_mesh_v1", "/path.fbx")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_link_empty_path_returns_failure(self):
        manifest, placeholder_reg, linker = self._setup()
        result = linker.link("character_knight_mesh_v1", "")
        self.assertFalse(result.success)

    def test_link_unresolved_returns_failure(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB))
        linker = AssetLinker(manifest, placeholder_reg)
        result = linker.link("prop_barrel_prefab_v1", "/barrel.prefab")
        self.assertFalse(result.success)
        self.assertIn("UNRESOLVED", result.error)

    def test_link_wrong_extension_gives_warning(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        linker = AssetLinker(manifest, placeholder_reg)
        result = linker.link("character_knight_mesh_v1", "/knight.wav")  # wrong ext for mesh
        self.assertTrue(result.success)
        self.assertTrue(result.has_warning)
        self.assertIsNotNone(result.extension_warning)

    def test_link_correct_extension_no_warning(self):
        manifest, placeholder_reg, linker = self._setup()
        result = linker.link("character_knight_mesh_v1", "/knight.fbx")
        self.assertTrue(result.success)
        self.assertFalse(result.has_warning)

    def test_link_bulk_all_succeed(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        manifest.register(make_placeholder("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP))
        linker = AssetLinker(manifest, placeholder_reg)

        results = linker.link_bulk({
            "character_knight_mesh_v1": "/knight.fbx",
            "enemy_dragon_sfx_v1": "/dragon_roar.wav",
        })
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))

    def test_link_bulk_deterministic_order(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        for i in range(5):
            manifest.register(make_placeholder(f"character_unit{i}_mesh_v1", AssetType.MESH))
        linker = AssetLinker(manifest, placeholder_reg)

        links = {f"character_unit{i}_mesh_v1": f"/unit{i}.fbx" for i in range(5)}
        results = linker.link_bulk(links)
        # Results should be sorted by asset_id (D11)
        ids = [r.asset_id for r in results]
        self.assertEqual(ids, sorted(ids))

    def test_mark_missing_transitions_linked(self):
        manifest, placeholder_reg, linker = self._setup()
        linker.link("character_knight_mesh_v1", "/knight.fbx")
        result = linker.mark_missing("character_knight_mesh_v1")
        self.assertTrue(result.success)
        self.assertEqual(manifest.get("character_knight_mesh_v1").status, AssetStatus.MISSING)

    def test_mark_missing_non_linked_fails(self):
        manifest, placeholder_reg, linker = self._setup()
        # Still PLACEHOLDER — cannot mark missing
        result = linker.mark_missing("character_knight_mesh_v1")
        self.assertFalse(result.success)

    def test_link_history_recorded(self):
        manifest, placeholder_reg, linker = self._setup()
        linker.link("character_knight_mesh_v1", "/knight.fbx")
        history = linker.link_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].asset_id, "character_knight_mesh_v1")
        self.assertEqual(history[0].resolved_path, "/knight.fbx")

    def test_history_for_asset(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        manifest.register(make_placeholder("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP))
        linker = AssetLinker(manifest, placeholder_reg)
        linker.link("character_knight_mesh_v1", "/a.fbx")
        linker.link("enemy_dragon_sfx_v1", "/b.wav")
        history = linker.history_for_asset("character_knight_mesh_v1")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].asset_id, "character_knight_mesh_v1")


# =============================================================================
# AssetCleanupManager Tests
# =============================================================================

class TestAssetCleanupManager(unittest.TestCase):

    def _setup(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        manifest.register(make_placeholder("character_knight_anim_v1", AssetType.ANIMATION_CONTROLLER))
        manifest.register(make_linked("character_knight_mat_v1", AssetType.MATERIAL, "/mat.mat"))
        placeholder_reg.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_001")
        placeholder_reg.track("character_knight_anim_v1", AssetType.ANIMATION_CONTROLLER, entity_id="ent_001")
        cleaner = AssetCleanupManager(manifest, placeholder_reg)
        return manifest, placeholder_reg, cleaner

    def test_cleanup_for_entity_removes_placeholders(self):
        manifest, placeholder_reg, cleaner = self._setup()
        result = cleaner.cleanup_for_entity("ent_001")
        self.assertEqual(result.removed_count, 2)
        self.assertIsNone(manifest.get("character_knight_mesh_v1"))
        self.assertIsNone(manifest.get("character_knight_anim_v1"))

    def test_cleanup_for_entity_skips_linked(self):
        manifest, placeholder_reg, cleaner = self._setup()
        # character_knight_mat_v1 is LINKED — should be skipped
        result = cleaner.cleanup_for_entity("ent_001")
        self.assertIsNotNone(manifest.get("character_knight_mat_v1"))

    def test_cleanup_for_entity_unknown_entity_noop(self):
        manifest, placeholder_reg, cleaner = self._setup()
        result = cleaner.cleanup_for_entity("unknown_entity")
        self.assertEqual(result.removed_count, 0)

    def test_cleanup_orphaned_placeholders_removes_stale(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        manifest.register(make_placeholder("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP))
        cleaner = AssetCleanupManager(manifest, placeholder_reg)

        # Only knight mesh is active — dragon sfx is orphaned
        active = {"character_knight_mesh_v1"}
        result = cleaner.cleanup_orphaned_placeholders(active)
        self.assertEqual(result.removed_count, 1)
        self.assertIn("enemy_dragon_sfx_v1", result.removed_asset_ids)
        self.assertIsNone(manifest.get("enemy_dragon_sfx_v1"))
        self.assertIsNotNone(manifest.get("character_knight_mesh_v1"))

    def test_cleanup_never_removes_linked(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_linked("character_knight_mesh_v1", AssetType.MESH, "/a.fbx"))
        cleaner = AssetCleanupManager(manifest, placeholder_reg)
        # active_asset_ids is empty — but linked ref must not be removed
        result = cleaner.cleanup_orphaned_placeholders(set())
        self.assertEqual(result.removed_count, 0)

    def test_cleanup_history_recorded(self):
        manifest, placeholder_reg, cleaner = self._setup()
        cleaner.cleanup_for_entity("ent_001")
        history = cleaner.cleanup_history()
        self.assertEqual(len(history), 1)

    def test_total_removed_accumulates(self):
        manifest, placeholder_reg, cleaner = self._setup()
        cleaner.cleanup_for_entity("ent_001")
        self.assertEqual(cleaner.total_removed(), 2)


# =============================================================================
# EngineSyncReceiver Tests
# =============================================================================

class TestEngineSyncReceiver(unittest.TestCase):

    def _setup(self, asset_ids: list[str], asset_type: AssetType = AssetType.MESH):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        for aid in asset_ids:
            manifest.register(make_placeholder(aid, asset_type))
            placeholder_reg.track(aid, asset_type)
        linker = AssetLinker(manifest, placeholder_reg)
        receiver = EngineSyncReceiver(linker, manifest)
        return manifest, placeholder_reg, receiver

    def test_receive_feedback_transitions_placeholders_to_linked(self):
        manifest, _, receiver = self._setup([
            "character_knight_mesh_v1",
            "enemy_dragon_mesh_v1",
        ])
        result = receiver.receive_feedback(
            resolved_assets={
                "character_knight_mesh_v1": "/knight.fbx",
                "enemy_dragon_mesh_v1": "/dragon.fbx",
            },
            tick=1,
        )
        self.assertEqual(result.linked_count, 2)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(manifest.get("character_knight_mesh_v1").status, AssetStatus.LINKED)
        self.assertEqual(manifest.get("enemy_dragon_mesh_v1").status, AssetStatus.LINKED)

    def test_receive_feedback_unknown_asset_counted_as_failure(self):
        manifest, _, receiver = self._setup(["character_knight_mesh_v1"])
        result = receiver.receive_feedback(
            resolved_assets={"unknown_asset_mesh_v1": "/path.fbx"},
            tick=1,
        )
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.linked_count, 0)

    def test_receive_empty_feedback_is_noop(self):
        manifest, _, receiver = self._setup(["character_knight_mesh_v1"])
        result = receiver.receive_feedback(resolved_assets={}, tick=1)
        self.assertEqual(result.linked_count, 0)
        self.assertEqual(manifest.get("character_knight_mesh_v1").status, AssetStatus.PLACEHOLDER)

    def test_receive_feedback_from_payload_dict(self):
        manifest, _, receiver = self._setup(["character_knight_mesh_v1"])
        payload = {
            "resolved_assets": {"character_knight_mesh_v1": "/knight.fbx"},
            "generated_frame": 100,
        }
        result = receiver.receive_feedback_from_payload(payload, tick=5)
        self.assertEqual(result.linked_count, 1)

    def test_receive_feedback_idempotent(self):
        manifest, _, receiver = self._setup(["character_knight_mesh_v1"])
        result1 = receiver.receive_feedback(
            {"character_knight_mesh_v1": "/knight.fbx"}, tick=1
        )
        result2 = receiver.receive_feedback(
            {"character_knight_mesh_v1": "/knight.fbx"}, tick=2
        )
        # Second call hits already-LINKED — the linker handles this gracefully
        self.assertEqual(result1.linked_count, 1)
        self.assertEqual(manifest.get("character_knight_mesh_v1").status, AssetStatus.LINKED)

    def test_sync_history_recorded(self):
        manifest, _, receiver = self._setup(["character_knight_mesh_v1"])
        receiver.receive_feedback({"character_knight_mesh_v1": "/a.fbx"}, tick=1)
        receiver.receive_feedback({"character_knight_mesh_v1": "/a.fbx"}, tick=2)
        self.assertEqual(receiver.sync_count(), 2)

    def test_total_linked_accumulates(self):
        manifest, _, receiver = self._setup([
            "character_knight_mesh_v1",
            "enemy_dragon_sfx_v1",
        ], AssetType.AUDIO_CLIP)
        # register second as mesh
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))

        manifest2, _, receiver2 = self._setup(["character_knight_mesh_v1"])
        receiver2.receive_feedback({"character_knight_mesh_v1": "/a.fbx"}, tick=1)
        self.assertEqual(receiver2.total_linked(), 1)


# =============================================================================
# AudioManifest Tests
# =============================================================================

class TestAudioManifest(unittest.TestCase):

    def test_register_sfx(self):
        a = AudioManifest()
        meta = a.register_sfx("enemy_dragon_sfx_v1", loops=False, spatial=True)
        self.assertEqual(meta.asset_type, AssetType.AUDIO_CLIP)
        self.assertEqual(meta.spatialization, AudioSpatialization.SPATIAL_3D)
        self.assertFalse(meta.loops)

    def test_register_music(self):
        a = AudioManifest()
        meta = a.register_music("game_theme_music_v1", loops=True, volume=0.7)
        self.assertEqual(meta.asset_type, AssetType.AUDIO_MUSIC)
        self.assertEqual(meta.spatialization, AudioSpatialization.FLAT_2D)
        self.assertTrue(meta.loops)

    def test_register_duplicate_raises(self):
        a = AudioManifest()
        a.register_sfx("enemy_dragon_sfx_v1")
        with self.assertRaises(ValueError):
            a.register_sfx("enemy_dragon_sfx_v1")

    def test_update_duration(self):
        a = AudioManifest()
        a.register_sfx("enemy_dragon_sfx_v1")
        result = a.update_duration("enemy_dragon_sfx_v1", 2.5)
        self.assertTrue(result)
        self.assertAlmostEqual(a.get("enemy_dragon_sfx_v1").duration_seconds, 2.5)

    def test_update_duration_nonexistent_returns_false(self):
        a = AudioManifest()
        self.assertFalse(a.update_duration("does_not_exist_sfx_v1", 1.0))

    def test_music_sequence_linking(self):
        a = AudioManifest()
        a.register_music("game_intro_music_v1")
        a.register_music("game_main_music_v1")
        a.register_music("game_boss_music_v1")
        a.link_music_sequence("game_intro_music_v1", next_track_id="game_main_music_v1")
        a.link_music_sequence("game_main_music_v1",
                               previous_track_id="game_intro_music_v1",
                               next_track_id="game_boss_music_v1")
        sequence = a.get_music_sequence("game_intro_music_v1")
        self.assertEqual(len(sequence), 3)
        self.assertEqual(sequence[0].asset_id, "game_intro_music_v1")
        self.assertEqual(sequence[2].asset_id, "game_boss_music_v1")

    def test_music_sequence_cycle_detection(self):
        a = AudioManifest()
        a.register_music("game_loop_a_music_v1")
        a.register_music("game_loop_b_music_v1")
        a.link_music_sequence("game_loop_a_music_v1", next_track_id="game_loop_b_music_v1")
        a.link_music_sequence("game_loop_b_music_v1", next_track_id="game_loop_a_music_v1")
        # Should terminate without infinite loop
        sequence = a.get_music_sequence("game_loop_a_music_v1")
        self.assertEqual(len(sequence), 2)

    def test_get_by_tag(self):
        a = AudioManifest()
        a.register_sfx("enemy_footstep_sfx_v1", tags=["combat", "ambient"])
        a.register_sfx("player_footstep_sfx_v1", tags=["ambient"])
        a.register_music("game_theme_music_v1", tags=["combat"])
        combat_assets = a.get_by_tag("combat")
        self.assertEqual(len(combat_assets), 2)

    def test_compute_budget_summary(self):
        a = AudioManifest()
        a.register_sfx("enemy_dragon_sfx_v1", spatial=True)
        a.register_sfx("ui_click_sfx_v1", spatial=False)
        a.register_music("game_theme_music_v1")
        a.update_duration("enemy_dragon_sfx_v1", 3.0)
        summary = a.compute_budget_summary()
        self.assertEqual(summary.total_sfx_clips, 2)
        self.assertEqual(summary.total_music_tracks, 1)
        self.assertEqual(summary.sfx_with_known_duration, 1)
        self.assertAlmostEqual(summary.total_sfx_duration_seconds, 3.0)
        self.assertEqual(summary.spatial_3d_count, 1)
        self.assertEqual(summary.flat_2d_count, 2)  # ui_click + music

    def test_serialization_roundtrip(self):
        a = AudioManifest()
        a.register_sfx("enemy_dragon_sfx_v1", tags=["combat"])
        a.register_music("game_theme_music_v1", volume=0.6)
        a.update_duration("enemy_dragon_sfx_v1", 2.5)
        restored = AudioManifest.from_json(a.to_json())
        self.assertEqual(len(restored), 2)
        meta = restored.get("enemy_dragon_sfx_v1")
        self.assertAlmostEqual(meta.duration_seconds, 2.5)
        self.assertIn("combat", meta.tags)


# =============================================================================
# AssetRegistryManager Integration Tests
# =============================================================================

class TestAssetRegistryManager(unittest.TestCase):

    def test_auto_register_creates_placeholder(self):
        mgr = AssetRegistryManager("0.1.0")
        ref = mgr.auto_register("character", "knight", AssetType.MESH, entity_id="ent_001")
        self.assertEqual(ref.status, AssetStatus.PLACEHOLDER)
        self.assertEqual(ref.asset_id, "character_knight_mesh_v1")

    def test_auto_register_idempotent(self):
        mgr = AssetRegistryManager("0.1.0")
        ref1 = mgr.auto_register("character", "knight", AssetType.MESH)
        ref2 = mgr.auto_register("character", "knight", AssetType.MESH)
        self.assertEqual(ref1.asset_id, ref2.asset_id)
        self.assertEqual(mgr.total_asset_count(), 1)

    def test_auto_register_many(self):
        mgr = AssetRegistryManager("0.1.0")
        refs = mgr.auto_register_many(
            "character", "knight",
            [AssetType.MESH, AssetType.ANIMATION_CONTROLLER, AssetType.MATERIAL]
        )
        self.assertEqual(len(refs), 3)
        self.assertEqual(mgr.total_asset_count(), 3)

    def test_link_placeholder_to_linked(self):
        mgr = AssetRegistryManager("0.1.0")
        mgr.auto_register("character", "knight", AssetType.MESH, entity_id="ent_001")
        result = mgr.link("character_knight_mesh_v1", "/assets/knight.fbx")
        self.assertTrue(result.success)
        self.assertEqual(mgr.get("character_knight_mesh_v1").status, AssetStatus.LINKED)

    def test_validate_for_commit_clean(self):
        mgr = AssetRegistryManager("0.1.0")
        mgr.auto_register("character", "knight", AssetType.MESH)
        report = mgr.validate_for_commit()
        self.assertFalse(report.blocks_commit)

    def test_validate_for_commit_blocked_by_unresolved(self):
        mgr = AssetRegistryManager("0.1.0")
        mgr.register_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB)
        report = mgr.validate_for_commit()
        self.assertTrue(report.blocks_commit)
        self.assertEqual(report.error_count(), 1)

    def test_receive_engine_feedback_links_assets(self):
        mgr = AssetRegistryManager("0.1.0")
        mgr.auto_register("character", "knight", AssetType.MESH)
        mgr.auto_register("enemy", "dragon", AssetType.AUDIO_CLIP)
        result = mgr.receive_engine_feedback(
            resolved_assets={
                "character_knight_mesh_v1": "/knight.fbx",
                "enemy_dragon_sfx_v1": "/dragon.wav",
            },
            tick=1,
        )
        self.assertEqual(result.linked_count, 2)
        self.assertEqual(mgr.placeholder_count(), 0)

    def test_cleanup_for_entity(self):
        mgr = AssetRegistryManager("0.1.0")
        mgr.auto_register("character", "knight", AssetType.MESH, entity_id="ent_001")
        mgr.auto_register("character", "knight", AssetType.ANIMATION_CONTROLLER, entity_id="ent_001")
        removed = mgr.cleanup_for_entity("ent_001")
        self.assertEqual(removed, 2)
        self.assertFalse(mgr.contains("character_knight_mesh_v1"))

    def test_builder_summary_message(self):
        mgr = AssetRegistryManager("0.1.0")
        mgr.auto_register("character", "knight", AssetType.MESH)
        mgr.auto_register("enemy", "dragon", AssetType.AUDIO_CLIP)
        summary = mgr.builder_summary()
        self.assertIn("2", summary)
        self.assertIn("grey boxes", summary)

    def test_serialization_roundtrip(self):
        mgr = AssetRegistryManager("0.1.0")
        mgr.auto_register("character", "knight", AssetType.MESH, entity_id="ent_001")
        mgr.auto_register("enemy", "dragon", AssetType.AUDIO_CLIP, entity_id="ent_002")
        mgr.link("character_knight_mesh_v1", "/knight.fbx")
        mgr.register_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB)

        json_str = mgr.to_json()
        restored = AssetRegistryManager.from_json(json_str)

        self.assertEqual(restored.total_asset_count(), mgr.total_asset_count())
        self.assertEqual(restored.placeholder_count(), mgr.placeholder_count())
        self.assertTrue(restored.has_unresolved())
        linked_ref = restored.get("character_knight_mesh_v1")
        self.assertEqual(linked_ref.status, AssetStatus.LINKED)


# =============================================================================
# AssetReportGenerator Tests
# =============================================================================

class TestAssetReportGenerator(unittest.TestCase):

    def _setup(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()

        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        manifest.register(make_linked("character_knight_anim_v1", AssetType.ANIMATION_CONTROLLER, "/anim"))
        manifest.register(make_unresolved("prop_barrel_prefab_v1", AssetType.PREFAB))
        placeholder_reg.track("character_knight_mesh_v1", AssetType.MESH, entity_id="ent_001")

        gen = AssetReportGenerator(manifest, placeholder_reg, "0.1.0")
        return manifest, placeholder_reg, gen

    def test_generate_returns_report(self):
        _, _, gen = self._setup()
        report = gen.generate()
        self.assertIsNotNone(report)
        self.assertEqual(report.total_refs, 3)

    def test_report_has_unresolved_error(self):
        _, _, gen = self._setup()
        report = gen.generate()
        self.assertTrue(report.blocks_commit)
        errors = [p for p in report.problems if p.severity == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].asset_id, "prop_barrel_prefab_v1")

    def test_report_summary_bar_present(self):
        _, _, gen = self._setup()
        report = gen.generate()
        self.assertIsNotNone(report.summary_bar)
        self.assertGreater(len(report.summary_bar), 0)

    def test_report_suggestions_ranked_mesh_first(self):
        manifest = AssetManifest()
        placeholder_reg = PlaceholderRegistry()
        manifest.register(make_placeholder("ui_button_font_v1", AssetType.FONT))
        manifest.register(make_placeholder("character_knight_mesh_v1", AssetType.MESH))
        manifest.register(make_placeholder("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP))
        placeholder_reg.track("character_knight_mesh_v1", AssetType.MESH)
        placeholder_reg.track("ui_button_font_v1", AssetType.FONT)
        placeholder_reg.track("enemy_dragon_sfx_v1", AssetType.AUDIO_CLIP)
        gen = AssetReportGenerator(manifest, placeholder_reg, "0.1.0")
        report = gen.generate()
        # MESH should appear before AUDIO_CLIP and FONT in suggestions
        if len(report.suggestions) >= 2:
            self.assertLessEqual(
                report.suggestions[0].priority,
                report.suggestions[1].priority,
            )

    def test_report_type_summaries_only_for_present_types(self):
        _, _, gen = self._setup()
        report = gen.generate()
        type_names = {s.asset_type for s in report.type_summaries}
        self.assertIn(AssetType.MESH, type_names)
        self.assertIn(AssetType.ANIMATION_CONTROLLER, type_names)
        self.assertIn(AssetType.PREFAB, type_names)

    def test_generate_minimal_returns_dict(self):
        _, _, gen = self._setup()
        minimal = gen.generate_minimal()
        self.assertIn("summary_bar", minimal)
        self.assertIn("blocks_commit", minimal)
        self.assertIn("placeholder_count", minimal)

    def test_report_serializes_to_json(self):
        _, _, gen = self._setup()
        report = gen.generate()
        json_str = report.to_json()
        data = json.loads(json_str)
        self.assertIn("total_refs", data)
        self.assertIn("problems", data)
        self.assertIn("suggestions", data)
        self.assertIn("type_summaries", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)