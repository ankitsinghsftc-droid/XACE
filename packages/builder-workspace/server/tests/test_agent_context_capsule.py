import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.context_capsule import (  # noqa: E402
    AGENT_CONTEXT_CAPSULE_SCHEMA,
    CONTEXT_FILENAME,
    INSTRUCTIONS_FILENAME,
    MANIFEST_FILENAME,
    RESPONSE_SCHEMA_FILENAME,
    RETRIEVAL_INDEX_FILENAME,
    AgentContextCapsuleBuilder,
    AgentContextRetriever,
    ContextCapsuleRequest,
    ContextRetrievalRequest,
    ContextRetrievalSource,
)
from agent_host.contracts import AGENT_CONTRACT_SCHEMA, AgentSessionHandle  # noqa: E402
from agent_host.session_store import (  # noqa: E402
    AgentSessionStore,
    AgentStoredSession,
)
from secret_redaction import REDACTED_SECRET  # noqa: E402


CGS_HASH = "c" * 64
FIXED_TIME = "2026-08-31T00:00:00Z"
FAKE_SECRET = "sk-capsulesecret000000000000"
UNRELATED_MARKER = "UNRELATED_REPO_FILE_MARKER"


def _cgs() -> dict:
    return {
        "metadata": {
            "name": "Zombie Chase",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": CGS_HASH,
            "api_key": FAKE_SECRET,
        },
        "component_schemas": [
            {
                "type_id": 5,
                "name": "COMP_VELOCITY_V1",
                "fields": [{"name": "max_linear_speed"}],
            },
            {
                "type_id": 100,
                "name": "COMP_HEALTH_V1",
                "fields": [{"name": "current"}, {"name": "max"}],
            },
        ],
        "global_systems": [
            {
                "id": "InputSystem",
                "phase": "Input",
                "reads": [6],
                "writes": [5],
                "depends_on": [],
                "deterministic": True,
                "description": "Collects player movement input.",
            }
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
                                    "secret_note": FAKE_SECRET,
                                },
                            },
                            {
                                "type_id": 100,
                                "name": "COMP_HEALTH_V1",
                                "defaults": {"current": 30.0, "max": 30.0},
                            },
                        ],
                    },
                    {
                        "id": "actor_player",
                        "actor_type": "PlayerCharacter",
                        "control_type": "Human",
                        "components": [
                            {
                                "type_id": 100,
                                "name": "COMP_HEALTH_V1",
                                "defaults": {"current": 100.0, "max": 100.0},
                            }
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
                        "description": "Moves actors according to velocity.",
                    },
                    {
                        "id": "AISystem",
                        "phase": "Simulation",
                        "reads": [1, 160],
                        "writes": [5],
                        "depends_on": ["MovementSystem"],
                        "deterministic": True,
                        "description": "Makes zombies chase the player.",
                    },
                ],
                "rules": [
                    {
                        "id": "rule_player_death",
                        "condition": "current <= 0",
                        "effect": "game_over()",
                        "priority": 1,
                        "is_active": True,
                    }
                ],
            }
        ],
        "assets": {
            "items": [
                {
                    "id": "asset_zombie_mesh",
                    "asset_type": "mesh",
                    "status": "linked",
                    "path": "Assets/Characters/Zombie.glb",
                }
            ]
        },
        "semantic_bindings": {
            "zombie_walk": {
                "type": "animation",
                "target": "asset_zombie_mesh",
                "summary": "Zombie walk cycle.",
            }
        },
    }


def _request() -> ContextCapsuleRequest:
    return ContextCapsuleRequest(
        xace_session_id="session-1",
        user_prompt=f"Make the zombie faster but do not leak {FAKE_SECRET}",
        cgs=_cgs(),
        project_manifest={
            "name": "Zombie Chase",
            "version": "0.1.0",
            "engine": "godot",
            "token": FAKE_SECRET,
        },
        diagnostics=(
            {
                "severity": "warning",
                "code": "LOW_SPEED",
                "message": f"Zombie speed references {FAKE_SECRET}",
            },
        ),
        prompt_history_summaries=(
            {
                "mutation_id": "mutation-1",
                "summary": "Previously tuned player health.",
            },
        ),
        runtime_status={
            "state": "idle",
            "session": "runtime-1",
            "authorization": f"Bearer {FAKE_SECRET}",
        },
        adapter_context={
            "godot": {"status": "available", "path": "adapters/godot"},
        },
    )


def _handle() -> AgentSessionHandle:
    return AgentSessionHandle(
        xace_session_id="session-1",
        provider_id="mock",
        provider_session_id="mock-thread-session-1",
        base_cgs_hash=CGS_HASH,
        latest_cgs_hash=CGS_HASH,
        created_at=FIXED_TIME,
    )


def _capsule_text(result) -> str:
    return "\n".join(
        (result.capsule_dir / filename).read_text(encoding="utf-8")
        for filename in sorted(
            (
                CONTEXT_FILENAME,
                INSTRUCTIONS_FILENAME,
                MANIFEST_FILENAME,
                RESPONSE_SCHEMA_FILENAME,
                RETRIEVAL_INDEX_FILENAME,
            )
        )
    )


class AgentContextCapsuleTests(unittest.TestCase):
    def test_capsule_generation_is_deterministic_for_same_cgs_hash_and_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            builder = AgentContextCapsuleBuilder(temp_dir)
            request = _request()

            first = builder.build(request)
            first_text = _capsule_text(first)
            second = builder.build(request)
            second_text = _capsule_text(second)

            self.assertEqual(first.fingerprint, second.fingerprint)
            self.assertEqual(first.relative_path, second.relative_path)
            self.assertEqual(first.manifest, second.manifest)
            self.assertEqual(first.files, second.files)
            self.assertEqual(first_text, second_text)

    def test_capsule_contains_expected_snapshot_files_and_response_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = AgentContextCapsuleBuilder(temp_dir).build(_request())

            self.assertTrue(result.relative_path.startswith(".xace/agent_capsules/"))
            for filename in (
                CONTEXT_FILENAME,
                INSTRUCTIONS_FILENAME,
                MANIFEST_FILENAME,
                RESPONSE_SCHEMA_FILENAME,
                RETRIEVAL_INDEX_FILENAME,
            ):
                self.assertTrue((result.capsule_dir / filename).exists(), filename)

            context = json.loads(
                (result.capsule_dir / CONTEXT_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(context["schema"], AGENT_CONTEXT_CAPSULE_SCHEMA)
            self.assertEqual(context["cgs_hash"], CGS_HASH)
            self.assertIn("actor_zombie", context["cgs_fragments"]["catalog"]["actors"])
            self.assertIn("xace.retrieve_context", _capsule_text(result))

            response_schema = json.loads(
                (result.capsule_dir / RESPONSE_SCHEMA_FILENAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(response_schema["schema"], AGENT_CONTRACT_SCHEMA)
            self.assertEqual(
                response_schema["properties"]["schema"]["const"],
                AGENT_CONTRACT_SCHEMA,
            )
            self.assertIn("proposal_kind", response_schema["required"])

    def test_capsule_never_includes_secrets_or_unrelated_repo_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "unrelated_design_notes.txt").write_text(
                f"{UNRELATED_MARKER} {FAKE_SECRET}",
                encoding="utf-8",
            )

            result = AgentContextCapsuleBuilder(project_root).build(_request())
            text = _capsule_text(result)

            self.assertNotIn(FAKE_SECRET, text)
            self.assertNotIn(UNRELATED_MARKER, text)
            self.assertIn(REDACTED_SECRET, text)

    def test_progressive_retrieval_is_scoped_read_only_logged_and_cgs_bound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentSessionStore(temp_dir)
            store.upsert_session(AgentStoredSession.from_handle(_handle()))
            source = ContextRetrievalSource.from_request(_request())
            retriever = AgentContextRetriever(session_store=store)

            result = retriever.retrieve(
                source,
                ContextRetrievalRequest(
                    xace_session_id="session-1",
                    cgs_hash=CGS_HASH,
                    scope="cgs.actor",
                    item_id="actor_zombie",
                    provider_id="mock",
                ),
            )

            self.assertTrue(result.allowed)
            self.assertTrue(result.logged)
            self.assertTrue(result.to_dict()["read_only"])
            self.assertEqual(result.data["source_cgs_hash"], CGS_HASH)
            self.assertEqual(result.data["value"]["id"], "actor_zombie")
            self.assertNotIn(FAKE_SECRET, json.dumps(result.to_dict(), sort_keys=True))

            calls = store.list_tool_calls(
                "session-1",
                tool_name="xace.retrieve_context",
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].status, "completed")
            self.assertEqual(calls[0].permission, "read_only")
            self.assertEqual(calls[0].cgs_hash, CGS_HASH)

    def test_progressive_retrieval_denies_unsafe_or_stale_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AgentSessionStore(temp_dir)
            store.upsert_session(AgentStoredSession.from_handle(_handle()))
            source = ContextRetrievalSource.from_request(_request())
            retriever = AgentContextRetriever(session_store=store)

            unsafe = retriever.retrieve(
                source,
                ContextRetrievalRequest(
                    xace_session_id="session-1",
                    cgs_hash=CGS_HASH,
                    scope="shell",
                    query=f"print {FAKE_SECRET}",
                    provider_id="mock",
                ),
            )
            self.assertEqual(unsafe.status, "denied")
            self.assertTrue(unsafe.logged)
            self.assertNotIn(FAKE_SECRET, json.dumps(unsafe.to_dict(), sort_keys=True))

            stale = retriever.retrieve(
                source,
                ContextRetrievalRequest(
                    xace_session_id="session-1",
                    cgs_hash="d" * 64,
                    scope="cgs.actor",
                    item_id="actor_zombie",
                    provider_id="mock",
                ),
            )
            self.assertEqual(stale.status, "denied")
            self.assertIn("does not match", stale.reason)

            calls = store.list_tool_calls(
                "session-1",
                tool_name="xace.retrieve_context",
            )
            self.assertEqual([call.status for call in calls], ["denied", "denied"])


if __name__ == "__main__":
    unittest.main()
