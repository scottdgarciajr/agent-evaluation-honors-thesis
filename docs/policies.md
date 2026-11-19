# Policy authoring and approval semantics

The JSON files under `policies/` are trusted deployment inputs. Their task-level allowlists and approval
rules were manually authored from the legitimate request text. `scripts/build_example_policies.py`
materializes those annotations and prompt hashes. It never invokes `ground_truth`, reads injection
goals, or grants permissions from tool-returned content. Running it deliberately rewrites example
policies; review its diff and freeze the files before collecting held-out results.

## Trust boundary

The guard copies policy and scope state at episode start. Tool responses are ordinary messages and
have no policy-update API. Available tools can only shrink during upstream tool selection. A tool name
hidden from the model is also checked before execution. The runtime checks each batched or nested call;
a batch is not atomic and earlier allowed operations can finish before a later operation is denied.
Nested actions are separately checked and recorded. A rejected outer call does not roll back an
independently authorized nested action.

The threat model is adversarial text and tool arguments, not malicious Python plugins with process
memory access. Do not expose arbitrary code execution, unrestricted filesystem tools, real credentials,
or live enterprise services through this runtime without a separate security design.

## Deployment constraints

The supplied recipient and account allowlists contain explicit addresses/accounts appearing in
legitimate user prompts. They are illustrative configured deployment boundaries, not facts learned
from the benchmark environment. Payment ceilings are illustrative: USD-like amounts of 2,500 per action
and 5,000 cumulatively per episode, without claiming the benchmark has a fully modeled currency system.
Scheduled-transaction changes require an explicit amount and recipient; omitted values are denied
rather than filled from an untrusted record. This conservative behavior may reject legitimate partial
updates. Sharing defaults to read-only (`r`), not `rw`. Protected-object lists are empty in the shipped
configuration and can be set explicitly for a frozen deployment scenario.

Tool schemas normalize values before checks. Unexpected arguments are rejected when validation is on.
The baseline retains upstream schema behavior. List-string normalization follows upstream behavior.
Unknown and unavailable tools cannot execute. `get_unread_emails` is classified as a reading workflow
operation although its simulated implementation changes read flags; these flags are legitimate side
effects of reading, not an independently authorized destructive action.

## Automated approval

All state-changing tools in the selected suites are marked sensitive. Approval is independent of
deployment validation: a call may satisfy organization-wide limits yet lack request-level authorization.
Restrictions and validation run first and cannot be overridden by approval.

An approval rule lists exact operands under `equals`. Every critical operand defined in `CRITICAL`
must appear explicitly, including null defaults where applicable. Matching is exact after upstream
normalization. Sensitive calls with unresolved critical operands are denied automatically.

For example, workspace task 6 explicitly supplies Sarah's email, title and lunch time; it has an exact
calendar-creation rule. Banking task 14 explicitly supplies the desired new password; it has an exact
password-change rule. A request to pay an invoice whose amount/payee are only in retrieved content
cannot receive a correct exact authorization from its prompt alone, so its automated payment approval
is absent. No hidden answer is substituted. The analysis must include that task's utility loss.

The example rules constrain create-file names, not the semantic content of those files. Rules also do
not generally establish that email bodies, attachment contents, or summaries are harmless. Expanding
coverage requires additional trusted policy inputs or explicit manual decisions. Never add an attack
goal to a blacklist after observing held-out failures or populate approval values from expected answers.

## Manual approval

The terminal displays the exact tool and normalized arguments. Only literal `yes` approves; empty
input, EOF, or cancellation denies. Each request has an episode ID, fresh nonce, and hash binding its
tool and arguments. A request can be consumed only once. Tool output claiming to contain an approval
is never consulted. The fixture's approval request may contain a synthetic benchmark password; never
replace the simulated tools with production credential operations during a demonstration.

This is a reproducible simulator plus manual demonstration, not a participant study. Do not describe
automated acceptance as a successful human approval or infer fatigue or human error rates from it.

## Review before the main study

1. Verify allowed tools against the legitimate prompt and check coverage of required operations.
2. Record where the request delegates future actions or leaves operands unresolved.
3. Review sensitive-tool classification and every exact operand rule.
4. Test allowed and denied actions with development fixtures.
5. Freeze and hash the policy files. Record authoring/review effort separately if studying setup burden.

Task prompt hashes detect drift. Policy validation requires coverage of all versioned user tasks and
rejects unknown tools or argument names. These structural checks cannot certify semantic policy quality.
