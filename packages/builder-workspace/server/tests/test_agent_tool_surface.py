import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.context_capsule import ContextRetrievalSource  # noqa: E402
from agent_host.contracts import (  # noqa: E402
    AgentEventType,
    AgentSessionHandle,
    AgentToolPermission,
    ToolTransport,
)
from agent_host.session_store import AgentSessionStore, AgentStoredSession  # noqa: E402
from agent_host.tool_surface import (  # noqa: E402
    AGENT_TOOL_SURFACE_SCHEMA,
    DENIED_XACE_TOOL_NAMES,
    READ_ONLY_XACE_TOOL_NAMES,
    TOOL_GET_DIAGNOSTICS,
    TOOL_READ_CGS,
    TOOL_RETRIEVE_CONTEXT,
    TOOL_RUNTIME_SNAPSHOT,
    TOOL_RUNTIME_STATUS,
    TOOL_SEARCH_PROJECT,
    XaceToolCallRequest,
    XaceToolSurface,
    default_xace_tool_specs,
    tool_names_from_specs,
)


CGS_HASH = "e" * 64
STALE_CGS_HASH = "f" * 64
FIXED_TIME = "2026-08-31T00:00:00Z"
FAKE_SECRET = "sk-toolsurfacesecret000000000000"


class FakeRuntimeControl:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def status(self, *, session_id: str = "") -> dict:
        self.calls.append(("status", session_id))
        return {
            "accepted": True,
            "reason": "",
            "status": {
                "engine_connected": True,
                "tick": 7,
                "latest_world_hash": "1" * 64,
            },
        }

    def send_control(
        self,
        action: str,
        *,
        session_id: str = "",
        tick: int | None = None,
        version_ids: dict | None = None,
    ) -> dict:
        self.calls.append((action, session_id, tick, version_ids))
        if action != "snapshot":
            return {"accepted": False, "reason": "unsupported action", "status": {}}
        return {
            "accepted": True,
            "reason": "",
            "status": {"engine_connected": True, "tick": tick or 0},
            "snapshot": {
                "tick": tick or 0,
                "world_hash": "2" * 64,
                "entities": [],
            },
        }


def _cgs() -> dict:
    return {
        "metadata": {
            "name": "Zombie Chase",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": CGS_HASH,
            "api_key": FAKE_SECRET,
        },
        "global_systems": [
            {
                "id": "InputSystem",
                "phase": "Input",
                "reads": [6],
                "writes": [5],
                "depends_on": [],
                "deterministic": True,
                "description": "Collects movement input.",
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
                            }
                        ],
                    },
                    {
                        "id": "actor_player",
                        "actor_type": "PlayerCharacter",
                        "control_type": "Human",
                        "components": [],
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
                        "description": "Moves zombies and players.",
                    }
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


def _source() -> ContextRetrievalSource:
    return ContextRetrievalSource(
        cgs=_cgs(),
        cgs_hash=CGS_HASH,
        project_manifest={"name": "Zombie Chase", "engine": "godot"},
        diagnostics=(
            {
                "severity": "warning",
                "code": "ZOMBIE_SPEED_LOW",
                "message": "Zombie speed is below recommended range.",
            },
        ),
        runtime_status={"state": "idle"},
        adapter_context={"godot": {"status": "available"}},
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


def _store(temp_dir: str) -> AgentSessionStore:
    store = AgentSessionStore(temp_dir)
    store.upsert_session(AgentStoredSession.from_handle(_handle()))
    return store


def _request(tool_name: str, arguments: dict | None = None, cgs_hash: str = CGS_HASH):
    return XaceToolCallRequest(
        tool_name=tool_name,
        xace_session_id="session-1",
        provider_id="mock",
        cgs_hash=cgs_hash,
        arguments=arguments or {},
    )


class AgentToolSurfaceTests(unittest.TestCase):
    def test_default_tool_specs_are_stable_mcp_read_only_contracts(self):
        specs = default_xace_tool_specs()

        self.assertEqual(tool_names_from_specs(specs), READ_ONLY_XACE_TOOL_NAMES)
        self.assertNotIn("xace.shell", tool_names_from_specs(specs))
        self.assertIn("xace.shell", DENIED_XACE_TOOL_NAMES)

        for spec in specs:
            self.assertEqual(spec.permission, AgentToolPermission.READ_ONLY)
            self.assertEqual(spec.transport, ToolTransport.MCP)
            self.assertTrue(spec.read_only)
            self.assertEqual(spec.input_schema["type"], "object")
            self.assertFalse(spec.input_schema.get("additionalProperties", True))
            json.dumps(spec.to_dict(), sort_keys=True)

        self.assertEqual(AGENT_TOOL_SURFACE_SCHEMA, "xace.agent_tool_surface.v1")

    def test_read_context_search_and_diagnostics_execute_and_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            surface = XaceToolSurface(_source(), session_store=store)

            summary = surface.execute(_request(TOOL_READ_CGS))
            actor = surface.execute(
                _request(
                    TOOL_RETRIEVE_CONTEXT,
                    {"scope": "cgs.actor", "item_id": "actor_zombie"},
                )
            )
            search = surface.execute(
                _request(TOOL_SEARCH_PROJECT, {"query": "zombie movement"})
            )
            diagnostics = surface.execute(_request(TOOL_GET_DIAGNOSTICS))

            self.assertTrue(summary.allowed)
            self.assertEqual(
                summary.data["value"]["catalog"]["actors"],
                ["actor_player", "actor_zombie"],
            )
            self.assertEqual(actor.data["value"]["id"], "actor_zombie")
            self.assertTrue(search.data["items"])
            self.assertEqual(
                diagnostics.data["items"][0]["code"],
                "ZOMBIE_SPEED_LOW",
            )

            calls = store.list_tool_calls("session-1")
            self.assertEqual(
                [call.tool_name for call in calls],
                [
                    TOOL_READ_CGS,
                    TOOL_RETRIEVE_CONTEXT,
                    TOOL_SEARCH_PROJECT,
                    TOOL_GET_DIAGNOSTICS,
                ],
            )
            self.assertTrue(all(call.permission == "read_only" for call in calls))
            self.assertTrue(all(call.transport == "mcp" for call in calls))

            events = store.list_events(
                "session-1",
                event_type=AgentEventType.TOOL_CALL.value,
            )
            self.assertEqual(len(events), 4)
            self.assertTrue(all(event.data["status"] == "completed" for event in events))

    def test_runtime_status_and_snapshot_use_read_only_runtime_control(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = FakeRuntimeControl()
            surface = XaceToolSurface(
                _source(),
                session_store=_store(temp_dir),
                runtime_control=runtime,
            )

            status = surface.execute(_request(TOOL_RUNTIME_STATUS))
            snapshot = surface.execute(_request(TOOL_RUNTIME_SNAPSHOT, {"tick": 9}))

            self.assertTrue(status.allowed)
            self.assertEqual(status.data["status"]["tick"], 7)
            self.assertTrue(snapshot.allowed)
            self.assertEqual(snapshot.data["snapshot"]["tick"], 9)
            self.assertEqual(
                runtime.calls,
                [("status", "session-1"), ("snapshot", "session-1", 9, None)],
            )

    def test_runtime_unavailable_is_structured_and_logged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            surface = XaceToolSurface(_source(), session_store=store)

            result = surface.execute(_request(TOOL_RUNTIME_STATUS))

            self.assertEqual(result.status, "unavailable")
            self.assertIn("runtime control client", result.reason)
            self.assertTrue(result.logged)
            self.assertEqual(store.list_tool_calls("session-1")[0].status, "unavailable")

    def test_denies_unknown_shell_and_stale_cgs_with_structured_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store(temp_dir)
            surface = XaceToolSurface(_source(), session_store=store)

            shell = surface.execute(
                _request(
                    "xace.shell",
                    {"command": f"echo {FAKE_SECRET}"},
                )
            )
            stale = surface.execute(
                _request(
                    TOOL_READ_CGS,
                    {"scope": "summary"},
                    cgs_hash=STALE_CGS_HASH,
                )
            )

            self.assertEqual(shell.status, "denied")
            self.assertEqual(stale.status, "denied")
            self.assertTrue(shell.logged)
            self.assertTrue(stale.logged)
            encoded = json.dumps(
                {"shell": shell.to_dict(), "stale": stale.to_dict()},
                sort_keys=True,
            )
            self.assertNotIn(FAKE_SECRET, encoded)

            events = store.list_events(
                "session-1",
                event_type=AgentEventType.TOOL_CALL.value,
            )
            self.assertEqual([event.data["denied"] for event in events], [True, True])
            self.assertIn("not allowlisted", events[0].data["reason"])


if __name__ == "__main__":
    unittest.main()
