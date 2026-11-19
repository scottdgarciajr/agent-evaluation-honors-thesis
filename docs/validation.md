# Validation record

Verified locally on November 17, 2026 with Windows, CPython 3.12.2, AgentDojo 0.1.35,
and the versions in `requirements-lock.txt`.

| Check | Observed result |
|---|---|
| `python -m pytest -q` | 60 tests passed |
| `python -m ruff check src tests scripts` | Passed |
| `python -m pip check` | No broken requirements |
| `python scripts/preflight_payloads.py` | 474 payload/environment combinations validated without model calls |
| `agent-eval demo --output runs/verified-demo` | 32 scripted episodes completed |
| `agent-eval analyze runs/verified-demo` | CSV, JSON, Markdown, PNG, and PDF outputs generated |
| Chart inspection | Labels, axes, and explicit offline-fixture warning inspected |
| `agent-eval doctor` | Both selected benchmark suites imported with expected counts |
| One-click PowerShell launcher invoked from outside the project | Environment checks, 39 tests, 474 payload checks, 32 episodes and report generation passed |
| HTML report local links | All download and episode links resolved to existing files |
| Latest-results launcher (`-Mode Results -NoOpen`) | Reopened the correct report path from outside the project |
| Ollama discovery | 15 installed models found; 8 advertised tool calling |
| Native Ollama tool smoke test | `llama3.2:latest` called an addition tool and consumed its returned result |
| Real AgentDojo evaluation launched through GUI | All 4 quick-check episodes completed on `llama3.2:latest`; zero metered API cost |
| Native GUI interaction | Select-all chose the 8 compatible models; progress, completion log and result path displayed |
| Simplified native results tab | Graphs, count labels, model selector and plain-language explanations visually inspected |
| Human-readable comparison calculations | Tests distinguish run completion, task success, attacker success, unknown outcomes, and matched-case coverage |

The payload preflight crosses every user task with one reference injection goal and every injection
goal with one reference user task for each of six attack templates. It is a local compatibility check,
not the full attack matrix or an LLM robustness experiment. Model transport, resumption, and budget
behavior are exercised with mocked responses; no paid model calls were made during validation.

The additional provider/GUI tests cover native message/tool-result translation, explicit context limits,
tool capability discovery, local runs without OpenAI keys, zero local API metering, total OpenAI budgets
shared across models, cancellation before requests, endpoint credential rejection, error redaction, and
public preferences excluding keys. The real local quick check generated a comparison and detailed
reports in `runs/gui-20261118-003544Z-a54fe8/`. This is a functional check with one task, not research-scale
evidence for security or utility differences. No paid OpenAI evaluations were performed.

The offline fixture forces specific proposed actions. Its charts verify the report pipeline and guard
behavior under those scripts. They do not measure susceptibility or real-model defense effectiveness.
The original planning documents and source files were not modified.

The browser report adds suite/condition filters, readable safeguard names, embedded charts and
expandable action decisions. HTML escaping is tested against script content and template-token text.
Browser visual inspection was attempted but stopped by the computer-use tool because it could not
verify Chrome's current URL. No browser security settings were changed or bypassed. The report and
its links were verified through local generation and checks; automatic browser opening remains a
user-facing launcher action.
