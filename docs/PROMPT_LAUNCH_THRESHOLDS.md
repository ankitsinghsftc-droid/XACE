# Prompt Launch Thresholds

Source of truth: `docs/prompt_launch_thresholds.json`

Threshold schema: `xace.prompt_launch_thresholds.v1`

Owner task: `48`

Task 48 defines measurable launch thresholds for prompt benchmark reports and
wires those thresholds into `tools/prompt_corpus_benchmark.py`. The benchmark
now fails when the selected threshold profile is not met.

These thresholds do not turn local classifier-only evidence into hosted-provider
or runtime proof. The default profile gates the evidence XACE can measure today.
The launch profile defines the stricter future bar for hosted provider,
compilation, runtime, rollback, and provider reliability execution.
Task 53 provider accounting artifacts are emitted with every prompt benchmark
run; in the local classifier profile they prove `provider_call_count: 0`, zero
provider tokens, and zero provider cost.

## Profiles

| Profile | Purpose | Expected Status Today |
| --- | --- | --- |
| `local_classifier` | Gates the deterministic local classifier/matrix benchmark for the reviewed corpus. | Passing |
| `launch_provider_runtime` | Gates future hosted-provider plus compile/runtime/rollback benchmark execution. | Failing until those dimensions run |

## Local Classifier Thresholds

| Metric | Threshold |
| --- | ---: |
| Corpus cases | `>= 100` |
| Classification accuracy | `>= 0.85` |
| Builder route accuracy | `>= 0.75` |
| Result-kind accuracy | `>= 0.85` |
| Unsupported no-mutation rate | `>= 1.0` |
| Unsupported exact block/unsupported rate | `>= 0.90` |
| Total provider cost | `<= 0.0` |
| Provider cost per case | `<= 0.0` |
| Average latency | `<= 10 ms` |
| P95 latency | `<= 50 ms` |
| Reproducibility metadata | Required |
| Provider calls | `not_run` |
| Compile/runtime/rollback | `not_run_local_classifier_only` |

## Launch Provider Runtime Thresholds

| Metric | Threshold |
| --- | ---: |
| Corpus cases | `>= 100` |
| Classification accuracy | `>= 0.95` |
| Builder route accuracy | `>= 0.95` |
| Result-kind accuracy | `>= 0.95` |
| Compilation success rate | `>= 0.95` |
| Runtime success rate | `>= 0.95` |
| Rollback success rate | `>= 0.95` |
| Unsupported no-mutation rate | `>= 1.0` |
| Unsupported exact block/unsupported rate | `>= 0.98` |
| Provider reliability | `>= 0.98` |
| Provider cost per case | `<= 0.05 USD` |
| P95 latency | `<= 15000 ms` |
| Reproducibility metadata | Required |

The `launch_provider_runtime` profile also requires provider, compile, runtime,
and rollback dimensions to execute. Running that profile against the local
classifier-only report must fail.

## Commands

Run the default local threshold profile:

```powershell
python tools/prompt_corpus_benchmark.py --output target-production-prompt-corpus
```

Run the future launch profile:

```powershell
python tools/prompt_corpus_benchmark.py --threshold-profile launch_provider_runtime --output target-production-prompt-corpus-launch-threshold
```

Validate the threshold contract and benchmark failure behavior:

```powershell
python tools/prompt_launch_threshold_check.py
```

The checker verifies that the local benchmark passes the selected profile and
that an intentionally stricter threshold file makes the benchmark fail below
threshold.
