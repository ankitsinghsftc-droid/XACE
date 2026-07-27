# Provider Health And Stale-Model Policy

Task 54 defines the local provider-readiness ABI that Builder checks before
any prompt can enter PIL. Task 58 adds a narrow deterministic exception for
certified player-speed value edits: those edits emit approval-gated GDE
transactions locally and do not enter provider readiness, PIL, or LLM execution.

## Readiness Tuple

Hosted providers are ready only when the current settings have a matching
`xace.provider_health_proof.v1` record for the exact tuple below:

| Field | Requirement |
| --- | --- |
| `provider` | Canonical provider ID, such as `openai`, `anthropic`, `google`, or `moonshot`. |
| `model` | Non-empty resolved model ID; `unresolved` is blocked. |
| `base_url` | Canonical http(s) base URL with trailing slashes removed. |
| `key_fingerprint` | Stored key fingerprint from the local credential flow; raw keys are never stored in the proof. |
| `config_hash` | Deterministic hash of provider, model, base URL, and key fingerprint. |
| `checks` | `key_present`, `key_valid`, `model_reachable`, and `test_call` must all be true. |

Changing the model, base URL, or saved key keeps the previous proof for audit
context, but the readiness gate marks it stale and requires a new Test run.

## Blocking Codes

`ProviderSettingsStore.active_readiness()` returns these deterministic codes
for hosted provider configurations:

| Code | Meaning | Prompt behavior |
| --- | --- | --- |
| `PROVIDER_MODEL_UNRESOLVED` | No resolved model is selected. | Block before PIL. |
| `PROVIDER_BASE_URL_INVALID` | The current base URL is empty or not http(s). | Block before PIL. |
| `PROVIDER_KEY_MISSING` | Hosted provider has no saved API key. | Block before PIL. |
| `PROVIDER_KEY_FINGERPRINT_MISSING` | A key exists but the settings artifact lacks the fingerprint. | Block before PIL. |
| `PROVIDER_HEALTH_UNTESTED` | No health proof exists for the current tuple. | Block before PIL. |
| `PROVIDER_HEALTH_PROOF_INVALID` | The proof is malformed or lacks required passing checks. | Block before PIL. |
| `PROVIDER_HEALTH_PROOF_STALE` | The proof hash or tuple no longer matches current settings. | Block before PIL. |
| `PROVIDER_HEALTH_FAILED` | The latest health test failed. | Block before PIL. |
| `PROVIDER_KEY_INVALID` | The latest hosted health test rejected the saved key. | Block before PIL. |
| `PROVIDER_QUOTA_FAILURE` | The latest hosted health test was blocked by quota, billing, or credits. | Block before PIL. |
| `PROVIDER_RATE_LIMITED` | The latest hosted health test hit a provider rate limit. | Block before PIL. |
| `PROVIDER_OUTAGE` | The latest hosted health test hit a provider outage, timeout, or service failure. | Block before PIL. |

For prompts that require PIL/provider execution, `SessionManager.run_pil()`
carries the readiness `code`, `action`, and `guard=provider_readiness` in its
blocked result so Builder can surface the same reason the server enforced.

## Builder UX State ABI

Task 57 adds a stable `ux_state` object to provider readiness, provider test
results, persisted health proofs, and pre-PIL blocked responses:

```json
{
  "schema": "xace.provider_ux_state.v1",
  "state": "rate_limit",
  "code": "PROVIDER_RATE_LIMITED",
  "label": "Rate limit",
  "message": "Provider rate limit blocked the last Test. Wait, lower traffic, or choose another provider.",
  "action": "wait_or_choose_provider",
  "severity": "blocked"
}
```

The required Builder states are deterministic:

| State | Readiness code | Builder copy |
| --- | --- | --- |
| `no_key` | `PROVIDER_KEY_MISSING` | Add a provider API key, save it, then run Test before prompting. |
| `invalid_key` | `PROVIDER_KEY_INVALID` | Replace the rejected key, save, then run Test. |
| `stale_health_proof` | `PROVIDER_HEALTH_PROOF_STALE` | Provider settings changed; run Test again. |
| `quota_failure` | `PROVIDER_QUOTA_FAILURE` | Add quota or choose another provider. |
| `rate_limit` | `PROVIDER_RATE_LIMITED` | Wait, lower traffic, or choose another provider. |
| `provider_outage` | `PROVIDER_OUTAGE` | Retry when the provider is reachable or choose another provider. |

The Builder prompt box and provider settings panel consume this object directly.
`npm run test:ui` covers the UI copy and publish path, while
`packages/builder-workspace/server/tests/test_provider_ux_states.py` covers the
server readiness states and hosted failure classifier.

## Proof Command

```powershell
python tools/provider_readiness_smoke.py --settings-path target-provider-health\provider_settings.json --output target-provider-health\provider_health_stale_policy_report.json
python -m unittest packages/builder-workspace/server/tests/test_provider_ux_states.py
npm.cmd --prefix packages/builder-workspace run test:ui
```

The report schema is `xace.provider_health_stale_policy_report.v1`. It proves
missing key, untested tuple, exact ready tuple, stale model, stale base URL,
stale key fingerprint, malformed proof, and invalid base URL cases using
isolated local settings and a certified structural prompt that still requires
provider/PIL readiness.

This is local deterministic readiness evidence. Task 55 adds the opt-in BYOK
hosted-provider proof command for real health and prompt checks, but archived
live BYOK reports and provider-specific reliability thresholds remain launch
proof work.
