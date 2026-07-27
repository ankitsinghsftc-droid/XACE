import tempfile
import unittest
import json
from pathlib import Path

import sys


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from cgs_persistence import CGSLoadError, CGSPersistence, SnapshotRecord  # noqa: E402


class CGSPersistenceAuthorityTests(unittest.TestCase):
    def test_cgs_save_and_snapshot_create_project_write_lock(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-lock-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            cgs = _sample_cgs("a" * 64)

            persist.save(cgs)
            persist.snapshot(
                cgs,
                SnapshotRecord(
                    cgs_hash="a" * 64,
                    schema_version="0.1.0",
                    turn_index=0,
                    mutation_count=1,
                    timestamp=1.0,
                    summary="lock test",
                ),
            )

            self.assertTrue((root / ".xace" / "cgs.write.lock").exists())
            self.assertTrue((root / ".xace" / "snapshot_index.json").exists())
            self.assertEqual(persist.current_cgs_hash(), "a" * 64)

    def test_recover_removes_leftover_temp_files(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-temp-recover-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            persist.save(_sample_cgs("a" * 64))
            stale_root = root / ".xace_tmp_crash.json"
            stale_snap = root / ".xace" / "snapshots" / ".xace_tmp_crash.json"
            stale_root.write_text("partial", encoding="utf-8")
            stale_snap.write_text("partial", encoding="utf-8")

            report = persist.recover()

            self.assertEqual(report.temp_files_removed, 2)
            self.assertFalse(stale_root.exists())
            self.assertFalse(stale_snap.exists())

    def test_interrupted_save_failure_preserves_previous_cgs(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-partial-save-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            persist.save(_sample_cgs("a" * 64))

            with self.assertRaises(CGSLoadError):
                persist.save({"metadata": {"name": "Broken"}})

            loaded = persist.load()
            self.assertEqual(loaded["metadata"]["cgs_hash"], "a" * 64)

    def test_snapshot_index_corruption_rebuilds_from_valid_snapshots(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-index-recover-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            cgs = _sample_cgs("b" * 64)
            persist.save(cgs)
            persist.snapshot(cgs, _record("b" * 64, timestamp=2.0))
            (root / ".xace" / "snapshot_index.json").write_text("{bad json", encoding="utf-8")

            snapshots = persist.list_snapshots()

            self.assertEqual([record.cgs_hash for record in snapshots], ["b" * 64])
            rebuilt = json.loads((root / ".xace" / "snapshot_index.json").read_text(encoding="utf-8"))
            self.assertEqual(rebuilt["snapshots"][0]["cgs_hash"], "b" * 64)

    def test_recover_restores_latest_valid_snapshot_when_main_cgs_corrupt(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-main-recover-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            old = _sample_cgs("c" * 64)
            latest = _sample_cgs("d" * 64)
            persist.save(old)
            persist.snapshot(old, _record("c" * 64, timestamp=1.0))
            persist.snapshot(latest, _record("d" * 64, timestamp=3.0))
            (root / "game.cgs.json").write_text("{corrupt", encoding="utf-8")

            loaded = persist.load()

            self.assertEqual(loaded["metadata"]["cgs_hash"], "d" * 64)
            self.assertEqual(persist.current_cgs_hash(), "d" * 64)

    def test_corrupt_snapshot_is_excluded_from_rebuilt_index(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-snapshot-corrupt-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            good = _sample_cgs("e" * 64)
            persist.save(good)
            persist.snapshot(good, _record("e" * 64, timestamp=2.0))
            bad_path = root / ".xace" / "snapshots" / f"{'f' * 64}.json"
            bad_path.write_text("{bad json", encoding="utf-8")
            (root / ".xace" / "snapshot_index.json").write_text(
                json.dumps({
                    "snapshots": [
                        _record("f" * 64, timestamp=5.0).to_dict(),
                        _record("e" * 64, timestamp=2.0).to_dict(),
                    ]
                }),
                encoding="utf-8",
            )

            snapshots = persist.list_snapshots()

            self.assertEqual([record.cgs_hash for record in snapshots], ["e" * 64])

    def test_component_schemas_declare_schema_only_system_access(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-component-schemas-") as tmp:
            root = Path(tmp)
            persist = CGSPersistence(root)
            cgs = _sample_cgs("f" * 64)
            cgs["component_schemas"] = [
                {
                    "type_id": 700,
                    "name": "PLUGIN_WEATHER_STATE_V1",
                    "defaults": {"humidity": 0},
                    "source": "plugin",
                },
                {
                    "type_id": 701,
                    "name": "COMP_GENERATED_COUNTER_V1",
                    "defaults": {"count": 0},
                    "source": "generated",
                },
            ]
            cgs["global_systems"] = [
                {
                    "id": "PluginWeatherSystem",
                    "phase": "Simulation",
                    "reads": [700],
                    "writes": [701],
                    "depends_on": [],
                    "deterministic": True,
                }
            ]

            persist.save(cgs)
            loaded = persist.load()

            self.assertEqual(loaded["component_schemas"][0]["type_id"], 700)
            self.assertEqual(loaded["global_systems"][0]["writes"], [701])

    def test_duplicate_component_schema_type_ids_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="xace-cgs-component-schema-dupe-") as tmp:
            persist = CGSPersistence(tmp)
            cgs = _sample_cgs("1" * 64)
            cgs["component_schemas"] = [
                {"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {}},
                {"type_id": 700, "name": "PLUGIN_WEATHER_STATE_V1", "defaults": {}},
            ]

            with self.assertRaises(CGSLoadError) as ctx:
                persist.save(cgs)

            self.assertIn(
                "component_schemas declares duplicate component type_id 700",
                str(ctx.exception),
            )

    def test_x10_016_recover_repairs_interrupted_plan_write_from_proof_bundle(self):
        with tempfile.TemporaryDirectory(prefix="xace-plan-proof-recover-") as tmp:
            root = Path(tmp)
            cgs_hash = "2" * 64
            persist = CGSPersistence(root)
            cgs = _sample_structural_cgs(cgs_hash)
            persist.save(cgs)
            persist.snapshot(cgs, _record(cgs_hash, timestamp=2.0))
            persisted_plan = persist.save_execution_plan(
                cgs_hash,
                json.dumps(_sample_plan(cgs_hash), sort_keys=True),
                cgs=cgs,
                validation={"ok": True},
            )
            persist.save_sgc_proof_bundle(cgs, persisted_plan, validation={"ok": True})
            plan_path = root / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
            plan_path.write_text("{interrupted", encoding="utf-8")

            report = persist.recover()
            repaired = json.loads(plan_path.read_text(encoding="utf-8"))

            self.assertEqual(report.execution_plans_repaired, 1)
            self.assertTrue(persist.verify_execution_plan(cgs_hash))
            self.assertEqual(repaired["compiled_from_cgs_hash"], cgs_hash)

    def test_x10_016_recover_restores_latest_snapshot_with_valid_plan(self):
        with tempfile.TemporaryDirectory(prefix="xace-plan-rollback-recover-") as tmp:
            root = Path(tmp)
            old_hash = "3" * 64
            failed_hash = "4" * 64
            persist = CGSPersistence(root)
            old_cgs = _sample_structural_cgs(old_hash)
            failed_cgs = _sample_structural_cgs(failed_hash)
            persist.save(old_cgs)
            persist.snapshot(old_cgs, _record(old_hash, timestamp=1.0))
            persist.save_execution_plan(
                old_hash,
                json.dumps(_sample_plan(old_hash), sort_keys=True),
                cgs=old_cgs,
                validation={"ok": True},
            )
            persist.save(failed_cgs)
            persist.snapshot(failed_cgs, _record(failed_hash, timestamp=3.0))
            plan_path = root / ".xace" / "execution_plans" / f"{failed_hash}.plan.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("{interrupted", encoding="utf-8")

            report = persist.recover()
            loaded = persist.load()

            self.assertEqual(report.execution_plans_removed, 1)
            self.assertEqual(report.restored_cgs_hash, old_hash)
            self.assertEqual(loaded["metadata"]["cgs_hash"], old_hash)

    def test_x10_016_corrupt_main_ignores_planless_structural_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="xace-corrupt-main-planless-") as tmp:
            root = Path(tmp)
            old_hash = "5" * 64
            failed_hash = "6" * 64
            persist = CGSPersistence(root)
            old_cgs = _sample_structural_cgs(old_hash)
            failed_cgs = _sample_structural_cgs(failed_hash)
            persist.save(old_cgs)
            persist.snapshot(old_cgs, _record(old_hash, timestamp=1.0))
            persist.save_execution_plan(
                old_hash,
                json.dumps(_sample_plan(old_hash), sort_keys=True),
                cgs=old_cgs,
                validation={"ok": True},
            )
            persist.snapshot(failed_cgs, _record(failed_hash, timestamp=5.0))
            (root / "game.cgs.json").write_text("{corrupt", encoding="utf-8")

            report = persist.recover()
            loaded = persist.load()

            self.assertEqual(report.restored_cgs_hash, old_hash)
            self.assertEqual(loaded["metadata"]["cgs_hash"], old_hash)


def _sample_cgs(cgs_hash: str) -> dict:
    return {
        "metadata": {
            "name": "Lock Test",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": cgs_hash,
        },
        "global_systems": [],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [],
                "systems": [],
                "rules": [],
            }
        ],
    }


def _sample_structural_cgs(cgs_hash: str) -> dict:
    cgs = _sample_cgs(cgs_hash)
    cgs["component_schemas"] = [
        {
            "type_id": 710,
            "name": "COMP_RECOVERY_COUNTER_V1",
            "defaults": {"count": 0},
            "source": "generated",
        }
    ]
    cgs["global_systems"] = [
        {
            "id": "RecoveryCounterSystem",
            "phase": "Simulation",
            "reads": [710],
            "writes": [710],
            "depends_on": [],
            "deterministic": True,
        }
    ]
    return cgs


def _sample_plan(cgs_hash: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "plan_version": 1,
        "adapter_protocol_version": 1,
        "migration_status": "current",
        "created_tick": 0,
        "plan_hash": "c" * 64,
        "compiled_from_cgs_hash": cgs_hash,
        "all_system_ids": ["RecoveryCounterSystem"],
        "phases": {
            "2": {
                "phase": "Simulation",
                "groups": [
                    {
                        "group_id": "Simulation_group_0",
                        "phase": "Simulation",
                        "parallel": False,
                        "systems": ["RecoveryCounterSystem"],
                        "serialization_constraints": [],
                        "execution_index": 0,
                    }
                ],
                "total_system_count": 1,
            }
        },
    }


def _record(cgs_hash: str, timestamp: float) -> SnapshotRecord:
    return SnapshotRecord(
        cgs_hash=cgs_hash,
        schema_version="0.1.0",
        turn_index=0,
        mutation_count=1,
        timestamp=timestamp,
        summary="authority test",
    )


if __name__ == "__main__":
    unittest.main()
