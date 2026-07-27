import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parents[2]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from cgs_persistence import CGSSaveError, CGSPersistence  # noqa: E402
from sgc_plan_validator import (  # noqa: E402
    SgcExecutionPlanContractError,
    validate_persisted_execution_plan_contract,
)


class SgcExecutionPlanContractTests(unittest.TestCase):
    def test_schema_declares_persisted_execution_plan_contract(self):
        schema_path = REPO_ROOT / "docs" / "schemas" / "xace-sgc-execution-plan.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema["$id"], "https://xace.dev/schemas/xace-sgc-execution-plan.schema.json")
        self.assertIn("compiled_from_cgs_hash", schema["required"])
        self.assertIn("plan_hash", schema["required"])
        self.assertIn("adapter_protocol_version", schema["required"])
        self.assertIn("migration_status", schema["required"])
        self.assertIn("component_access_sets", schema["required"])
        self.assertIn("system_metadata", schema["required"])
        self.assertIn("proof_bundle", schema["required"])
        self.assertEqual(schema["properties"]["compiled_from_cgs_hash"]["pattern"], "^[0-9a-f]{64}$")
        self.assertEqual(schema["properties"]["plan_hash"]["pattern"], "^[0-9a-f]{64}$")
        self.assertIn("phases", schema["required"])
        self.assertEqual(
            schema["properties"]["component_access_sets"]["$ref"],
            "#/$defs/ComponentAccessSets",
        )

    def test_persisted_contract_accepts_expected_path_and_hashes(self):
        cgs_hash = "a" * 64
        with tempfile.TemporaryDirectory(prefix="xace-sgc-plan-contract-") as tmp:
            plan_path = Path(tmp) / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
            report = validate_persisted_execution_plan_contract(
                cgs_hash,
                json.dumps(_sample_plan(cgs_hash), sort_keys=True),
                storage_path=plan_path,
            )

        self.assertTrue(report["ok"])
        self.assertFalse(report["persistence_metadata_required"])
        self.assertEqual(report["expected_filename"], f"{cgs_hash}.plan.json")
        self.assertEqual(report["runtime_load_status"], "strict_loader_ready")
        self.assertIn("Regenerate via SGC", report["migration_policy"])

    def test_strict_persisted_contract_requires_builder_metadata(self):
        cgs_hash = "a" * 64

        with self.assertRaises(SgcExecutionPlanContractError) as ctx:
            validate_persisted_execution_plan_contract(
                cgs_hash,
                json.dumps(_sample_plan(cgs_hash), sort_keys=True),
                require_persistence_metadata=True,
            )

        issues = "; ".join(ctx.exception.report["issues"])
        self.assertIn("component_access_sets is required", issues)
        self.assertIn("system_metadata is required", issues)
        self.assertIn("proof_bundle is required", issues)

    def test_strict_persisted_contract_requires_runtime_compatibility_metadata(self):
        cgs_hash = "a" * 64
        plan = _sample_plan(cgs_hash)
        plan.pop("adapter_protocol_version")
        plan.pop("migration_status")

        with self.assertRaises(SgcExecutionPlanContractError) as ctx:
            validate_persisted_execution_plan_contract(
                cgs_hash,
                json.dumps(plan, sort_keys=True),
                require_persistence_metadata=True,
            )

        issues = "; ".join(ctx.exception.report["issues"])
        self.assertIn("adapter_protocol_version is required", issues)
        self.assertIn("migration_status is required", issues)

    def test_persisted_contract_rejects_incompatible_runtime_metadata(self):
        cgs_hash = "a" * 64
        plan = _sample_plan(cgs_hash)
        plan["adapter_protocol_version"] = 99
        plan["migration_status"] = "pending"

        with self.assertRaises(SgcExecutionPlanContractError) as ctx:
            validate_persisted_execution_plan_contract(
                cgs_hash,
                json.dumps(plan, sort_keys=True),
            )

        issues = "; ".join(ctx.exception.report["issues"])
        self.assertIn("adapter_protocol_version must match", issues)
        self.assertIn("migration_status must be 'current'", issues)

    def test_persisted_contract_rejects_mismatched_cgs_hash(self):
        cgs_hash = "a" * 64
        plan = _sample_plan("b" * 64)

        with self.assertRaises(SgcExecutionPlanContractError) as ctx:
            validate_persisted_execution_plan_contract(cgs_hash, json.dumps(plan, sort_keys=True))

        self.assertFalse(ctx.exception.report["ok"])
        self.assertIn("compiled_from_cgs_hash must match", "; ".join(ctx.exception.report["issues"]))

    def test_persisted_contract_rejects_wrong_storage_path(self):
        cgs_hash = "a" * 64
        wrong_path = Path(".xace") / "proof" / "sgc" / f"{cgs_hash}.plan.json"

        with self.assertRaises(SgcExecutionPlanContractError) as ctx:
            validate_persisted_execution_plan_contract(
                cgs_hash,
                json.dumps(_sample_plan(cgs_hash), sort_keys=True),
                storage_path=wrong_path,
            )

        self.assertIn("storage path", "; ".join(ctx.exception.report["issues"]))

    def test_cgs_persistence_refuses_invalid_execution_plan_contract(self):
        cgs_hash = "a" * 64
        bad_plan = _sample_plan("b" * 64)
        with tempfile.TemporaryDirectory(prefix="xace-sgc-plan-persist-") as tmp:
            persist = CGSPersistence(tmp)

            with self.assertRaises(CGSSaveError):
                persist.save_execution_plan(
                    cgs_hash,
                    json.dumps(bad_plan, sort_keys=True),
                    cgs=_sample_cgs(cgs_hash),
                )

            self.assertFalse((Path(tmp) / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json").exists())

    def test_cgs_persistence_refuses_invalid_cgs_before_sgc_input(self):
        cgs_hash = "a" * 64
        cgs = _sample_cgs(cgs_hash)
        cgs["modes"][0]["systems"][1]["depends_on"] = ["MissingSystem"]

        with tempfile.TemporaryDirectory(prefix="xace-sgc-cgs-schema-") as tmp:
            persist = CGSPersistence(tmp)

            with self.assertRaises(CGSSaveError) as ctx:
                persist.save_execution_plan(
                    cgs_hash,
                    json.dumps(_sample_plan(cgs_hash), sort_keys=True),
                    cgs=cgs,
                )

            message = str(ctx.exception)
            self.assertIn("CGS schema validation failed before SGC input", message)
            self.assertIn("references unknown system 'MissingSystem'", message)
            self.assertFalse((Path(tmp) / ".xace" / "execution_plans").exists())

    def test_cgs_persistence_writes_canonical_reproducible_enriched_execution_plan(self):
        cgs_hash = "a" * 64
        plan = _sample_plan(cgs_hash)
        cgs = _sample_cgs(cgs_hash)
        validation = {"ok": True, "load_ready": True, "rollback_compatible": True}

        with tempfile.TemporaryDirectory(prefix="xace-sgc-plan-persist-") as tmp:
            persist = CGSPersistence(tmp)
            first = persist.save_execution_plan(
                cgs_hash,
                json.dumps(plan, indent=2),
                cgs=cgs,
                validation=validation,
            )
            second = persist.save_execution_plan(
                cgs_hash,
                json.dumps(plan, sort_keys=True, separators=(",", ":")),
                cgs=cgs,
                validation=validation,
            )

            plan_path = Path(tmp) / ".xace" / "execution_plans" / f"{cgs_hash}.plan.json"
            stored = plan_path.read_text(encoding="utf-8")
            persisted = json.loads(stored)

        self.assertEqual(first, second)
        self.assertEqual(stored, first)
        self.assertEqual(stored, json.dumps(persisted, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        self.assertEqual(persisted["compiled_from_cgs_hash"], cgs_hash)
        self.assertEqual(persisted["plan_hash"], "c" * 64)
        self.assertEqual(persisted["schema_version"], "0.1.0")
        self.assertEqual(persisted["plan_version"], 1)
        self.assertEqual(persisted["adapter_protocol_version"], 1)
        self.assertEqual(persisted["migration_status"], "current")
        self.assertEqual(
            persisted["component_access_sets"]["by_system"]["InputSystem"],
            {"reads": [10], "writes": [11]},
        )
        self.assertEqual(persisted["component_access_sets"]["all_reads"], [10, 11, 20])
        self.assertEqual(persisted["component_access_sets"]["all_writes"], [11, 30])
        self.assertEqual(persisted["component_access_sets"]["component_ids"], [10, 11, 20, 30])
        self.assertEqual(persisted["system_metadata"]["systems"]["MovementSystem"]["depends_on"], ["InputSystem"])
        self.assertEqual(persisted["proof_bundle"]["path"], f".xace/proof/sgc/{cgs_hash}")
        self.assertEqual(persisted["proof_bundle"]["plan_hash"], "c" * 64)

        strict_report = validate_persisted_execution_plan_contract(
            cgs_hash,
            stored,
            require_persistence_metadata=True,
        )
        self.assertTrue(strict_report["ok"])
        self.assertEqual(strict_report["component_access_system_count"], 2)
        self.assertEqual(strict_report["system_metadata_count"], 2)


def _sample_plan(cgs_hash: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "plan_version": 1,
        "adapter_protocol_version": 1,
        "migration_status": "current",
        "created_tick": 0,
        "plan_hash": "c" * 64,
        "compiled_from_cgs_hash": cgs_hash,
        "all_system_ids": ["InputSystem", "MovementSystem"],
        "phases": {
            "1": {
                "phase": "Input",
                "groups": [
                    {
                        "group_id": "Input_group_0",
                        "phase": "Input",
                        "parallel": False,
                        "systems": ["InputSystem"],
                        "serialization_constraints": [],
                        "execution_index": 0,
                    }
                ],
                "total_system_count": 1,
            },
            "2": {
                "phase": "Simulation",
                "groups": [
                    {
                        "group_id": "Simulation_group_0",
                        "phase": "Simulation",
                        "parallel": False,
                        "systems": ["MovementSystem"],
                        "serialization_constraints": [],
                        "execution_index": 0,
                    }
                ],
                "total_system_count": 1,
            },
        },
    }


def _sample_cgs(cgs_hash: str) -> dict:
    return {
        "metadata": {
            "name": "SGC Contract Sample",
            "cgs_hash": cgs_hash,
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "execution_plan_version": 1,
        },
        "global_systems": [],
        "modes": [
            {
                "id": "default",
                "schema_version": "0.1.0",
                "is_default": True,
                "actors": [
                    {
                        "id": "actor_sample",
                        "components": [
                            {"type_id": 10, "name": "COMP_INPUT_SAMPLE_V1", "defaults": {}},
                            {"type_id": 11, "name": "COMP_VELOCITY_SAMPLE_V1", "defaults": {}},
                            {"type_id": 20, "name": "COMP_TRANSFORM_SAMPLE_V1", "defaults": {}},
                            {"type_id": 30, "name": "COMP_POSITION_SAMPLE_V1", "defaults": {}},
                        ],
                    }
                ],
                "systems": [
                    {
                        "id": "InputSystem",
                        "display_name": "Input System",
                        "phase": "Input",
                        "reads": [10],
                        "writes": [11],
                        "depends_on": [],
                        "deterministic": True,
                        "description": "Samples input.",
                        "version": {"major": 1, "minor": 0},
                    },
                    {
                        "id": "MovementSystem",
                        "display_name": "Movement System",
                        "phase": "Simulation",
                        "reads": [11, 20],
                        "writes": [30],
                        "depends_on": ["InputSystem"],
                        "deterministic": True,
                        "description": "Applies movement.",
                        "version": {"major": 1, "minor": 0},
                    },
                ],
                "rules": [],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
