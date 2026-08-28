import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ASSET_REGISTRY_DIR = Path(__file__).resolve().parents[1]
if str(ASSET_REGISTRY_DIR) not in sys.path:
    sys.path.insert(0, str(ASSET_REGISTRY_DIR))

from semantic_binding_status import (  # noqa: E402
    ADAPTER_STATUS_REPORT_SCHEMA,
    SEMANTIC_BINDING_STATUS_REPORT_SCHEMA,
    build_adapter_status_reports,
    evaluate_semantic_binding_status,
)


class SemanticBindingStatusTests(unittest.TestCase):
    def test_tracks_resolved_unresolved_unsupported_missing_and_fallback_per_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            resolved_audio = _write_asset(assets / "resolved.wav", b"resolved-audio\n")
            mesh = _write_asset(assets / "mesh.glb", b"unsupported-mesh\n")
            cgs = _fixture_cgs(root, resolved_audio, mesh)

            report = evaluate_semantic_binding_status(cgs, project_root=root)

            self.assertEqual(SEMANTIC_BINDING_STATUS_REPORT_SCHEMA, report.to_dict()["schema"])
            self.assertEqual(15, len(report.records))
            for engine, counts in report.count_by_engine().items():
                self.assertEqual(
                    {
                        "resolved": 1,
                        "unresolved": 1,
                        "unsupported": 1,
                        "missing": 1,
                        "fallback": 1,
                    },
                    counts,
                    engine,
                )
            fallback = [record for record in report.records if record.status == "fallback"]
            self.assertEqual(3, len(fallback))
            self.assertTrue(all(not record.blocks_runtime and not record.blocks_handoff for record in fallback))
            unsupported = [record for record in report.records if record.status == "unsupported"]
            self.assertTrue(all("ASSET_TYPE_MISMATCH" in record.issue_codes for record in unsupported))

    def test_adapter_status_reports_are_split_by_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / "assets"
            assets.mkdir()
            resolved_audio = _write_asset(assets / "resolved.wav", b"resolved-audio\n")
            mesh = _write_asset(assets / "mesh.glb", b"unsupported-mesh\n")
            cgs = _fixture_cgs(root, resolved_audio, mesh)

            reports = build_adapter_status_reports(
                evaluate_semantic_binding_status(cgs, project_root=root)
            )

            self.assertEqual({"godot", "unity", "unreal"}, set(reports))
            for engine, report in reports.items():
                self.assertEqual(ADAPTER_STATUS_REPORT_SCHEMA, report["schema"])
                self.assertEqual(engine, report["engine"])
                self.assertEqual(5, report["record_count"])
                self.assertEqual(
                    {"resolved", "unresolved", "unsupported", "missing", "fallback"},
                    {record["status"] for record in report["records"]},
                )


def _write_asset(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def _asset_ref(asset_id: str, asset_type: str, status: str, path: Path | str = "", *, fallback=False) -> dict:
    ref = {
        "id": asset_id,
        "asset_type": asset_type,
        "status": status,
    }
    if path:
        ref["path"] = f"assets/{Path(path).name}"
        ref["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else hashlib.sha256(asset_id.encode()).hexdigest()
    if fallback:
        ref["fallback_policy"] = {"kind": "silent_audio", "reason": "optional semantic audio"}
    return ref


def _binding(binding_id: str, asset_id: str, asset_type: str, status: str) -> dict:
    return {
        "binding_id": binding_id,
        "event_name": "combat.hit_confirmed",
        "playback_kind": "Audio",
        "asset": {
            "id": asset_id,
            "asset_type": asset_type,
            "status": status,
        },
        "semantic_action": "play",
        "entity_selector": "SourceEntity",
        "parameters": {
            "xace_engine_targets": "godot,unity,unreal",
        },
        "enabled": True,
        "priority": 0,
    }


def _fixture_cgs(root: Path, resolved_audio: Path, mesh: Path) -> dict:
    del root
    assets = [
        _asset_ref("resolved_sfx", "AudioClip", "Linked", resolved_audio),
        _asset_ref("unresolved_sfx", "AudioClip", "Unresolved"),
        _asset_ref("missing_sfx", "AudioClip", "Linked", "missing.wav"),
        _asset_ref("fallback_sfx", "AudioClip", "Missing", fallback=True),
        _asset_ref("unsupported_mesh", "Mesh", "Linked", mesh),
    ]
    return {
        "metadata": {
            "name": "Semantic Binding Status Fixture",
            "version": "0.1.0",
            "schema_version": "0.1.0",
            "cgs_hash": "a" * 64,
        },
        "assets": assets,
        "global_systems": [],
        "modes": [{
            "id": "mode_default",
            "is_default": True,
            "actors": [],
            "systems": [],
            "rules": [],
        }],
        "semantic_bindings": {
            "bindings": [
                _binding("binding.resolved", "resolved_sfx", "AudioClip", "Linked"),
                _binding("binding.unresolved", "unresolved_sfx", "AudioClip", "Unresolved"),
                _binding("binding.missing", "missing_sfx", "AudioClip", "Linked"),
                _binding("binding.fallback", "fallback_sfx", "AudioClip", "Missing"),
                _binding("binding.unsupported", "unsupported_mesh", "Mesh", "Linked"),
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
