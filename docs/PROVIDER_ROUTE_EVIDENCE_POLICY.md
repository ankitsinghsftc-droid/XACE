# Provider Route Evidence Policy

Task 56 gates automatic provider/model routing on benchmark evidence. Any
`ModelRouter` automatic choice must have a fresh `xace.provider_route_evidence.v1`
record for the exact route:

| Field | Requirement |
| --- | --- |
| `provider` | Provider ID selected by the router, such as `anthropic`, `deepseek`, `google`, or `local`. |
| `logical_name` | Logical model name from `ModelDescriptor`. |
| `model_id` | Concrete model ID used for the call. Local routes use the selected local model string. |
| `tier` | Effective `ComplexityTier` after pass-number overrides. |
| `benchmark_id` | Stable ID for the benchmark proof run. |
| `benchmark_hash` | Deterministic hash or artifact digest for the benchmark report. |
| `benchmarked_at_utc` | UTC timestamp for the benchmark run. |
| `expires_at_utc` | UTC timestamp after which the route is stale. |
| `status` | Must be `passed`. |

Missing evidence blocks with `MODEL_ROUTE_EVIDENCE_MISSING`. Expired evidence
blocks with `MODEL_ROUTE_EVIDENCE_STALE`. Malformed, failed, or future-dated
evidence blocks with `MODEL_ROUTE_EVIDENCE_INVALID`. If a preferred route is
missing or stale but another healthy route has fresh benchmark evidence, the
router may select the benchmarked route and records the rejected route messages
on the `RoutingDecision`.

This policy applies to automatic routing only. Explicit provider settings and
manual hosted provider use still pass through the Task 54 provider-readiness
gate and the Task 55 hosted-provider proof gate.

## Proof Command

```powershell
python tools/provider_route_evidence_check.py --output target-provider-route-evidence\provider_route_evidence_report.json
```

The report schema is `xace.provider_route_evidence_report.v1`. It proves a
benchmarked cloud route, missing-evidence rejection, stale-evidence rejection,
alternate benchmarked-route selection after an unbenchmarked preferred route is
rejected, and exact local selected-model evidence.
