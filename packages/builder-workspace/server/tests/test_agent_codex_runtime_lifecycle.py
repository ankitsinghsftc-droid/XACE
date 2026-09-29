import hashlib
import json
import sys
import platform
import struct
from unittest.mock import patch
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from agent_host.codex_runtime_lifecycle import (  # noqa: E402
    CODEX_GUIDED_RUNTIME_SOURCE,
    CODEX_RUNTIME_LIFECYCLE_SCHEMA,
    CODEX_RUNTIME_LOCK_FILENAME,
    CODEX_RUNTIME_PENDING_FILENAME,
    CODEX_RUNTIME_STATE_FILENAME,
    CodexRuntimeLifecycle,
    CodexRuntimeLifecycleError,
    resolve_verified_codex_runtime,
)


FIXED_TIME = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


class CodexRuntimeLifecycleTests(unittest.TestCase):
    def test_guided_install_plan_uses_official_channel_without_automatic_download(self):
        lifecycle = _lifecycle(Path("unused"), platform_name="Windows")

        first = lifecycle.guided_plan("install")
        second = lifecycle.guided_plan("install")

        self.assertEqual(first, second)
        self.assertEqual(first["mode"], "guided_official_external_install")
        self.assertIn("chatgpt.com/codex/install.ps1", first["command"])
        self.assertFalse(first["automatic_download"])
        self.assertFalse(first["xace_modifies_external_runtime"])
        self.assertEqual(first["credential_owner"], "codex_provider")

    def test_verify_and_activate_records_exact_machine_local_pin(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-runtime-") as tmp:
            root = Path(tmp)
            executable = _runtime(root / "provider" / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")

            status = lifecycle.verify_and_activate(executable, operation="install", confirm_official_install=True)

            expected_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
            self.assertTrue(status["ready"])
            self.assertEqual(status["active"]["version"], "0.143.0")
            self.assertEqual(status["active"]["sha256"], expected_digest)
            self.assertEqual(status["active"]["source"], CODEX_GUIDED_RUNTIME_SOURCE)
            self.assertEqual(status["active"]["platform"], lifecycle._platform)
            self.assertEqual(status["active"]["architecture"], lifecycle._architecture)
            self.assertFalse(status["active"]["xace_copied_runtime"])
            self.assertTrue((root / "state" / CODEX_RUNTIME_STATE_FILENAME).exists())

            resolved = resolve_verified_codex_runtime(root / "state")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved["executable_path"], str(executable.resolve()))

    def test_update_retains_last_known_good_and_rollback_reverifies_it(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-update-") as tmp:
            root = Path(tmp)
            old = _runtime(root / "provider-143" / "codex.exe", "0.143.0")
            new = _runtime(root / "provider-144" / "codex.exe", "0.144.0")
            lifecycle = _lifecycle(root / "state")

            lifecycle.verify_and_activate(old, operation="install", confirm_official_install=True)
            updated = lifecycle.verify_and_activate(new, operation="update", confirm_official_install=True)

            self.assertEqual(updated["active"]["version"], "0.144.0")
            self.assertEqual(updated["last_known_good"]["version"], "0.143.0")

            rolled_back = lifecycle.rollback()
            self.assertEqual(rolled_back["active"]["version"], "0.143.0")
            self.assertEqual(rolled_back["active_health"]["code"], "verified_active")
            self.assertEqual(rolled_back["history_count"], 3)

    def test_failed_repair_leaves_active_state_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-repair-") as tmp:
            root = Path(tmp)
            executable = _runtime(root / "provider" / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")
            installed = lifecycle.verify_and_activate(executable, operation="install", confirm_official_install=True)
            original_generation = installed["generation"]
            original_digest = installed["active"]["sha256"]

            with self.assertRaisesRegex(CodexRuntimeLifecycleError, "SHA-256 mismatch"):
                lifecycle.verify_and_activate(
                    executable,
                    operation="repair", confirm_official_install=True,
                    expected_sha256="0" * 64,
                )

            after = lifecycle.inspect()
            self.assertEqual(after["generation"], original_generation)
            self.assertEqual(after["active"]["sha256"], original_digest)
            self.assertFalse(after["pending_operation"])

    def test_deactivate_never_deletes_provider_runtime(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-remove-") as tmp:
            root = Path(tmp)
            executable = _runtime(root / "provider" / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")
            lifecycle.verify_and_activate(executable, operation="install", confirm_official_install=True)

            removed = lifecycle.deactivate()

            self.assertTrue(executable.exists())
            self.assertIsNone(removed["active"])
            self.assertFalse(removed["ready"])
            self.assertEqual(removed["active_health"]["code"], "not_active")

    def test_interrupted_operation_recovery_preserves_last_atomic_state(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-recovery-") as tmp:
            root = Path(tmp)
            executable = _runtime(root / "provider" / "codex.exe", "0.143.0")
            state_dir = root / "state"
            lifecycle = _lifecycle(state_dir)
            installed = lifecycle.verify_and_activate(executable, operation="install", confirm_official_install=True)
            generation = installed["generation"]
            (state_dir / CODEX_RUNTIME_PENDING_FILENAME).write_text(
                json.dumps({"operation": "update"}),
                encoding="utf-8",
            )
            (state_dir / CODEX_RUNTIME_LOCK_FILENAME).write_text(
                "stale",
                encoding="utf-8",
            )

            recovered = lifecycle.recover_interrupted()

            self.assertTrue(recovered["recovery"]["recovered"])
            self.assertTrue(recovered["recovery"]["active_state_preserved"])
            self.assertEqual(recovered["generation"], generation)
            self.assertTrue(recovered["ready"])
            self.assertFalse((state_dir / CODEX_RUNTIME_PENDING_FILENAME).exists())
            self.assertTrue((state_dir / CODEX_RUNTIME_LOCK_FILENAME).exists())

    def test_modified_active_executable_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-tamper-") as tmp:
            root = Path(tmp)
            executable = _runtime(root / "provider" / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")
            lifecycle.verify_and_activate(executable, operation="install", confirm_official_install=True)

            executable.write_text("0.143.0-tampered", encoding="utf-8")

            status = lifecycle.inspect()
            self.assertFalse(status["ready"])
            self.assertEqual(status["active_health"]["code"], "digest_mismatch")
            self.assertIsNone(resolve_verified_codex_runtime(root / "state"))

    def test_prerelease_and_private_extension_candidates_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-reject-") as tmp:
            root = Path(tmp)
            prerelease = _runtime(root / "provider" / "codex.exe", "0.145.0-alpha.1")
            extension = _runtime(
                root / ".vscode" / "extensions" / "openai.chatgpt-1" / "codex.exe",
                "0.143.0",
            )
            lifecycle = _lifecycle(root / "state")

            with self.assertRaisesRegex(CodexRuntimeLifecycleError, "Prerelease"):
                lifecycle.verify_candidate(prerelease)
            with self.assertRaisesRegex(CodexRuntimeLifecycleError, "private editor-extension"):
                lifecycle.verify_candidate(extension)

    def test_corrupt_state_is_reported_and_never_resolved(self):
        with tempfile.TemporaryDirectory(prefix="xace-codex-corrupt-") as tmp:
            state_dir = Path(tmp) / "state"
            state_dir.mkdir(parents=True)
            (state_dir / CODEX_RUNTIME_STATE_FILENAME).write_text(
                "{not-json",
                encoding="utf-8",
            )
            lifecycle = _lifecycle(state_dir)

            status = lifecycle.inspect()

            self.assertEqual(status["schema"], CODEX_RUNTIME_LIFECYCLE_SCHEMA)
            self.assertFalse(status["ready"])
            self.assertIn("unreadable", status["state_error"])
            self.assertIsNone(resolve_verified_codex_runtime(state_dir))

    def test_confirmation_is_required_before_executing(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = _lifecycle(Path(tmp))
            with patch.object(lifecycle, "_version_reader") as reader:
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "Confirm"):
                    lifecycle.verify_and_activate("not-installed")
                reader.assert_not_called()

    def test_digest_and_native_header_checked_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = _runtime(root / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")
            with patch.object(lifecycle, "_version_reader") as reader:
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "SHA-256"):
                    lifecycle.verify_candidate(executable, expected_sha256="0" * 64)
                reader.assert_not_called()
                executable.write_bytes(b"shell wrapper")
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "platform"):
                    lifecycle.verify_candidate(executable)
                reader.assert_not_called()

    def test_recovery_cannot_steal_live_operation_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = _lifecycle(Path(tmp))
            other = _lifecycle(Path(tmp))
            with lifecycle._operation_lock("install", Path(tmp)):
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "already in progress"):
                    other.recover_interrupted()

    def test_schema_changes_prevent_repair_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = _runtime(root / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")
            lifecycle.verify_and_activate(executable, confirm_official_install=True)
            original = lifecycle.state_path.read_bytes()
            changed = _schema()
            changed["ClientRequest.json"]["description"] = "changed"
            with patch.object(lifecycle, "_schema_probe", return_value=changed):
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "schema mismatch"):
                    lifecycle.rollback()
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "schema mismatch"):
                    lifecycle.verify_and_activate(executable, operation="repair", confirm_official_install=True)
            self.assertEqual(lifecycle.state_path.read_bytes(), original)

    def test_failed_atomic_activation_keeps_prior_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = _runtime(root / "old.exe", "0.143.0")
            new = _runtime(root / "new.exe", "0.144.0")
            lifecycle = _lifecycle(root / "state")
            lifecycle.verify_and_activate(old, confirm_official_install=True)
            original = lifecycle.state_path.read_bytes()
            with patch.object(lifecycle, "_write_state", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    lifecycle.verify_and_activate(new, operation="update", confirm_official_install=True)
            self.assertEqual(lifecycle.state_path.read_bytes(), original)

    def test_removed_selection_does_not_rediscover_path(self):
        from agent_host.codex_adapter import resolve_codex_executable
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = _lifecycle(Path(tmp))
            lifecycle.deactivate()
            with patch.dict("os.environ", {"XACE_CODEX_RUNTIME_DIR": tmp,
                            "XACE_CODEX_APP_SERVER_BIN": "", "XACE_CODEX_EXECUTABLE": ""}):
                with patch("agent_host.codex_adapter.shutil.which", return_value="unexpected") as which:
                    self.assertIsNone(resolve_codex_executable())
                    which.assert_not_called()

    def test_revocation_blocks_resolution_and_activation(self):
        from agent_host.codex_distribution import codex_distribution_policy
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = _runtime(root / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")
            lifecycle.verify_and_activate(executable, confirm_official_install=True)
            policy = codex_distribution_policy()
            policy["revocation"]["revoked_versions"] = ["0.143.0"]
            with patch("agent_host.codex_distribution.codex_distribution_policy", return_value=policy):
                self.assertEqual(lifecycle.inspect()["active_health"]["code"], "runtime_revoked")
                self.assertIsNone(resolve_verified_codex_runtime(root / "state"))
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "revoked"):
                    lifecycle.verify_candidate(executable)

    def test_missing_schema_methods_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = _runtime(root / "codex.exe", "0.143.0")
            lifecycle = _lifecycle(root / "state")
            with patch.object(lifecycle, "_schema_probe", return_value={"empty.json": {}}):
                with self.assertRaisesRegex(CodexRuntimeLifecycleError, "schema incompatible"):
                    lifecycle.verify_candidate(executable)

    def test_cli_guide_and_inspect_do_not_install_or_create_state(self):
        import contextlib
        import io
        tools_dir = SERVER_DIR.parents[2] / "tools"
        with patch.object(sys, "path", [str(tools_dir), *sys.path]):
            from codex_runtime import main
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "unused"
            for command in ("guide", "inspect"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(["--state-dir", str(root), command]), 0)
                self.assertFalse(json.loads(output.getvalue())["automatic_download"])
            self.assertFalse(root.exists())


def _schema():
    from codex_schema_fixture import schema_fixture
    return schema_fixture()


def _runtime(path: Path, version: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(128)
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if sys.platform == "win32":
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 60, 64)
        header[64:68] = b"PE\0\0"
        struct.pack_into("<H", header, 68, 0xAA64 if arm else 0x8664)
    elif sys.platform == "darwin":
        header[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<I", header, 4, 0x100000C if arm else 0x1000007)
    else:
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", header, 18, 183 if arm else 62)
    path.write_bytes(bytes(header) + version.encode())
    return path


def _lifecycle(
    state_dir: Path,
    *,
    platform_name: str | None = None,
) -> CodexRuntimeLifecycle:
    return CodexRuntimeLifecycle(
        state_dir,
        version_reader=lambda path: f"codex {Path(path).read_bytes()[128:].decode()}",
        schema_probe=lambda _path: _schema(),
        clock=lambda: FIXED_TIME,
        platform_name=platform_name,
        architecture=platform.machine(),
    )


if __name__ == "__main__":
    unittest.main()
