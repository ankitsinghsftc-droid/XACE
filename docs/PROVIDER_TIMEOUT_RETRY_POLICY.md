# Provider Timeout And Retry Policy

Task 52 defines the provider-call retry ABI used by `packages/inference`.
Every live provider call routed through `InferenceAdapter` now produces a
deterministic retry summary in telemetry, whether the call succeeds, retries,
or fails before usable text is returned.

## Scope

The policy applies to provider calls made through:

- `packages/inference/src/inference_adapter.py`
- `packages/inference/src/inference_retry_policy.py`
- registered provider clients under `packages/inference`

Cache hits and deterministic Tier S shortcuts are still telemetry events, but
their provider attempt count is `0` because no provider call occurs.

## Retry Summary ABI

The retry policy emits `xace.inference_retry_summary.v1` with:

- `provider`, `model_id`, `tier`, and `call_label`
- configured `timeout_seconds`
- `attempt_count` and `retry_count`
- `rate_limited`
- `total_backoff_seconds`
- `final_outcome`: `success` or `failure`
- `final_failure_category` on failure
- `user_error` for deterministic user-facing failure handling
- `attempts`, each using `xace.inference_retry_attempt.v1`

Each attempt records:

- actual provider call index
- attempt kind
- outcome
- failure category
- error type and bounded error message
- whether a retry was scheduled
- backoff seconds
- timeout seconds
- rate-limit classification
- elapsed milliseconds

## Failure Categories

| Category | User error code | Retry behavior |
| --- | --- | --- |
| `timeout` | `PROVIDER_TIMEOUT` | Transport retry budget, no default backoff. |
| `rate_limit` | `PROVIDER_RATE_LIMIT` | Transport retry budget with Retry-After or exponential backoff. |
| `server_error` | `PROVIDER_SERVER_ERROR` | Transport retry budget with fixed tier backoff. |
| `transport_error` | `PROVIDER_TRANSPORT_ERROR` | Transport retry budget, no default backoff. |
| `schema_error` | `PROVIDER_RESPONSE_SCHEMA` | Schema retry budget. |
| `quality_error` | `PROVIDER_EMPTY_RESPONSE` | Quality retry budget. |
| `provider_error` | `PROVIDER_CALL_FAILED` | Generic provider failure if no narrower category matches. |

`InferenceAdapter` copies the final summary into `InferenceTelemetryEvent` as
`retry_report` and also exposes compact top-level telemetry fields:
`attempt_count`, `retry_count`, `timeout_seconds`, `rate_limited`,
`backoff_seconds`, `failure_category`, and `user_error_code`.

## Local Proof

Run:

```powershell
python tools/provider_timeout_retry_check.py --json
```

The checker uses a synthetic provider client with the real `InferenceAdapter`
and proves timeout recovery, exhausted timeout, exhausted rate limit, exhausted
server error, exhausted schema error, and exhausted quality error behavior. The
report is written to:

```text
target-provider-timeout-retry/provider_timeout_retry_report.json
```

Launch certification runs the same check in quick and full modes and stores the
artifact under the selected certification target directory.
