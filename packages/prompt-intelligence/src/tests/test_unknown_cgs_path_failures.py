#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[1]
for subdir in (
    "output_parser",
    "validation_loop",
    "llm_orchestrator",
    "context_assembler",
    "intent_intake",
):
    sys.path.insert(0, str(SRC_ROOT / subdir))

from schema_path_validator import SchemaPathValidator
from structured_output_parser import StructuredOutputParser
from validation_loop import ValidationLoop


CGS = {
    "metadata": {
        "name": "Zombie Chase",
        "cgs_hash": "task26",
        "version": "0.1.0",
        "schema_version": "0.1.0",
    },
    "global_systems": [
        {
            "id": "InputSystem",
            "phase": "Simulation",
            "reads": [6],
            "writes": [5],
            "depends_on": [],
            "deterministic": True,
        },
    ],
    "modes": [
        {
            "id": "mode_default",
            "is_default": True,
            "actors": [
                {
                    "id": "actor_zombie",
                    "actor_type": "Enemy",
                    "control_type": "AiProxy",
                    "components": [
                        {
                            "type_id": 5,
                            "name": "COMP_VELOCITY_V1",
                            "defaults": {
                                "max_linear_speed": 10.0,
                                "max_angular_speed": 360.0,
                            },
                        },
                    ],
                },
            ],
            "systems": [
                {
                    "id": "MovementSystem",
                    "phase": "Simulation",
                    "reads": [5],
                    "writes": [1],
                    "depends_on": ["InputSystem"],
                    "deterministic": True,
                },
            ],
            "rules": [],
        }
    ],
}

VALID_PATH = (
    "modes[mode_default].actors[actor_zombie].components[5].defaults.max_linear_speed"
)
UNKNOWN_PATH = (
    "modes.mode_default.actors.actor_zombie.components.5.defaults.max_linear_speed"
)


def _raw_mutation(path: str) -> str:
    return json.dumps(
        {
            "schema_delta_type": "value_mutation",
            "operations": [
                {
                    "path": path,
                    "op": "SET",
                    "value": 12.0,
                    "type_hint": "float",
                    "field_name": "max_linear_speed",
                    "actor_id": "actor_zombie",
                    "type_id": 5,
                }
            ],
            "confidence": 0.91,
        }
    )


class UnknownCgsPathFailureTests(unittest.TestCase):
    def test_known_cgs_path_still_passes(self) -> None:
        result = SchemaPathValidator().validate([VALID_PATH], CGS)

        self.assertTrue(result.valid)
        self.assertEqual(result.invalid_paths, ())
        self.assertEqual(result.unknown_paths, ())

    def test_unknown_cgs_path_is_hard_failure(self) -> None:
        result = SchemaPathValidator().validate([UNKNOWN_PATH], CGS)

        self.assertFalse(result.valid)
        self.assertEqual(result.unknown_paths, (UNKNOWN_PATH,))
        self.assertIn("production mutation", " ".join(result.reasons))

    def test_structured_output_marks_unknown_path_invalid(self) -> None:
        canonical = StructuredOutputParser().parse(_raw_mutation(UNKNOWN_PATH), CGS)

        self.assertFalse(canonical.is_fully_valid)
        self.assertFalse(canonical.path_validation.valid)
        self.assertEqual(canonical.path_validation.unknown_paths, (UNKNOWN_PATH,))

    def test_validation_loop_blocks_unknown_path_before_apply(self) -> None:
        canonical = StructuredOutputParser().parse(_raw_mutation(UNKNOWN_PATH), CGS)
        result = ValidationLoop().validate(canonical, CGS)

        self.assertFalse(result.passed)
        self.assertIsNone(result.proposed_cgs)
        self.assertIn("structural", result.layer_results)
        self.assertTrue(result.layer_results["structural"].errors)
        self.assertFalse(result.layer_results["structural"].warnings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
