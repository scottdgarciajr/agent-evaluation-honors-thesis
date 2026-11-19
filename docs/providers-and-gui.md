# Providers and the desktop console

## Desktop workflow

Double-click `Open Research GUI.cmd`. The launcher reuses or installs the pinned environment and opens
a native Tk window. It does not expose a network web server or put credentials in a URL. The CLI
equivalent is `.venv\Scripts\agent-eval.exe gui`.

Ollama discovery connects to `http://127.0.0.1:11434` by default and lists installed model capabilities.
Check individual models or Select all compatible. Models explicitly lacking tool support are disabled;
embedding models cannot act as AgentDojo agents. Unknown tool capability is labeled unverified and can
be tested individually. No models are downloaded automatically.

Choose OpenAI to enter a masked key and refresh account model IDs, or add an ID manually. The account
model endpoint does not certify tool support. Obvious embedding/image/audio IDs are filtered, and
remaining IDs are candidates. Apply verified positive per-million input/output token prices to checked
models. Different models can have different prices. Prices are remembered; API keys are not.

Quick check uses development banking task 14, injection goal 7, one attack, and baseline/full safeguards:
four episodes per model. It tests integration and is too small to establish comparative security.
Pilot and main-study presets retain their original task selections and comparisons. The footprint
preview shows total scheduled episodes before optional caps. All selected models run sequentially.

The **Set up a test** tab provides three choices: where to run, which models to use, and how much testing.
Usable models are shown first. Research combinations and model parameters are optional. After testing,
the **Understand the results** tab opens automatically with three count-based graphs and a written explanation:
ordinary task completion, attacker-goal success, and useful work during those same attacks.

The window remains responsive during inference. Stop prevents subsequent requests/episodes/models;
an in-flight request waits for completion or timeout. Closing an active console first requests a safe
stop. Open results opens the batch comparison. The offline demo button runs scripted fixtures separately.

## Results and credentials

Each GUI run gets a unique `runs/gui-<UTC timestamp>-<suffix>/` folder. Its `report.html` compares models
and links to each detailed report. `comparison.csv` contains descriptive rates by model/condition/scenario.
`batch.json` records public configuration and model status. Individual model directories retain the
original manifests, schedules, episode JSONs, charts, paired estimates, and coverage information.
Partial/error models remain visible. View Results.cmd reopens the latest batch or offline report.
The report leads with graphical matched-case comparisons and task/action stories. Raw metrics and
downloads are collapsed under Research details. “Test runs finished” means the agent returned a complete
run, not that the user's task was accomplished. Counts such as “0 of 1” describe the observed cases;
they do not establish the underlying security probability of a model.

Keys pass directly to the OpenAI client outside `ExperimentConfig`. Preferences use an explicit
allowlist of public fields. Error strings redact the supplied key and common `sk-…` patterns. Ollama
requests never receive the OpenAI key. The Show checkbox reveals only the in-memory entry when requested.

OpenAI's estimated budget is shared across the whole model batch. Local Ollama records zero **metered
API charge**, not zero hardware/energy cost. Custom remote Ollama/cloud-backed models may have their own
costs; those are not estimated here. Prices and provider billing can differ as documented in the README.

## Ollama adapter and research assumptions

The adapter uses native `/api/chat` tool calling, translates assistant/tool messages, converts developer
messages to the native system role, and returns a shared AgentDojo-compatible response. Native runtime
options explicitly set context size (`num_ctx`) and output allowance (`num_predict`). The configured
context must cover the conservative input bound, output allowance, and overhead. Native thinking is
model-default/on/off; OpenAI `reasoning_effort` is not silently reused for Ollama.

For the original tool-filter comparator, native Ollama receives available definitions in a text-only
selection block and no executable tools. This adapts upstream's OpenAI `tool_choice=none` request to
native chat. It is **not byte-identical prompting across providers** and must be reported as such.
The deterministic safeguards, simulated tools, and outcome evaluators are shared across providers.

Installed model digests/capabilities/details enter manifests. Changing a tag's digest changes its
experiment fingerprint. Unsupported models and inference errors never become successful defenses.
Small-model failures and missing coverage should be reported alongside completed-only rates.

Primary API documentation: [model listing](https://docs.ollama.com/api/tags),
[native chat](https://docs.ollama.com/api/chat), and
[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility).

## CLI examples

```powershell
# List models without inference:
.\.venv\Scripts\agent-eval.exe models --provider ollama

# Preview all compatible installed models without generation:
.\.venv\Scripts\agent-eval.exe batch --provider ollama --all-models --config configs/ollama-quick.json

# Run specific models and generate a comparison report:
.\.venv\Scripts\agent-eval.exe batch --live --provider ollama `
  --models llama3.2:latest qwen2.5:7b --config configs/ollama-quick.json --output runs/local-comparison

# Evaluate every compatible installed model:
.\.venv\Scripts\agent-eval.exe batch --live --provider ollama `
  --all-models --config configs/ollama-quick.json --output runs/all-local-models
```

CLI OpenAI credentials come from `OPENAI_API_KEY`, not a command-line key argument. Common CLI prices
apply to every selected model; use the GUI for different per-model prices. Identical batch reruns
resume completed episodes; scientific changes require a new folder. Single-model `run --live` also
accepts `--provider ollama --model <name> --config configs/ollama-quick.json`.
