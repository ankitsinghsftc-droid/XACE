import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import credential_store  # noqa: E402
from credential_store import (  # noqa: E402
    CredentialStoreError,
    LinuxSecretServiceBackend,
    MacOSKeychainBackend,
    UnsafeFileCredentialBackend,
    credential_ref,
)
from provider_settings import ProviderSettingsStore  # noqa: E402


class CredentialStoreTests(unittest.TestCase):
    def test_provider_settings_persists_reference_not_api_key(self):
        with tempfile.TemporaryDirectory(prefix="xace-credential-settings-") as tmp:
            settings_path = Path(tmp) / "provider_settings.json"
            credential_path = Path(tmp) / "unsafe_credentials.json"
            backend = UnsafeFileCredentialBackend(credential_path)

            store = ProviderSettingsStore(settings_path, credential_store=backend)
            api_key = "sk-" + "test-secret"
            store.configure(provider="openai", model="gpt-test", api_key=api_key)

            raw = settings_path.read_text(encoding="utf-8")
            self.assertNotIn(api_key, raw)
            payload = json.loads(raw)
            entry = payload["providers"]["openai"]
            self.assertEqual(entry["credential_ref"], credential_ref("openai"))
            self.assertEqual(store.secret_for("openai"), api_key)

    def test_clear_key_removes_credential_reference(self):
        with tempfile.TemporaryDirectory(prefix="xace-credential-clear-") as tmp:
            settings_path = Path(tmp) / "provider_settings.json"
            backend = UnsafeFileCredentialBackend(Path(tmp) / "unsafe_credentials.json")
            store = ProviderSettingsStore(settings_path, credential_store=backend)
            store.configure(provider="anthropic", model="claude-test", api_key="sk-ant-" + "test")

            store.configure(provider="anthropic", api_key="", clear_key=True)

            self.assertEqual(store.secret_for("anthropic"), "")
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            entry = payload["providers"]["anthropic"]
            self.assertNotIn("credential_ref", entry)
            self.assertNotIn("secret", entry)

    def test_clear_key_without_api_key_field_removes_credential_reference(self):
        with tempfile.TemporaryDirectory(prefix="xace-credential-clear-none-") as tmp:
            settings_path = Path(tmp) / "provider_settings.json"
            backend = UnsafeFileCredentialBackend(Path(tmp) / "unsafe_credentials.json")
            store = ProviderSettingsStore(settings_path, credential_store=backend)
            store.configure(provider="google", model="gemini-test", api_key="AIza-test")

            store.configure(provider="google", clear_key=True)

            self.assertEqual(store.secret_for("google"), "")
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertNotIn("credential_ref", payload["providers"]["google"])

    def test_unsafe_file_backend_requires_explicit_env_when_selected(self):
        with mock.patch.dict(os.environ, {credential_store.BACKEND_ENV: "unsafe-file"}, clear=True):
            with self.assertRaises(CredentialStoreError):
                credential_store.create_credential_store()

        with tempfile.TemporaryDirectory(prefix="xace-credential-env-") as tmp:
            with mock.patch.dict(os.environ, {
                credential_store.BACKEND_ENV: "unsafe-file",
                credential_store.UNSAFE_FALLBACK_ENV: "1",
                credential_store.UNSAFE_STORE_PATH_ENV: str(Path(tmp) / "unsafe.json"),
            }, clear=True):
                backend = credential_store.create_credential_store()
                self.assertTrue(backend.unsafe)

    def test_macos_keychain_uses_security_command(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return _Completed(stdout="secret-value\n")

        with mock.patch.object(credential_store.sys, "platform", "darwin"):
            with mock.patch.object(credential_store.shutil, "which", return_value="/usr/bin/security"):
                with mock.patch.object(credential_store.subprocess, "run", side_effect=fake_run):
                    backend = MacOSKeychainBackend()
                    backend.set_secret("xace.provider.openai.api_key", "secret-value")
                    self.assertEqual(backend.get_secret("xace.provider.openai.api_key"), "secret-value")
                    backend.delete_secret("xace.provider.openai.api_key")

        self.assertEqual(calls[0][:2], ["security", "add-generic-password"])
        self.assertEqual(calls[1][:2], ["security", "find-generic-password"])
        self.assertEqual(calls[2][:2], ["security", "delete-generic-password"])

    def test_linux_secret_service_uses_secret_tool_or_requires_explicit_fallback(self):
        with mock.patch.object(credential_store.sys, "platform", "linux"):
            with mock.patch.object(credential_store.shutil, "which", return_value=None):
                with self.assertRaises(CredentialStoreError):
                    LinuxSecretServiceBackend(allow_unsafe_fallback=False)
                backend = LinuxSecretServiceBackend(allow_unsafe_fallback=True)
                self.assertTrue(backend.unsafe)

    def test_windows_backend_uses_credential_manager_api(self):
        fake_advapi = mock.Mock()
        fake_advapi.CredWriteW.return_value = 1
        fake_advapi.CredDeleteW.return_value = 1

        with mock.patch.object(credential_store.sys, "platform", "win32"):
            with mock.patch.object(credential_store.ctypes, "WinDLL", return_value=fake_advapi, create=True):
                backend = credential_store.WindowsCredentialManagerBackend()
                backend.set_secret("xace.provider.openai.api_key", "sk-win")
                backend.delete_secret("xace.provider.openai.api_key")

        self.assertTrue(fake_advapi.CredWriteW.called)
        self.assertTrue(fake_advapi.CredDeleteW.called)


class _Completed:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


if __name__ == "__main__":
    unittest.main()
