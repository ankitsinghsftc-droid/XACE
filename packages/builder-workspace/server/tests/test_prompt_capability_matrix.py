import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parents[2]
PROMPT_FIXTURE_DIR = SERVER_DIR / "tests" / "fixtures"
for path in (SERVER_DIR, PROMPT_FIXTURE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from builder_server import create_app  # noqa: E402
from prompt_capability_matrix import (  # noqa: E402
    REQUIRED_CATEGORY_IDS,
    load_prompt_capability_matrix,
    prompt_capability_matrix_hash,
)
from prompt_pipeline_contract import (  # noqa: E402
    blocked_prompt_pipeline_scenario,
    supported_prompt_pipeline_scenarios,
)


class PromptCapabilityMatrixTests(unittest.TestCase):
    def test_matrix_declares_required_task35_categories(self):
        matrix = load_prompt_capability_matrix()

        self.assertEqual(matrix["schema"], "xace.prompt_capability_matrix.v1")
        self.assertEqual(matrix["category_order"], list(REQUIRED_CATEGORY_IDS))
        self.assertEqual([category["id"] for category in matrix["categories"]], list(REQUIRED_CATEGORY_IDS))
        self.assertEqual(matrix["matrix_hash"], prompt_capability_matrix_hash(matrix))

        for category in matrix["categories"]:
            self.assertTrue(category["product_wording"].strip(), category["id"])
            self.assertTrue(category["builder_copy"].strip(), category["id"])
            self.assertGreaterEqual(len(category["examples"]), 2, category["id"])

    def test_certified_examples_cover_prompt_contract_scenarios(self):
        matrix = load_prompt_capability_matrix()
        certified = _category(matrix, "certified_supported")
        blocked = _category(matrix, "blocked")
        certified_prompts = {example["prompt"] for example in certified["examples"]}
        blocked_prompts = {example["prompt"] for example in blocked["examples"]}

        for scenario in supported_prompt_pipeline_scenarios():
            self.assertIn(scenario.prompt, certified_prompts, scenario.scenario_id)
        self.assertIn(blocked_prompt_pipeline_scenario().prompt, blocked_prompts)

    def test_builder_endpoint_returns_docs_matrix(self):
        from fastapi.testclient import TestClient  # noqa: PLC0415

        matrix = load_prompt_capability_matrix()
        with tempfile.TemporaryDirectory(prefix="xace-prompt-matrix-api-") as tmp:
            root = Path(tmp)
            app = create_app(
                project_path=str(root / "project"),
                static_dir=str(root / "missing-dist"),
                model_provider="auto",
            )
            client = TestClient(app)
            response = client.get("/api/prompt/capability-matrix")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["matrix_hash"], matrix["matrix_hash"])
        self.assertEqual(payload["source_of_truth"], "docs/prompt_capability_matrix.json")
        self.assertEqual(json.dumps(payload["categories"], sort_keys=True), json.dumps(matrix["categories"], sort_keys=True))


def _category(matrix: dict, category_id: str) -> dict:
    for category in matrix["categories"]:
        if category["id"] == category_id:
            return category
    raise AssertionError(f"missing category {category_id}")


if __name__ == "__main__":
    unittest.main()
