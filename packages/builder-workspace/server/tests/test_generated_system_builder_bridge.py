"""Focused Builder handoff coverage for X10-031 generated systems."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import session_manager as session_module  # noqa: E402


def _materialized_batch() -> dict:
    return {
        "schema": "xace.typed_cgs_operation_batch.v1",
        "request_id": "request.builder.generated",
        "prompt_id": "prompt.builder.generated",
        "summary": "Add a locally compiled counter system.",
        "operations": [
            {
                "operation_id": "system.generated.counter",
                "kind": "add_generated_system",
                "explanation": "Increment the fixed counter every tick.",
                "system_id": "GeneratedCounterSystem",
                "phase": "Simulation",
                "reads": [10000],
                "writes": [10000],
                "depends_on": [],
                "behavior": {
                    "kind": "increment_numeric_field",
                    "component_type_id": 10000,
                    "field": "count",
                    "amount": 1,
                },
                "scope": "global",
                "mode_id": "",
                "version": "1.0.0",
                "deterministic": True,
                "parallel": False,
                "runtime_executor": {
                    "kind": "generated.increment_numeric_field",
                    "component_type_id": 10000,
                    "field": "count",
                    "amount": 1,
                    "abi": {},
                    "compile_artifact": {},
                },
            }
        ],
    }


class GeneratedSystemBuilderBridgeTests(unittest.TestCase):
    def test_server_retained_materialized_batch_reaches_gde_boundary(self) -> None:
        transaction = {
            "operation_format": "typed_cgs_v1",
            "typed_operation_batch": _materialized_batch(),
            "operations": [],
        }

        self.assertEqual(
            session_module._pending_transaction_block_reason(transaction),
            "",
        )

    def test_generated_system_is_visible_in_preview_and_serialization(self) -> None:
        batch = _materialized_batch()
        operations = batch["operations"]
        preview = session_module._preview_system_diff(
            {"affected_systems": ["GeneratedCounterSystem"]},
            operations,
        )
        self.assertEqual(preview["added_systems"], ["GeneratedCounterSystem"])
        self.assertEqual(preview["touched_systems"], ["GeneratedCounterSystem"])

        result = SimpleNamespace(
            kind="mutation",
            turn_index=1,
            intent_category="MutationRequest",
            confidence=1.0,
            mode_profile_warnings=[],
            auto_committed=False,
            diff_text="generated diff",
            typed_mutation=SimpleNamespace(
                normalized_batch=batch,
                parser_confidence=1.0,
            ),
        )
        serialized = session_module._serialize_pil_result(result)
        self.assertEqual(
            serialized["transaction"]["affected_systems"],
            ["GeneratedCounterSystem"],
        )


if __name__ == "__main__":
    unittest.main()
