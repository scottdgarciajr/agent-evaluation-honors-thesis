# Research protocol

## 1. Verify the code and source review

Read `literature-review.md`, `methodology.md`, and `policies.md` alongside the original proposal.
Run the offline checks and demo. Confirm that output fixtures are labeled and that denied calls
have no corresponding unauthorized tool effects. Examine examples of same-tool operand misuse.

## 2. Choose the model and affordable study size

Supply a model snapshot available to your API account and current token prices. Keep those settings
identical across conditions. Run the 54-episode development pilot with an explicit small cap. Review
errors, incomplete coverage, actual token use, estimated/provider cost, and time per episode before
projecting the full study. If the budget ends early, resume or report the partial pilot explicitly.

The full factorial held-out matrix is large. Before seeing held-out outcomes, choose either the full
matrix or a feasible deterministic sample, then save the exact task/injection IDs and conditions in a
new frozen JSON configuration. Preserve baseline-treatment pairs. Do not choose tasks because they
produce favorable security differences. Report the selection procedure and sample size in the thesis.

## 3. Review and freeze policies

Review each task scope using only its legitimate request. Mark unresolved operands and broad delegated
requests honestly. Correct policy bugs using development cases. Record setup/review time if it will be
analyzed; it is not inferred by this code. Freeze policies and the dependency lock before held-out runs.
No runtime rule can be added merely because it recognizes a held-out attack address or target.

## 4. Collect paired observations

Use a dedicated live output directory. The runner randomizes case blocks and condition order with
the split seed and records the full schedule. All condition blocks for a case remain together, but
budget limits can interrupt a block. Check matched-pair coverage before analysis. Repetitions use
distinct episode IDs, not a claim that the provider supports reproducible random seeds.

Monitor meaningful failures and cost. Completed records survive interruption. Resume only with the
same study settings, code, policies, and environment. Error retries are archived and included in the
budget ledger. Provider account billing can include activity outside this directory; audit it separately.

## 5. Analyze and inspect trajectories

Run `agent-eval analyze <run-directory>`. First inspect scheduled/recorded/completed counts and errors.
Then inspect suite/workflow/attack summaries, paired differences, cluster intervals, and attack-portfolio
coverage. Keep incomplete results separate. Check representative successes, blocked attacks, legitimate
tasks blocked by policy, and attacks that remain inside allowed tool/operand boundaries.

Inspect original and successful-dispatch trace scores when they disagree. The successful-dispatch
metric is supplemental. Payload exposure can be audited manually from retained messages; avoid
claiming the model resisted an injection it never encountered.

## 6. Write the empirical result

Report the model/snapshot, benchmark/package versions, task selection, policy assumptions, sample sizes,
repetitions, failure handling, denominators, intervals, approval burden, and estimated/observed costs.
Describe actual improvement or lack of improvement, not only the intended effect. Include examples of
utility sacrificed by conservative approvals. Never present the scripted demo as a measured result.

This protocol does not enroll human participants or authorize production enterprise deployment.
