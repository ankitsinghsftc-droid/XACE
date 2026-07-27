import json
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
PACKAGES_DIR = SERVER_DIR.parents[1]
REPO_ROOT = PACKAGES_DIR.parent
TOOLS_DIR = REPO_ROOT / "tools"
for path in (SERVER_DIR, PACKAGES_DIR, TOOLS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from credential_store import UnsafeFileCredentialBackend  # noqa: E402
from provider_settings import ProviderSettingsStore  # noqa: E402
from secret_redaction import REDACTED_SECRET, redact_text, redact_value  # noqa: E402
from security_secret_scan import scan_paths  # noqa: E402
from inference.src.telemetry_pipeline import (  # noqa: E402
    FileBackend,
    InferenceTelemetryEvent,
    TelemetryPipeline,
)


class SecretRedactionAndScanTests(unittest.TestCase):
    def test_redactor_removes_common_api_key_shapes(self):
        fake_openai_key = "sk-" + "xace-redaction-openai-secret-123"
        fake_anthropic_key = "sk-ant-" + "xace-redaction-anthropic-secret-456"
        fake_google_key = "AIza" + "XaceRedactionGoogleSecret123456789"

        payload = {
            "api_key": fake_openai_key,
            "headers": {
                "Authorization": f"Bearer {fake_anthropic_key}",
                "x-api-key": fake_google_key,
            },
            "message": f"provider echoed {fake_openai_key}",
        }

        redacted = redact_value(payload)
        serialized = json.dumps(redacted, sort_keys=True)

        self.assertNotIn(fake_openai_key, serialized)
        self.assertNotIn(fake_anthropic_key, serialized)
        self.assertNotIn(fake_google_key, serialized)
        self.assertIn(REDACTED_SECRET, serialized)

    def test_secret_scanner_detects_raw_leak_and_accepts_redacted_artifacts(self):
        fake_key = "sk-" + "xace-artifact-secret-leak-123"
        with tempfile.TemporaryDirectory(prefix="xace-secret-scan-") as tmp:
            root = Path(tmp)
            leak_file = root / "leak.log"
            leak_file.write_text(f"Authorization: Bearer {fake_key}\n", encoding="utf-8")

            leak_findings = scan_paths([leak_file], repo_root=root)
            self.assertGreaterEqual(len(leak_findings), 1)
            self.assertIn("bearer_token", {finding.kind for finding in leak_findings})

            project = root / "project"
            _write_redacted_project_artifacts(project, fake_key)
            clean_findings = scan_paths([project], repo_root=project)

            self.assertEqual([], clean_findings)

    def test_provider_settings_and_telemetry_do_not_persist_fake_keys(self):
        fake_key = "sk-" + "xace-provider-settings-artifact-secret"
        with tempfile.TemporaryDirectory(prefix="xace-provider-secret-scan-") as tmp:
            root = Path(tmp)
            settings_path = root / "provider_settings.json"
            backend = UnsafeFileCredentialBackend(root / "unsafe_credentials.json")
            store = ProviderSettingsStore(settings_path, credential_store=backend)

            store.configure(provider="openai", model="xace-test-model", api_key=fake_key)
            store._record_test("openai", {
                "ok": False,
                "provider": "openai",
                "model": "xace-test-model",
                "base_url": "https://api.openai.com/v1",
                "key_fingerprint": "test-fingerprint",
                "checks": {},
                "message": f"provider error included {fake_key}",
                "latency_ms": 1,
            })

            telemetry_path = root / "telemetry.jsonl"
            telemetry = TelemetryPipeline()
            telemetry.add_backend(FileBackend(str(telemetry_path)))
            telemetry.emit(InferenceTelemetryEvent(
                request_id="redaction-test",
                session_id="secret-scan",
                call_label=f"provider failed {fake_key}",
                provider="openai",
                model_id="xace-test-model",
                outcome=f"transport_error {fake_key}",
            ))

            settings_text = settings_path.read_text(encoding="utf-8")
            telemetry_text = telemetry_path.read_text(encoding="utf-8")
            self.assertNotIn(fake_key, settings_text)
            self.assertNotIn(fake_key, telemetry_text)
            self.assertIn(REDACTED_SECRET, settings_text)
            self.assertIn(REDACTED_SECRET, telemetry_text)
            self.assertEqual([], scan_paths([settings_path, telemetry_path], repo_root=root))


def _write_redacted_project_artifacts(project: Path, fake_key: str) -> None:
    artifact_payload = redact_value({
        "metadata": {"cgs_hash": "0" * 64},
        "provider": {"api_key": fake_key},
        "message": f"raw provider failure {fake_key}",
    })
    files = [
        project / "game.cgs.json",
        project / ".xace" / "snapshots" / "snapshot_1.json",
        project / ".xace" / "exports" / "godot" / "manifest.json",
        project / ".xace" / "logs" / "builder.log",
        project / ".xace" / "crash_reports" / "crash_1.json",
        project / ".xace" / "telemetry" / "inference.jsonl",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".log":
            path.write_text(redact_text(f"provider log had {fake_key}\n"), encoding="utf-8")
        else:
            path.write_text(json.dumps(artifact_payload, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
