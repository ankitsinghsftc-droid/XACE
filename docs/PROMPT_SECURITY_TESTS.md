# Prompt Security Tests

Source of truth: `docs/prompt_security_cases.jsonl`

Report schema: `xace.prompt_security_report.v1`

Owner task: `50`

Task 50 adds deterministic local prompt-security attack cases and a proof
command. The gate covers prompt injection, adversarial instructions, malformed
model responses, unsafe mutations, hallucinated capabilities, schema
corruption, and secret exfiltration attempts.

This is not an external security review and does not prove arbitrary prompt
security. It proves that the checked-in attack corpus is blocked before
provider/mutation execution or quarantined with recorded reasons and artifacts.

## Case Contract

Each JSONL row uses schema `xace.prompt_security_case.v1` and includes:

| Field | Meaning |
| --- | --- |
| `id` | Stable case ID. |
| `attack_type` | One required class from the Task 50 attack set. |
| `surface` | Deterministic guard being exercised. |
| `input` | Prompt, provider response, mutation, capability, or CGS fragment payload. |
| `expected_outcome` | `blocked` or `quarantined`. |
| `expected_reason` / `expected_signals` | Exact evidence expected from the guard. |

Required attack classes:

- `prompt_injection`
- `adversarial_instructions`
- `malformed_model_response`
- `unsafe_mutation`
- `hallucinated_capability`
- `schema_corruption`
- `secret_exfiltration`

## Guard Behavior

- Prompt-level attacks run through the real Builder classifier in
  `packages/builder-workspace/server/prompt_classifier_gate.py`.
- Classifier-blocked attacks must report category `unsupported` or `blocked`,
  deny provider calls, deny mutation creation, and include the expected signal.
- Malformed model responses are quarantined before any mutation transaction is
  trusted.
- Unsafe mutation payloads are quarantined when they request host command,
  filesystem, network, upload, or path-traversal behavior.
- Hallucinated capabilities are checked against the certified/constrained
  prompt capability matrix examples.
- Corrupted CGS fragments are quarantined for schema, entity, component, or hash
  integrity failures.

## Artifacts

Run:

```powershell
python tools/prompt_security_check.py --artifact-dir target-prompt-security
```

The command writes:

| Artifact | Schema / Contents |
| --- | --- |
| `target-prompt-security/prompt_security_report.json` | `xace.prompt_security_report.v1` summary with counts, corpus hash, findings, and artifact paths. |
| `target-prompt-security/prompt_security_cases.jsonl` | `xace.prompt_security_case_result.v1` per-case rows. |
| `target-prompt-security/prompt_security_report.md` | Human-readable summary table. |

Launch certification quick/full runs the same gate under its target directory:

```powershell
python tools/certify_launch.py --quick --target-dir target-codex-certify-task50-quick --report-path target-codex-certify-task50-quick\launch_certification_report.json
```
