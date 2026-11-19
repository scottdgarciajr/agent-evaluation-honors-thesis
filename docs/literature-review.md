# Proposal review and scholarly grounding

## Assessment

The proposal's central question is feasible: determine how much security simple rule-based runtime
controls provide while preserving useful work. AgentDojo supplies realistic simulated workflows,
attacker-controlled content, mutable state, and task-specific outcome checks. Extending it directly
keeps the baseline and secured agents comparable; a separate LangChain agent/environment would add
implementation differences and evaluator work without answering the central question more clearly.

The original proposal leaves metrics and several safeguards open. This implementation makes them
operational: a full factorial comparison of tool restriction, deployment constraints, and exact-scope
approval; task completion and attacker success measured separately; coverage/error reporting; approval
burden; and measured cost/timing. Workspace and banking provide cloud-drive, messaging, calendar,
account, and payment simulations. They do not implement the proposal's optional SQL/cloud deployment.

The strongest contribution is an empirical analysis of **simple controls, their combinations, and
their failure/utility costs under an explicit trusted-policy assumption**. It is not the invention of
tool filtering, task alignment, operation-level authorization, or provably secure information flow.
In particular, strong outcomes obtained by denying all dynamically specified sensitive actions must
be accompanied by their benign utility cost and policy-authoring assumptions.

## Literature matrix

All 14 scholarly PDFs supplied in `Sources/` are represented below. The two MHTML guidance documents
are considered separately. Published results describe each paper's own model, benchmark, and threat
model; they are not comparable leaderboard numbers for this implementation.

| Supplied source | Mechanism / threat model | Evaluation relevance and limitation | Role in this study |
|---|---|---|---|
| **Debenedetti et al. (2024), AgentDojo**, NeurIPS Datasets and Benchmarks. `NeurIPS-2024-…pdf` | Dynamic tool-using agents encounter injected external data. Extensible tasks, environments, attackers, and defenses. | Deterministic task/state checks avoid relying entirely on an LLM judge. Advance tool filtering cannot stop attacks achievable with the legitimate tools and can struggle with dynamic workflows. The released benchmark has evolved since the paper. | Core framework, baseline, existing filter comparator, independent utility/ASR, finite attack portfolio. |
| **Zhang et al. (2025), Agent Security Bench (ASB)**, ICLR. `ICLR-2025-…pdf` | Broader attacks across user inputs, tool outputs, memory, and planning; multiple application scenarios. | Wider coverage than the selected AgentDojo study, but different completion definitions and attacks. Required-tool-use success is not interchangeable with AgentDojo state/task success. | Taxonomy and threat-model boundary; do not combine its percentages with this benchmark. |
| **Liu et al. (2024), Formalizing and Benchmarking Prompt Injection Attacks and Defenses**, USENIX Security. `usenixsecurity24-liu-yupei.pdf` | Formalizes attacker-chosen injected tasks in application data; compares heuristic attacks and defenses. | Establishes that formatting, instructional prevention, and detection need empirical evaluation. Application-output settings differ from multi-step stateful agents; detection alone may leave the task uncompleted. | Motivation for independent utility measurement and multiple attack templates. |
| **Chen, Piet et al. (2025), StruQ**, USENIX Security. `usenixsecurity25-chen-sizhe.pdf` | Controlled prompt/data formatting plus special structured instruction training. | Requires frontend/model training changes; separation is more than adding delimiters. Protects a defined programmatic interface and has residual weaknesses against strong attacks. | Distinguish runtime rules from trained input-separation defenses. |
| **Chen, Zharmagambetov et al. (2025), SecAlign**, ACM CCS. `3719027.3744836.pdf` | Preference optimization on injected inputs with secure/insecure output pairs. | Training-based resistance with utility evaluation, rather than a permission enforcement layer. Does not establish complete security or unrestricted multi-turn generalization. | Explain why model retraining is outside this project's simple runtime-control scope. |
| **Liu et al. (2025), DataSentinel**, IEEE S&P / supplied arXiv version. `2504.11358v4.pdf` | Fine-tunes a detector through minimax optimization against adaptive attacks. Known-answer detection exploits failure to retain a randomly selected secret in output. | The intentionally susceptible detector is a distinct trained component. Detection needs a downstream response policy; its assumptions/results are not a guarantee about action authorization. | Distinguish injection detection from controlling tool execution; discuss false positives and adaptive testing. |
| **Chen et al. (2025), Can Indirect Prompt Injection Attacks Be Detected and Removed?**, ACL. `2025.acl-long.890.pdf` | Evaluates detection and segmentation/extraction removal on contaminated external documents. | Examines both identifying malicious instructions and post-detection recovery, with remaining over-defense and generalization issues. Document removal differs from stateful authorization. | Support reporting usability loss and the distinction between blocking a task and completing it safely. |
| **Jia et al. (2025), The Task Shield**, ACL. `2025.acl-long.1435.pdf` | LLM-mediated extraction and contribution checks align instructions/actions with user objectives. | Test-time AgentDojo defense with added LLM calls; depends on the checking model and can make extraction/scoring mistakes. | Close runtime comparison in related work. Our checker is deterministic policy evaluation, not an implementation of Task Shield's semantic alignment. |
| **Debenedetti et al. (2025), Defeating Prompt Injections by Design (CaMeL)**. `2503.18813v2.pdf` | Separates trusted planning/control from data; interpreter capabilities track provenance and enforce flow policies. | Stronger structural protection under specified assumptions. Explicit non-goals include some misleading textual outputs that do not violate protected flows. | Establish that immutable permissions alone are weaker than provenance-aware information-flow enforcement. No CaMeL-equivalent proof is claimed. |
| **Sharma et al. (2026), Beyond OAuth: Task-Scoped Authorization for AI Agents via Natural Language Slices (PAuth)**. `2603.17170v2.pdf` | Server-centric operation authorization, natural-language slices, and signed provenance envelopes; agent may be compromised. | Authorizing a tool is insufficient when its operands can be abused. Server reasoning/provenance infrastructure differs materially from a local deterministic guard. Treat the supplied version as a preprint unless its publication venue is independently confirmed. | Motivate same-tool/wrong-operand tests; avoid claiming operation-level authorization as novel. |
| **Dong et al. (2025), Memory Injection Attacks on LLM Agents via Query-Only Interaction (MINJA)**. `2503.03704v5.pdf` | Query-only interactions induce stored malicious reasoning records, including bridging steps and progressive shortening. | Cross-query memory poisoning requires memory persistence and retrieval assumptions absent from this single-episode design. | Clearly exclude persistent-memory protection claims; resetting episodes does not evaluate a memory defense. |
| **Liu et al. (2025), Make Agent Defeat Agent: Automatic Detection of Taint-Style Vulnerabilities in LLM-based Agents (AgentFuzz)**, USENIX Security. `usenixsecurity25-liu-fengyu.pdf` | Feedback-directed adversarial exploration of application paths to sensitive sinks. | Application vulnerability discovery, including code execution, differs from task-level prompt-injection outcome evaluation. | Separate vulnerabilities in tool implementations from malicious choices among simulated tools. |
| **Zhu et al. (2025), MELON**, ICML/PMLR. `zhu25z.pdf` | Masked re-execution compares next actions to identify reduced dependence on the user request. | Behavioral detection on AgentDojo with additional inference and special handling for false positives/negatives. | Add to the related-work discussion of runtime defense cost and utility tradeoffs; not implemented as a comparator here. |
| **Ye, Cui & Hadfield-Menell (2026), Prompt Injection as Role Confusion**, ICML/PMLR. `ye26b.pdf` | Role probes study perceived instruction source; fabricated reasoning can imitate higher-authority roles. | Mechanistic observations and CoT Forgery attacks do not imply that textual role tags alone establish an enforcement boundary. | Motivate forged-approval/permission stress tests; our templates are distinct and do not reproduce the paper's results. |

## Practical guidance

- **OpenAI (March 11, 2026), Designing AI agents to resist prompt injection** describes social-engineering
  style attacks and motivates limiting the consequences of manipulation, including capability limits.
  This supports execution controls but does not establish the effectiveness of this particular policy.
  [Official source](https://openai.com/index/designing-agents-to-resist-prompt-injection/).
- **OWASP, LLM Prompt Injection Prevention Cheat Sheet** advocates layered defenses, least privilege,
  action validation, human oversight, and testing. Treat it as engineering guidance, not a controlled
  experiment or evidence that any checklist guarantees safety.
  [Official source](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html).

## Recommended revisions to the supplied related-work draft

1. Add MELON and role-confusion work, which are in the source collection but not developed in the draft.
2. State the threat model before comparing methods: trusted request/policy, attacker-controlled external
   content, simulated tools, no persistent memory, and no compromised Python runtime.
3. Explain StruQ's programmatic prompt/data interface requirement precisely; avoid implying that it
   cannot follow legitimate user instructions. Its limitation concerns interface and training assumptions.
4. Describe DataSentinel's key-presence decision and trained detector separately from the prompt's
   instruction to repeat a key. Do not imply that an exact once-only output check is the entire method.
5. Contextualize the draft's quoted AgentDojo tool-filter percentage as a result for that paper's specific
   model and attack configuration. The thesis must measure the chosen model/version anew.
6. Distinguish empirical action-policy enforcement from semantic intent checking and formal information-flow
   guarantees. Include the extra trusted policy information and unresolved-operand denial in limitations.
7. Avoid equating attacks that meet a whole benchmark goal with all unauthorized actions. Retain separate
   policy-violation counts and requested-versus-executed records.

## Primary references

1. Debenedetti et al. (2024). *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and
   Defenses for LLM Agents*. [arXiv:2406.13352](https://arxiv.org/abs/2406.13352).
2. Zhang et al. (2025). *Agent Security Bench (ASB): Formalizing and Benchmarking Attacks and Defenses
   in LLM-Based Agents*. ICLR. [Authors' repository](https://github.com/agiresearch/ASB).
3. Liu et al. (2024). *Formalizing and Benchmarking Prompt Injection Attacks and Defenses*. USENIX Security.
   [Proceedings](https://www.usenix.org/conference/usenixsecurity24/presentation/liu-yupei).
4. Chen et al. (2025). *StruQ: Defending Against Prompt Injection with Structured Queries*. USENIX Security.
   [Proceedings](https://www.usenix.org/conference/usenixsecurity25/presentation/chen-sizhe).
5. Chen et al. (2025). *SecAlign: Defending Against Prompt Injection with Preference Optimization*. CCS.
   [DOI](https://doi.org/10.1145/3719027.3744836).
6. Liu et al. (2025). *DataSentinel: A Game-Theoretic Detection of Prompt Injection Attacks*.
   [Supplied version](https://arxiv.org/abs/2504.11358).
7. Chen et al. (2025). *Can Indirect Prompt Injection Attacks Be Detected and Removed?* ACL.
   [Proceedings](https://aclanthology.org/2025.acl-long.890/).
8. Jia et al. (2025). *The Task Shield: Enforcing Task Alignment to Defend Against Indirect Prompt
   Injection in LLM Agents*. ACL. [Proceedings](https://aclanthology.org/2025.acl-long.1435/).
9. Debenedetti et al. (2025). *Defeating Prompt Injections by Design*.
   [Supplied version](https://arxiv.org/abs/2503.18813).
10. Sharma et al. (2026). *Beyond OAuth: Task-Scoped Authorization for AI Agents via Natural Language Slices*.
    [Supplied version](https://arxiv.org/abs/2603.17170).
11. Dong et al. (2025). *Memory Injection Attacks on LLM Agents via Query-Only Interaction*.
    [Supplied version](https://arxiv.org/abs/2503.03704).
12. Liu et al. (2025). *Make Agent Defeat Agent: Automatic Detection of Taint-Style Vulnerabilities in
    LLM-based Agents*. USENIX Security.
    [Proceedings](https://www.usenix.org/conference/usenixsecurity25/presentation/liu-fengyu).
13. Zhu et al. (2025). *MELON: Provable Defense Against Indirect Prompt Injection Attacks in AI Agents*.
    ICML/PMLR. [Authors' repository](https://github.com/kaijiezhu11/MELON).
14. Ye, Cui & Hadfield-Menell (2026). *Prompt Injection as Role Confusion*. Supplied ICML paper `ye26b.pdf`.

The PDFs in the workspace are the source versions reviewed. Do not infer that a paper's broad title
or abstract claim applies without its stated assumptions and evaluation conditions.
