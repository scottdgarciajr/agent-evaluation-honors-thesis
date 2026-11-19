# Methodology

## Research questions

1. How do deterministic tool restrictions, deployment-level action validation, and approval affect
   attacker success and legitimate task completion, individually and together?
2. How much protection remains when an attacker uses a tool that the legitimate workflow also permits?
3. What utility loss, approval burden, and computational overhead accompany the controls?

The hypothesis is that layered controls reduce unauthorized effects, particularly where tool filtering
alone permits the relevant tool, with an associated cost in some legitimate workflows. A null result,
severe utility loss, or failure against a same-tool attack remains a valid empirical finding.

## Benchmark and experimental conditions

Use AgentDojo **0.1.35**, benchmark **v1.2.2**, with 40 workspace and 16 banking user tasks and 14/9
injection goals respectively. These versioned counts differ from the original 2024 paper. The code
enumerates installed task IDs rather than assuming a historical case count.

Conditions `r0v0a0` through `r1v1a1` enumerate every combination of restriction (r), validation (v),
and approval (a). `r0v0a0` is the baseline. A ninth condition uses the released AgentDojo LLM tool
filter without the research safeguards. All conditions use the same model, system message, tool
format, iteration/call limits, and initial state for each case. Successful valid-tool baseline
trajectories are tested for parity with native AgentDojo.

Restriction uses a curated trusted task scope. Validation applies deployment policies independently
of the task: allowed recipients/accounts, payment ceilings, sharing permissions, protected objects,
and unexpected-argument rejection. Approval applies exact critical-operand constraints for sensitive
operations. The three controls may overlap; their effects need not be additive. The curated tool
restriction is not the same mechanism as AgentDojo's LLM-inferred filter.

The model still sees untrusted tool content. Immutable policy state prevents tool content from granting
new permissions; it does not ensure that every permitted action is semantically faithful to the user.
Text contamination, harmful content sent to an allowed recipient, and malicious actions within
unconstrained operands can remain possible. Do not claim general injection immunity or CaMeL-style
information-flow guarantees.

## Splits and freezing

Within each suite, sort user task IDs, shuffle with Python's `Random` seeded from
`"20261117:<suite>"`, and reserve the first ceiling(20% of tasks) for development. All injection cases
and repetitions for a user task stay in that task's split. There are 8 workspace and 4 banking
development tasks. The split is by task, not by individual trajectory or injection payload.

The shipped scopes were written using only legitimate prompts, including held-out prompts as
configuration inputs. This is not an unseen-request generalization study: the deployment receives
trusted per-request scopes. No attack goals, hidden answer keys, or ground-truth tool sequences
are used to grant defender permissions. This distinction must be explicit in the thesis.

Inspect policy correctness and tune only on development outcomes. Before the main study, freeze code,
dependency lock, task selection, policies, model ID, generation settings, attack portfolio, and pricing
metadata. Manifests hash them. The evaluator and attacker may access benchmark ground truth; the
defender's policy module cannot. The original public benchmark may also be present in model training;
the study cannot rule out contamination.

The complete held-out design has 61,236 episodes (three repetitions, nine conditions, four attacks,
all versioned injection goals, and one benign case per task). Enumerate before running. A limited
budget may require a smaller preregistered task/attack sample. Document that selection before observing
held-out results; a partially finished full matrix has missing coverage and is not a complete study.

## Attacks

The primary portfolio uses AgentDojo's `ignore_previous`, `injecagent`, `important_instructions`, and
`tool_knowledge` attacks. Candidate injection locations follow upstream attacker-side ground-truth
reachability logic. The tool-knowledge attack also uses attacker ground truth as designed upstream.
None of this data enters defender policies.

Upstream attack constructors recognize a fixed historical model-name enumeration. The adapter uses a
constructor-only name proxy for unsupported model IDs and then sets the prose identity to "OpenAI
assistant" for OpenAI or "AI assistant" for Ollama. Recognized IDs retain the upstream identity. This change is recorded here and payload
hashes allow auditing; it is not an exact reproduction of the paper's old-model experiments.

Ollama evaluations use native tool calling with model digests and context/generation options recorded.
Native role/message formatting and the text-only upstream-filter adapter differ from OpenAI's API
representation; cross-provider comparisons must acknowledge these backend differences. Multi-model
batches share scenario configurations and run sequentially. Quick-check results establish integration,
not a statistically meaningful security ranking. See `providers-and-gui.md`.

Additional `forged_approval` and `permission_escalation` templates test specific policy boundaries.
They are custom stress tests, not reproductions of the role-confusion paper's attack. Unit/integration
tests also force harmful same-tool arguments to test the guard independently of model susceptibility.

Payload generation is independent of condition. Agents may take different trajectories and may never
encounter a particular payload; report this as an exposure limitation rather than evidence of rejection.
The current logs retain payloads and messages for manual exposure audit; there is no automatic exposure
classifier. The finite portfolio's any-success outcome is not a claim of optimal adaptive attack strength.

## Outcomes and denominators

Primary outcomes preserve upstream evaluator semantics:

- **Benign utility:** completed benign episodes with upstream utility true / completed benign episodes.
- **Utility under attack:** completed attack episodes with upstream utility true / completed attack episodes.
- **Targeted ASR:** completed attack episodes with upstream attacker success true / completed attack episodes.
- **Safe completion:** utility true and attacker success false / completed attack episodes.

AgentDojo's variable called `security` is true when the injection goal succeeds. For benign runs its
true value is a sentinel, stored only as `upstream_security_raw`; attacker success is null.
Upstream utility can impose task-specific side-effect constraints; retain its original meaning and
report safe completion separately rather than assuming all evaluators share identical semantics.

Some evaluators examine proposed-call traces. The runner preserves original scores and separately
evaluates the same functions with successfully dispatched calls. These `execution_*` scores are a
declared supplemental interpretation, not a replacement benchmark. Tool errors can in principle follow
partial mutation; retained final-state evaluators still observe effects. A successful dispatch is not
proof of arbitrary real-service transactional semantics.

Every episode records completion status. API errors, budget stops, local input limits, truncation,
pending calls, and iteration/call exhaustion do not count as successful defenses. Summary CSVs report
completed/attempted coverage, status counts, and lower/upper bounds assigning missing attempted
outcomes all failures/all successes. Overall schedule coverage includes unattempted episodes. Do not
interpret completed-only rates without this coverage.

Policy-violation counts refer to the declared deployment constraints and task tool scope, evaluated
counterfactually in every condition. They are distinct from benchmark attacker-goal success. They do
not establish the intent of arbitrary text or identify every unauthorized act. A benign denial is not
automatically a false positive: an injected or erroneous action may arise even on a benign input.

## Statistical analysis and overhead

Report suite, workflow (read-only/state-changing), split, attack, and condition breakdowns. Pooled
charts are descriptive. Pair treatment and baseline on suite, user task, injection task, attack, and
repetition, using only pairs where both runs completed. Deltas are treatment minus baseline. A negative
benign utility delta measures task-completion loss, not an action-level false-positive rate.

Use 2,000 bootstrap resamples of whole user tasks for 95% percentile intervals, retaining within-task
case/repetition dependence. Suppress intervals for fewer than two task clusters. These are descriptive
intervals with no multiple-testing correction or confirmatory significance claims. Three repetitions
do not create three independent tasks. Provider nondeterminism remains even at temperature zero.

Report approval requests and denials, model tokens, estimated cost, request and episode duration,
policy-check time, and manual approval wait separately. Action-boundary duration includes dispatch;
policy time subtracts measured dispatch/nested time and manual wait. Timing includes instrumentation
and Python overhead. Costs use user-supplied rates and conservative reservations for unknown usage.
Raw provider billing is authoritative.

## Limitations

These are simulated enterprise workflows, not a deployment or evaluation of actual cloud IAM, SQL,
storage APIs, or production data. Policies are manually specified and intentionally conservative.
Dynamic operands often require human clarification; automatic denial can sharply reduce utility.
The study does not evaluate participant decision quality, memory poisoning, training defenses,
multimodal agents, or long-term cross-session attacks. Its result is conditional on model, version,
policy coverage, attack portfolio, and task selection.
