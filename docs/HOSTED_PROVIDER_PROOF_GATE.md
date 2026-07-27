# Hosted Provider Proof Gate

Task 55 adds an opt-in BYOK proof gate for real hosted and local/self-hosted
provider execution.

Normal certification performs no live provider calls. It runs the gate in
not-run mode to prove the safety boundary and report redaction. Live proof
requires both:

```powershell
$env:XACE_HOSTED_PROVIDER_PROOF_OPT_IN = "1"
python tools/hosted_provider_proof_gate.py --live --require-live --output target-hosted-provider-proof\hosted_provider_proof_report.json
```

## Live Provider Inputs

The live run checks OpenAI-compatible, Anthropic, Google, and one local or
self-hosted provider when requested. Each live provider must name the exact
model under test.

| Proof ID | Required BYOK/model inputs | Optional endpoint input |
| --- | --- | --- |
| `openai_compatible` | `XACE_OPENAI_COMPATIBLE_API_KEY` or `XACE_OPENAI_API_KEY`, plus `XACE_OPENAI_COMPATIBLE_MODEL` or `XACE_OPENAI_MODEL` | `XACE_OPENAI_COMPATIBLE_BASE_URL` |
| `anthropic` | `XACE_ANTHROPIC_API_KEY`, `XACE_ANTHROPIC_MODEL` | `XACE_ANTHROPIC_BASE_URL` |
| `google` | `XACE_GOOGLE_API_KEY`, `XACE_GOOGLE_MODEL` | `XACE_GOOGLE_BASE_URL` |
| `local_self_hosted` | `XACE_LOCAL_MODEL`; for OpenAI-compatible local endpoints also `XACE_LOCAL_API_KEY` | `XACE_LOCAL_PROVIDER_KIND`, `XACE_LOCAL_BASE_URL` |

`XACE_LOCAL_PROVIDER_KIND=ollama` is the default local provider kind.
`XACE_LOCAL_PROVIDER_KIND=openai_compatible` checks a self-hosted
OpenAI-compatible endpoint through the inference adapter.

To run only a subset:

```powershell
python tools/hosted_provider_proof_gate.py --live --require-live --providers openai_compatible,local_self_hosted --output target-hosted-provider-proof\hosted_provider_proof_report.json
```

## Report Contract

The report schema is `xace.hosted_provider_proof_report.v1`.

Each live provider case records:

- Provider proof ID, provider kind, model, base URL, and hash-only key
  fingerprint.
- Health result from the same provider settings path used by Builder.
- Prompt result through the real `InferenceAdapter` or local adapter.
- Token/cost/request metadata when the adapter returns it.
- Redaction status with known-secret and credential-shape findings.

The report must not contain raw API keys, bearer tokens, Google key shapes,
request URLs containing keys, or provider error text containing credentials.
If any configured key or credential-shaped text survives redaction, the gate
fails with `HOSTED_PROVIDER_REPORT_SECRET_SHAPE`.

## Current Launch Meaning

Task 55 provides the live proof command and its redaction/non-network guard.
This repository run did not execute live hosted calls because no BYOK provider
keys were supplied. A private-alpha or release gate that needs hosted-provider
acceptance must run the command with `--live --require-live` and archive the
redacted report.
