# Prompt Launch Thresholds

Source of truth: `docs/prompt_launch_thresholds.json`

Threshold schema: `xace.prompt_launch_thresholds.v1`

Owner task: `48`

Task 48 defines measurable launch thresholds for prompt benchmark reports and
wires those thresholds into `tools/prompt_corpus_benchmark.py`. The benchmark
now fails when the selected threshold profile is not met.

These thresholds separate local classifier-only evidence, local launch
provider/runtime evidence, and opt-in hosted-provider evidence. The default
profile gates the deterministic classifier/matrix benchmark. The
`launch_provider_runtime` profile is now exercised by
`tools/launch_provider_runtime_benchmark.py`: it sends provider-allowed corpus
rows through the real `InferenceAdapter` accounting/telemetry path, runs real
SGC/runtime and rollback proof commands, and fails if required dimensions do not
execute. This is not a hosted BYOK reliability claim; hosted proof remains the
separate opt-in `tools/hosted_provider_proof_gate.py` path.
Task 53 provider accounting artifacts are emitted with every prompt benchmark
run; in the local classifier profile they prove `provider_call_count: 0`, zero
provider tokens, and zero provider cost.

## Profiles

| Profile | Purpose | Expected Status Today |
| --- | --- | --- |
| `local_classifier` | Gates the deterministic local classifier/matrix benchmark for the reviewed corpus. | Passing |
| `launch_provider_runtime` | Gates launch provider/accounting plus compile/runtime/rollback benchmark execution. | Passing locally when built SGC/runtime binaries are supplied; hosted BYOK remains separate |

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

The `launch_provider_runtime` profile requires provider, compile, runtime, and
rollback dimensions to execute. `tools/launch_provider_runtime_benchmark.py`
provides those dimensions for the reviewed corpus using a deterministic local
provider client behind `InferenceAdapter` plus real SGC/runtime/rollback proof
commands. Running the profile against the local classifier-only report must
still fail.

## Commands

Run the default local threshold profile:

```powershell
python tools/prompt_corpus_benchmark.py --output target-production-prompt-corpus
```

Run the launch provider/runtime profile, with built runtime and SGC binaries:

```powershell
cargo build -p xace-runtime-core --bin xace_runtime --target-dir target-codex-task28-runtime
cargo build -p xace-system-graph-compiler --target-dir target-codex-task28-runtime
python tools/launch_provider_runtime_benchmark.py --output target-codex-task28-launch-provider-runtime --runtime-bin target-codex-task28-runtime\debug\xace_runtime.exe --sgc-bin target-codex-task28-runtime\debug\xace-system-graph-compiler.exe --json
```

Prove the local classifier-only report cannot satisfy the launch profile:

```powershell
python tools/prompt_corpus_benchmark.py --threshold-profile launch_provider_runtime --output target-production-prompt-corpus-launch-threshold
```

Validate the threshold contract and benchmark failure behavior:

```powershell
python tools/prompt_launch_threshold_check.py
```

The checker verifies that the local benchmark passes the selected profile, that
the launch benchmark command is documented, and that an intentionally stricter
threshold file makes the benchmark fail below threshold.
