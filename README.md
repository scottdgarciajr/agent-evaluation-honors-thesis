# AgentDojo runtime safeguard evaluation

[![Offline validation](https://github.com/scottdgarciajr/agent-evaluation-honors-thesis/actions/workflows/tests.yml/badge.svg)](https://github.com/scottdgarciajr/agent-evaluation-honors-thesis/actions/workflows/tests.yml)

Research code for **Evaluating Security Mechanisms for Tool-Using LLM Agents in Cloud-Based Enterprise Systems**.
The package extends AgentDojo 0.1.35 and benchmark version v1.2.2. All enterprise tools operate on
AgentDojo's simulated state. Only an explicitly requested live run contacts the OpenAI model API.

The study compares deterministic tool restriction, argument validation, and sensitive-action approval
individually and in all combinations, plus AgentDojo's original LLM tool filter.

## Get the project

```powershell
git clone https://github.com/scottdgarciajr/agent-evaluation-honors-thesis.git
cd agent-evaluation-honors-thesis
```

On Windows with Python 3.12 installed, double-click **Open Research GUI.cmd**. The launcher sets up
the environment on first use. Ollama runs need a running Ollama server and an installed tool-capable
model. OpenAI runs need your own API key. The public repository contains code, example configurations,
tests, and methodology documentation. Original literature PDFs, private planning documents, local
settings, credentials, and generated evaluation outputs are excluded. The code runs without those PDFs;
the literature review links to the cited publications.

## Easiest way to run and see results

**Double-click `Open Research GUI.cmd`** for the desktop console:

1. Choose **Ollama** or **OpenAI**. Ollama connects automatically to your local server.
2. Check individual models or **Select all compatible**. For OpenAI, enter your masked API key,
   refresh the account model list (or add an ID), and apply verified token prices to selected models.
3. Choose **Try it out** and click **Start comparison**.
4. The **Understand the results** tab opens when testing finishes. It explains useful work, attacker
   goals, and the effect of protections with count-based graphs. Click the task/actions button for details.

The setup screen shows usable models first and hides technical controls. Existing saved results can be
opened from **Understand my results** without running anything again. The browser report uses the same
graphs and explanations; raw scores, condition codes, and downloads sit under **Research details**.

API keys stay in memory and are excluded from saved preferences and experiment records. Public settings
remember the provider, server, preset, and per-model prices. The OpenAI budget is shared across selected
models. Ollama requires no OpenAI key or token prices. Models run sequentially; no downloads occur.
Non-tool and embedding models remain visible but are excluded from Select all compatible.

Quick check runs **4 development episodes per model** to test integration. Pilot runs **54**. Main study
is much larger. Advanced settings expose context/output limits, timeout, temperature, thinking, and
episode caps. Stop waits for the current bounded request and preserves completed work.

See [Ollama and GUI details](docs/providers-and-gui.md) for CLI examples and research assumptions.

Double-click **Run Test Evaluation.cmd** in this folder. It checks the environment, runs the automated
tests and payload checks, evaluates 32 scripted scenarios, and opens a visual HTML results report in
your browser. It creates the Python environment if needed. The first setup requires Python 3.12 and
internet access for dependencies. Subsequent offline tests need no API key and incur no model charges.

Double-click **View Results.cmd** to reopen the latest successful report. Every evaluation gets a new
timestamped folder, so rerunning does not collide with older code/configuration hashes. Reports include
charts, readable safeguard names, suite/condition filters, individual tool decisions, and CSV downloads.
The offline warning distinguishes software checks from research evidence about an actual LLM.

For the actual model pilot, double-click **Run Live Pilot.cmd**. It asks for your model ID, verified
token prices, and a hidden API key if one is not already in your environment. The default estimated
budget cap is $5. The key is not saved. To control settings from PowerShell:

```powershell
.\scripts\run-evaluation.ps1 -Mode Test
# Quick scripted evaluation after checks have already passed:
.\scripts\run-evaluation.ps1 -Mode Test -SkipChecks
# Inspect results without launching a browser:
.\scripts\run-evaluation.ps1 -Mode Results -NoOpen
```

Use the `.cmd` launchers if PowerShell's script execution policy blocks direct invocation. Setup/check
failures and failed offline episodes stop the workflow without replacing the latest report pointer.
Partial live runs still produce a report that explicitly shows their missing coverage.

## Get started on Windows

Run commands from this repository's root in PowerShell. Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\agent-eval.exe doctor
.\.venv\Scripts\agent-eval.exe validate --config configs/pilot.json
.\.venv\Scripts\python.exe -m pytest -q
```

The dependency lock includes development and analysis tools. To resolve fresh dependencies instead,
use `python -m pip install -e '.[dev]'` inside the virtual environment; record a new lock and use a new
run directory before collecting research data.

## Offline demonstration

```powershell
.\.venv\Scripts\agent-eval.exe demo --output runs/offline-demo
.\.venv\Scripts\agent-eval.exe analyze runs/offline-demo
.\.venv\Scripts\agent-eval.exe demo --manual --output runs/manual-demo
```

The demo exercises eight factorial conditions on four scripted scenarios using real AgentDojo tools
and evaluators. The manual mode presents one benign password-change request for terminal approval.
**These are integration fixtures, not measurements of an LLM's robustness.** Analysis artifacts and
charts are explicitly labeled. Use a new directory after changing code or policies.

## Inspect the study before spending money

```powershell
.\.venv\Scripts\agent-eval.exe tasks --config configs/main.json
.\.venv\Scripts\agent-eval.exe enumerate --config configs/pilot.json
.\.venv\Scripts\agent-eval.exe enumerate --config configs/main.json
```

The pilot schedules **54 episodes**, covering workspace task 8 and banking task 8, all nine conditions,
benign inputs, and two attacks against injection goal 0. One is a state-changing calendar workflow and
one is a read-only banking workflow. Both are in the development split. This pilot checks execution,
cost, and scoring; it is too small to establish comparative efficacy.

The full held-out matrix schedules **61,236 episodes**. This is a workload specification, not a
recommendation to spend that amount. Measure the pilot first, then create and freeze an affordable
configuration. If reducing scope, select tasks without consulting held-out outcomes, preserve paired
conditions, and document the selection and resulting limitations. `max_episodes` bounds each invocation;
budget exhaustion can stop sooner. Partial runs expose unattempted coverage and must not be reported
as the full study.

## Run a paid pilot

Set `OPENAI_API_KEY` in your environment. No `.env` file is loaded automatically and credentials are
never written into experiment records. Supply an available model ID, preferably a dated snapshot,
and its current input/output prices in USD per million tokens.

```powershell
# Replace these placeholders with your chosen model and its verified prices.
$modelId = 'YOUR_MODEL_SNAPSHOT'
$inputPrice = [double](Read-Host 'Verified input price in USD per million tokens')
$outputPrice = [double](Read-Host 'Verified output price in USD per million tokens')
.\.venv\Scripts\agent-eval.exe run --live --config configs/pilot.json `
  --output runs/pilot --model $modelId --max-cost-usd 5 `
  --input-usd-per-million $inputPrice --output-usd-per-million $outputPrice
.\.venv\Scripts\agent-eval.exe analyze runs/pilot
```

Prices must be positive. Prices are user-provided estimates; set a
provider-side spending limit too if a strict billing ceiling is required. A serialized UTF-8 byte bound
plus overhead screens inputs, a completion-token limit bounds outputs, and the runner reserves the
configured maximum request cost before each request. Failed requests retain their reservation because
their usage is unknown. Actual provider billing, cached-token discounts, and tokenizer/server overhead
can differ from the estimator. Model parameters are fixed across conditions; set `temperature: null`
or an appropriate `reasoning_effort` in your config if your chosen model requires it. Unsupported
parameters fail visibly rather than silently changing the experiment.

Rerun the same command, or use `resume` with identical arguments, to skip completed episodes and retry
incomplete/error episodes. Previous unsuccessful attempts are retained under `attempts/`; their cost
remains in the persistent budget ledger. Increasing `max_cost_usd` or changing the invocation episode
cap is allowed. Changing model, prices, policies, code, dependencies, or scientific settings requires
a new output directory. Use `run` without `--live` for a dry enumeration.

## Results and study documents

Each output directory contains a manifest, full schedule, budget ledger for live runs, and one JSON
record per episode. Records preserve payloads, messages, action decisions, actual dispatches, upstream
scores, execution-trace scores, token usage, request metadata, errors, and timing.

`analyze` produces `summary.csv`, `paired_differences.csv`, `attack_portfolio.csv`, `episodes.csv`,
`results.json`, `report.md`, a browser-ready `report.html`, and PNG/PDF charts. Rates use completed episodes; reports expose missing
coverage and attempted-episode bounds. A failed API request is never a successful defense. View
task-cluster uncertainty and paired coverage before drawing conclusions from pooled charts.

- [Methodology](docs/methodology.md): questions, comparisons, denominators, splits, limits.
- [Policy authoring](docs/policies.md): trust boundary, setup assumptions, approval simulator.
- [Proposal review and literature matrix](docs/literature-review.md): scholarly grounding and contribution.
- [Architecture](docs/architecture.md): interfaces and data flow.
- [Research protocol](docs/research-protocol.md): steps to freeze and conduct the study.
- [Validation record](docs/validation.md): checks completed and what they establish.

The input planning PDFs and source collection are preserved. No live model evaluation results are
included or implied by the offline fixtures.
