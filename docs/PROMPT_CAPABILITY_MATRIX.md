# Prompt Capability Matrix

Source of truth: `docs/prompt_capability_matrix.json`

Matrix schema: `xace.prompt_capability_matrix.v1`

Matrix hash: `426b3ed4a78a4ba10459886335c250c316c1cbbc4e5c6f78a2fe8a5748b2086a`

Task 35 defines the launch-safe prompt categories shared by documentation and
Builder. Builder exposes the same JSON artifact at
`GET /api/prompt/capability-matrix`; docs must not redefine prompt capability
categories outside that matrix.

## Category Summary

| Category | Builder decision | Product wording |
| --- | --- | --- |
| Certified supported | `accept_mutation_preview` | Certified prompt scenarios can create reviewed CGS mutations for the listed edits, then pass GDE, SGC, persistence, and runtime checks before they are treated as applied. |
| Constrained | `accept_with_constraints` | Constrained prompt scenarios may be supported when the request maps to known CGS components, systems, assets, or values and the Builder can show exactly what will change. |
| Clarification required | `ask_clarification` | Ambiguous prompt scenarios must ask bounded clarification questions before any CGS mutation is planned or applied. |
| Blocked | `block_before_mutation` | Blocked prompt scenarios are too broad, unsafe, or impossible to verify as a single safe CGS mutation and must not leave a pending apply transaction. |
| Unsupported | `refuse_unsupported` | Unsupported prompt scenarios request behavior XACE does not currently implement, such as engine-native scripting, external services, unsafe code, direct filesystem or network access, or unproven engine packaging. |
| Experimental | `hide_or_gate_experimental` | Experimental prompt scenarios are research or future-work categories. They must be labeled as experimental, hidden or gated in launch builds, and backed by separate proof before becoming supported. |

## Examples

| Category | Example prompts | Builder route |
| --- | --- | --- |
| Certified supported | "Set the player movement speed to 6.5."; "Add a general inventory component to the player."; "Add one generic pickup object near the player." | `mutation_preview` or `mutation_preview_with_sgc` |
| Constrained | "Add a simple stamina value to the player using the existing movement template."; "Add a health pickup near the player using the existing pickup behavior."; "Link this selected mesh reference to the pickup object." | `mutation_or_clarification` |
| Clarification required | "Make enemies harder."; "Add inventory."; "Add crafting." | `clarification` |
| Blocked | "Create any complete online game with all art, audio, animation, servers, and stores."; "Package and publish my finished game for every platform."; "Automatically convert my entire engine-native project into XACE gameplay." | `blocked` |
| Unsupported | "Write a Unity MonoBehaviour script that controls my player directly."; "Set up a hosted matchmaking backend and payment system."; "Read files from my desktop and use them to change the game automatically." | `unsupported` |
| Experimental | "Generate a branching quest chain with rewards and dialogue."; "Create a networked raid encounter with synced boss phases."; "Design a complete survival crafting loop from scratch." | `experimental` |

## Builder Contract

- Builder must load prompt capability categories from
  `docs/prompt_capability_matrix.json`.
- Builder API responses must include the canonical `matrix_hash` when returning
  the matrix.
- Builder boot must fetch `GET /api/prompt/capability-matrix` and retain the
  returned artifact for prompt UX/classifier flows rather than defining local
  categories.
- Certified supported examples must stay aligned with
  `packages/builder-workspace/server/tests/fixtures/prompt_pipeline_contract.py`.
- Blocked examples must not leave a pending prompt transaction.
- Task 36 classifier enforcement uses these category IDs and product wording.
  Non-accepted categories return a classifier-bearing `pil_result` before PIL,
  mutation planning, or provider calls.
- Task 37 clarification enforcement turns `clarification_required` classifier
  routes into bounded prompt clarification sessions. Builder records the chosen
  user resolution, blocks `pil_apply` while that session is pending, and does
  not generate a mutation from ambiguous wording without the recorded
  resolution.
- Task 42 prompt approval enforcement attaches a structured
  `xace.prompt_diff_preview.v1` preview to accepted mutation results. The
  preview covers CGS, system, asset, SGC, runtime, and cost sections, and
  `pil_apply` rejects persistence unless the request carries the matching
  preview approval token or an audited test-mode override with a reason.
- Task 44 prompt rollback recovery restores the pre-apply CGS and session
  runtime state for covered compile/runtime/replay/adapter/provider failure
  paths. Recovery emits `xace.prompt_apply_recovery.v1`, removes failed
  snapshot/plan/proof artifacts, and does not send `cgs_update` on failure.
- Task 45 prompt apply validation feedback attaches
  `xace.prompt_apply_feedback.v1` to every prompt apply response. The feedback
  includes classifier result, structured diff, SGC result, runtime load result,
  replay result, adapter result, rollback status, cost, latency, proof links,
  approval metadata, and authority hashes so Builder can show concrete failure
  details instead of a generic error state.
- Task 46 prompt corpus coverage stores a reviewed, versioned
  `xace.prompt_corpus_100.v1` JSONL corpus at `docs/prompt_corpus_100.jsonl`.
  The corpus covers 100 prompts across certified, constrained, clarification,
  blocked, unsupported, adversarial, experimental, and required genre-diverse
  cases for later benchmark tooling. It does not by itself prove hosted-provider
  reliability or benchmark thresholds.
- Task 47 prompt corpus benchmarking writes local classifier-only JSONL, JSON,
  and Markdown reports from the reviewed corpus. The report records accepted,
  blocked, clarified, compiled, runtime-passed, rollback-passed, cost, latency,
  provider, model, and reproducibility columns, while explicitly marking
  provider, compile, runtime, and rollback execution as not run in the local
  default mode.
- Task 48 prompt launch thresholds store measurable benchmark gates in
  `docs/prompt_launch_thresholds.json`. The local classifier profile gates
  classification, route, unsupported-blocking, cost, latency, and
  reproducibility metrics; the future launch profile defines provider,
  compilation, runtime, rollback, reliability, cost, latency, and
  reproducibility thresholds that must fail until those dimensions execute.
- Task 50 prompt security coverage stores deterministic attack cases in
  `docs/prompt_security_cases.jsonl` and validates them with
  `tools/prompt_security_check.py`. Covered prompt injection, adversarial
  instruction, malformed model-response, unsafe mutation, hallucinated
  capability, schema-corruption, and secret-exfiltration cases must be blocked
  before provider/mutation execution or quarantined with `xace.prompt_security_report.v1`
  artifacts.
- Task 51 inference boundary enforcement requires Builder, PIL, GDE, and tools
  to route provider execution through `packages/inference`. Local Ollama
  dispatch and hosted provider model discovery now live behind inference-layer
  helpers, and `tools/inference_adapter_boundary_check.py` fails when provider
  SDK imports or provider completion HTTP appear outside `packages/inference`.
- Task 52 provider timeout/retry enforcement records timeout policy, attempt
  count, retry count, rate-limit classification, backoff, failure category,
  deterministic user-facing error code, final outcome, and retry summary
  telemetry for every provider call through `InferenceAdapter`.
  `tools/provider_timeout_retry_check.py` proves timeout, rate-limit, server,
  schema, and quality failure behavior with local simulated provider failures.
- Task 53 provider token/cost accounting exports redacted
  `xace.provider_accounting_event.v1` JSONL rows and
  `xace.provider_accounting_summary.v1` JSON/Markdown summaries for prompt
  benchmarks. The local classifier benchmark records zero hosted provider
  calls, while `tools/provider_token_cost_accounting_check.py` proves exact
  prompt/completion/cache token, cost, model, tier, latency, request ID,
  cache-hit, deterministic-shortcut, failure, and redaction behavior through
  the real `InferenceAdapter`.
- Task 54 provider health enforcement requires an exact
  `xace.provider_health_proof.v1` match for provider, model, base URL, key
  fingerprint, and config hash before any prompt enters PIL. Stale, missing,
  invalid, or untested hosted provider settings return deterministic
  `PROVIDER_*` readiness codes and block with `guard=provider_readiness`.
- Task 55 hosted provider proof gating adds
  `tools/hosted_provider_proof_gate.py` and
  `xace.hosted_provider_proof_report.v1`. Normal local certification performs
  no live provider calls; live OpenAI-compatible, Anthropic, Google, and
  local/self-hosted health and prompt proof requires `--live`,
  `XACE_HOSTED_PROVIDER_PROOF_OPT_IN=1`, exact model IDs, and BYOK inputs.
- Task 56 automatic provider/model routing gates `ModelRouter` choices on
  `xace.provider_route_evidence.v1` benchmark records. Missing, stale, invalid,
  or failed route evidence blocks with deterministic `MODEL_ROUTE_EVIDENCE_*`
  explanations; if another healthy route has fresh evidence, the router may
  select that route and records the rejected route messages.
- Task 57 provider setup UX adds `xace.provider_ux_state.v1` to readiness,
  provider-test, health-proof, and pre-PIL blocked responses. Builder has
  explicit no-key, invalid-key, stale-health-proof, quota-failure, rate-limit,
  and provider-outage states covered by UI and server tests.
- Task 58 deterministic simple-edit routing recognizes certified player-speed
  numeric value edits and emits the same approval-gated GDE mutation transaction
  without provider readiness, PIL, LLM, or hosted-provider calls. The route is
  narrow: missing/non-numeric CGS targets, unsupported fields, unsafe values, or
  structural edits continue through the existing provider/PIL readiness path.
  `tools/deterministic_simple_edit_benchmark.py` proves zero provider,
  provider-readiness, PIL, and LLM calls for the certified simple-edit cases.

## Verification

```powershell
python tools/prompt_capability_matrix_check.py
python tools/prompt_clarification_loop_check.py
python tools/prompt_diff_approval_check.py
python tools/prompt_apply_recovery_check.py
python tools/prompt_apply_validation_feedback_check.py
python tools/prompt_corpus_check.py
python tools/prompt_corpus_benchmark.py --output target-production-prompt-corpus
python tools/deterministic_simple_edit_benchmark.py --output target-deterministic-simple-edit-benchmark
python tools/prompt_launch_threshold_check.py
python tools/prompt_security_check.py --artifact-dir target-prompt-security
python tools/inference_adapter_boundary_check.py
python tools/provider_timeout_retry_check.py
python tools/provider_token_cost_accounting_check.py
python tools/provider_readiness_smoke.py --settings-path target-provider-health\provider_settings.json --output target-provider-health\provider_health_stale_policy_report.json
python tools/hosted_provider_proof_gate.py --output target-hosted-provider-proof\hosted_provider_proof_report.json
python tools/provider_route_evidence_check.py --output target-provider-route-evidence\provider_route_evidence_report.json
npm.cmd --prefix packages/builder-workspace run test:ui
```
