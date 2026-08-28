# Prompt Corpus

Source of truth: `docs/prompt_corpus_100.jsonl`

Manifest: `docs/prompt_corpus_manifest.json`

Corpus schema: `xace.prompt_corpus_case.v1`

Corpus id: `xace.prompt_corpus_100.v1`

Corpus version: `1`

Corpus SHA-256:
`9fa5bac704aa6472f28a01b09703a25771604a36d2707e38a797cf0d511b974a`

Task 46 defines the reviewed 100-prompt JSONL corpus used by benchmark and
launch-threshold work. This corpus is a static, reviewed source artifact. Task
47 adds the local benchmark report generator for this corpus, Task 48 adds the
threshold profiles that make the benchmark fail when measured results fall
below the selected profile, and Task 53 adds redacted provider accounting
artifacts to every benchmark run. The local benchmark is not a hosted-provider
benchmark result and does not expand the prompt capability claims beyond
`docs/prompt_capability_matrix.json`.

## Coverage

| Dimension | Required Coverage | Count |
| --- | --- | --- |
| Prompts | Reviewed JSONL cases | 100 |
| Genres | platformer, rpg, shooter, survival, puzzle, strategy, inventory, simulation, multiplayer_combat, hybrid | 10 each |
| Categories | certified_supported, constrained, clarification_required, blocked, unsupported, experimental | 20, 20, 20, 10, 20, 10 |
| Difficulty bands | easy, medium, advanced, ambiguous, unsupported, adversarial | 10, 20, 20, 20, 20, 10 |

## Case Contract

Every JSONL row must include:

- `schema`: `xace.prompt_corpus_case.v1`
- `corpus_id`: `xace.prompt_corpus_100.v1`
- `corpus_version`: `1`
- `prompt_id`: stable `pc001` through `pc100`
- `genre`: one of the required genre IDs
- `difficulty_band`: one of the required difficulty bands
- `category_id`: one of the Task 35 prompt capability matrix category IDs
- `expected_builder_route`: expected Builder route for later benchmark tooling
- `expected_result_kind`: expected high-level Builder result shape
- `prompt`: the natural-language prompt
- `review`: reviewed flag, reviewer, review date, and status

## Validation

```powershell
python tools/prompt_corpus_check.py
```

The checker validates JSONL syntax, manifest hash, exact case count, unique
prompt IDs, category/route consistency, required genre/difficulty/category
coverage, and review metadata.

## X10-026 Unknown Path Case

`pc099` is the reviewed adversarial case for unknown CGS path production
hard-failure. It includes `x10_026_adversarial_case.parser_path` with the
unsupported grammar
`modes.mode_default.actors.actor_zombie.components.5.defaults.max_linear_speed`
and expects a blocked production apply result.

```powershell
python tools/prompt_unknown_cgs_path_check.py --json
```

## Benchmark

```powershell
python tools/prompt_corpus_benchmark.py --corpus docs/prompt_corpus_100.jsonl --output target-production-prompt-corpus
```

Task 47 writes:

- `summary.json`: schema `xace.prompt_corpus_benchmark.v1`, summary counts,
  reproducibility metadata, and full per-case results.
- `results.jsonl`: one `xace.prompt_corpus_benchmark_case.v1` row per prompt.
- `report.md`: human-readable benchmark report.
- `provider_accounting.jsonl`: redacted provider accounting event rows. This
  file is empty in the local classifier-only profile because no provider calls
  execute.
- `provider_accounting_summary.json`: schema
  `xace.provider_accounting_summary.v1`, provider call count, token totals,
  cost totals, latency totals, request ID counts, and redaction status.
- `provider_accounting.md`: human-readable provider accounting summary.

The default benchmark mode is local classifier-only. It records accepted,
blocked, clarified, compiled, runtime-passed, rollback-passed, cost, latency,
provider, model, and reproducibility columns for every corpus row. Provider
calls, SGC compile, runtime execution, rollback execution, and launch thresholds
are explicitly marked as not run in this mode. The provider accounting summary
therefore records `provider_call_count: 0`, zero tokens, and zero provider cost.

## Thresholds

Source of truth: `docs/prompt_launch_thresholds.json`

Human-readable contract: `docs/PROMPT_LAUNCH_THRESHOLDS.md`

The default benchmark evaluates the `local_classifier` profile and fails if the
measured local classifier/matrix report falls below threshold:

```powershell
python tools/prompt_corpus_benchmark.py --output target-production-prompt-corpus
```

The threshold checker proves both pass and fail behavior:

```powershell
python tools/prompt_launch_threshold_check.py
```
