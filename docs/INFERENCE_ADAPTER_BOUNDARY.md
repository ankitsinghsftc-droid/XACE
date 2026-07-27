# Inference Adapter Boundary

Source of truth: `tools/inference_adapter_boundary_check.py`

Report schema: `xace.inference_adapter_boundary_report.v1`

Owner task: `51`

Task 51 enforces one rule: Builder, PIL, GDE, and repository tools must not call
LLM providers directly. Provider SDK imports, provider completion endpoints, and
local model completion HTTP belong inside `packages/inference`.

Builder may keep provider IDs, model IDs, and endpoint configuration strings for
settings and UI. Actual provider execution, including local Ollama/vLLM model
completion and hosted-provider model discovery, must be routed through
`packages/inference`.

## Enforced Boundary

Allowed:

- `packages/inference/providers/**`
- `packages/inference/src/inference_adapter.py`
- Other `packages/inference/src/**` provider routing, discovery, budget, retry,
  cache, and telemetry helpers

Blocked outside `packages/inference`:

- Direct imports of provider SDK packages such as `openai`, `anthropic`, Google
  generative SDKs, Cohere, Groq, or Mistral.
- HTTP dispatch to provider completion endpoints such as OpenAI-compatible chat
  completions, Anthropic messages, Google `generateContent`, Moonshot chat
  completions, or local Ollama completion endpoints.
- Builder-local or tool-local model completion adapters that bypass
  `InferenceAdapter`.

## Implementation Notes

- Builder local Ollama dispatch now uses
  `packages/builder-workspace/server/ollama_adapter.py`, a thin wrapper around
  `packages/inference/src/local_model_manager.py` and `InferenceAdapter`.
- Hosted provider model discovery now lives in
  `packages/inference/src/provider_model_discovery.py`; Builder calls that helper
  instead of performing provider HTTP itself.
- `tools/inference_adapter_boundary_check.py` scans Builder, PIL, GDE, and tools
  for provider SDK imports and provider completion HTTP outside
  `packages/inference`. It also runs synthetic detector checks so the gate fails
  if the scanner stops detecting representative violations.

## Commands

Run the boundary gate:

```powershell
python tools/inference_adapter_boundary_check.py
```

Write an explicit artifact:

```powershell
python tools/inference_adapter_boundary_check.py --output target-inference-adapter-boundary\inference_adapter_boundary_report.json
```

Launch certification quick/full runs the same gate under the certification
target directory, and hosted CI runs it in `.github/workflows/xace-scope.yml`.
