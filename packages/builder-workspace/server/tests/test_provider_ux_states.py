import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from credential_store import UnsafeFileCredentialBackend  # noqa: E402
from provider_settings import (  # noqa: E402
    PROVIDER_UX_INVALID_KEY,
    PROVIDER_UX_NO_KEY,
    PROVIDER_UX_PROVIDER_OUTAGE,
    PROVIDER_UX_QUOTA_FAILURE,
    PROVIDER_UX_RATE_LIMIT,
    PROVIDER_UX_STALE_HEALTH_PROOF,
    ProviderSettingsStore,
    _classify_provider_failure,
    _fingerprint,
    _provider_config_hash,
    _provider_ux_state,
)


PROVIDER = "openai"
MODEL = "xace-provider-ux-model"
ALT_MODEL = "xace-provider-ux-model-rotated"
BASE_URL = "https://api.openai.com/v1"
KEY = "xace-provider-ux-key"


class ProviderUxStateTests(unittest.TestCase):
    def test_required_builder_states_are_returned_by_readiness(self):
        with tempfile.TemporaryDirectory(prefix="xace-provider-ux-") as tmp:
            root = Path(tmp)
            store = ProviderSettingsStore(
                root / "provider_settings.json",
                credential_store=UnsafeFileCredentialBackend(root / "unsafe_credentials.json"),
            )

            store.configure(provider=PROVIDER, model=MODEL, api_key="")
            self._assert_state(store.active_readiness(), PROVIDER_UX_NO_KEY, "PROVIDER_KEY_MISSING")

            store.configure(provider=PROVIDER, model=MODEL, api_key=KEY)
            store._record_test(PROVIDER, self._health_result(ok=True))
            store.configure(provider=PROVIDER, model=ALT_MODEL)
            self._assert_state(
                store.active_readiness(),
                PROVIDER_UX_STALE_HEALTH_PROOF,
                "PROVIDER_HEALTH_PROOF_STALE",
            )

            store.configure(provider=PROVIDER, model=MODEL)
            failure_cases = [
                (PROVIDER_UX_INVALID_KEY, "PROVIDER_KEY_INVALID"),
                (PROVIDER_UX_QUOTA_FAILURE, "PROVIDER_QUOTA_FAILURE"),
                (PROVIDER_UX_RATE_LIMIT, "PROVIDER_RATE_LIMITED"),
                (PROVIDER_UX_PROVIDER_OUTAGE, "PROVIDER_OUTAGE"),
            ]
            for state, code in failure_cases:
                with self.subTest(state=state):
                    store._record_test(PROVIDER, self._health_result(ok=False, state=state, code=code))
                    self._assert_state(store.active_readiness(), state, code)

    def test_failure_classifier_splits_task57_hosted_errors(self):
        samples = {
            PROVIDER_UX_INVALID_KEY: "401 unauthorized invalid API key",
            PROVIDER_UX_QUOTA_FAILURE: "insufficient_quota billing credit exhausted",
            PROVIDER_UX_RATE_LIMIT: "429 too many requests rate limit",
            PROVIDER_UX_PROVIDER_OUTAGE: "503 service unavailable upstream timeout",
        }
        expected_codes = {
            PROVIDER_UX_INVALID_KEY: "PROVIDER_KEY_INVALID",
            PROVIDER_UX_QUOTA_FAILURE: "PROVIDER_QUOTA_FAILURE",
            PROVIDER_UX_RATE_LIMIT: "PROVIDER_RATE_LIMITED",
            PROVIDER_UX_PROVIDER_OUTAGE: "PROVIDER_OUTAGE",
        }
        for state, text in samples.items():
            with self.subTest(state=state):
                classified = _classify_provider_failure(text)
                self.assertEqual(classified["schema"], "xace.provider_ux_state.v1")
                self.assertEqual(classified["state"], state)
                self.assertEqual(classified["code"], expected_codes[state])
                self.assertTrue(classified["message"])
                self.assertTrue(classified["action"])

    def _health_result(self, *, ok: bool, state: str = "", code: str = "") -> dict:
        fingerprint = _fingerprint(KEY)
        selection = self._selection()
        checks = {
            "key_present": True,
            "key_valid": ok or state != PROVIDER_UX_INVALID_KEY,
            "model_reachable": ok,
            "test_call": ok,
        }
        ux_state = _provider_ux_state(
            ok=ok,
            code=code,
            state=state,
            action="test_provider",
            message="Provider is ready for prompts." if ok else "",
        )
        return {
            "ok": ok,
            "provider": PROVIDER,
            "model": MODEL,
            "base_url": BASE_URL,
            "key_fingerprint": fingerprint,
            "config_hash": _provider_config_hash(selection, fingerprint),
            "checks": checks,
            "message": "OpenAI responded." if ok else ux_state["message"],
            "latency_ms": 1,
            "failure_code": "" if ok else ux_state["code"],
            "failure_state": "" if ok else ux_state["state"],
            "ux_state": ux_state,
        }

    def _selection(self):
        from provider_settings import ProviderSelection  # noqa: WPS433

        return ProviderSelection(provider=PROVIDER, model=MODEL, base_url=BASE_URL, api_key=KEY)

    def _assert_state(self, readiness: dict, state: str, code: str) -> None:
        self.assertFalse(readiness.get("ok"))
        self.assertEqual(readiness.get("code"), code)
        ux_state = readiness.get("ux_state")
        self.assertIsInstance(ux_state, dict)
        self.assertEqual(ux_state.get("schema"), "xace.provider_ux_state.v1")
        self.assertEqual(ux_state.get("state"), state)
        self.assertEqual(ux_state.get("code"), code)
        self.assertTrue(ux_state.get("label"))
        self.assertTrue(ux_state.get("message"))
        self.assertTrue(ux_state.get("action"))


if __name__ == "__main__":
    unittest.main()
