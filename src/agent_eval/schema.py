from __future__ import annotations

import hashlib
import json
from itertools import product
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Condition(StrictModel):
    name: str
    restriction: bool = False
    validation: bool = False
    approval: bool = False
    upstream_filter: bool = False


CONDITIONS = {
    f"r{int(r)}v{int(v)}a{int(a)}": Condition(
        name=f"r{int(r)}v{int(v)}a{int(a)}", restriction=r, validation=v, approval=a
    )
    for r, v, a in product([False, True], repeat=3)
}
CONDITIONS["upstream_tool_filter"] = Condition(name="upstream_tool_filter", upstream_filter=True)


class ApprovalRule(StrictModel):
    """Explicit required operands; unconstrained text fields remain a documented limitation."""

    tool: str
    equals: dict[str, Any] = Field(default_factory=dict)
    # A rule must explicitly name every security-critical operand, even if an empty list.


class TaskScope(StrictModel):
    prompt_sha256: str
    allowed_tools: tuple[str, ...]
    approvals: tuple[ApprovalRule, ...] = ()
    notes: str
    workflow: Literal["read_only", "state_changing"]


class WorkflowPolicy(StrictModel):
    suite: Literal["workspace", "banking"]
    provenance: str
    sensitive_tools: tuple[str, ...]
    allowed_recipients: tuple[str, ...] = ()
    allowed_accounts: tuple[str, ...] = ()
    max_payment: float = Field(default=2500, gt=0)
    max_total_payments: float = Field(default=5000, gt=0)
    sharing_permissions: tuple[str, ...] = ("r",)
    protected_file_ids: tuple[str, ...] = ()
    protected_email_ids: tuple[str, ...] = ()
    tasks: dict[str, TaskScope]


class ExperimentConfig(StrictModel):
    benchmark_version: Literal["v1.2.2"] = "v1.2.2"
    suites: tuple[Literal["workspace", "banking"], ...] = ("workspace", "banking")
    conditions: tuple[str, ...] = tuple(CONDITIONS)
    attacks: tuple[str, ...] = ("ignore_previous", "injecagent", "important_instructions", "tool_knowledge")
    repetitions: int = Field(default=3, ge=1)
    split: Literal["dev", "test", "all"] = "test"
    split_seed: int = 20261117
    dev_fraction: float = Field(default=0.2, gt=0, lt=1)
    task_ids: tuple[str, ...] = ()
    injection_ids: tuple[str, ...] = ()
    include_benign: bool = True
    policy_paths: dict[str, str] = Field(
        default_factory=lambda: {"workspace": "policies/workspace.json", "banking": "policies/banking.json"}
    )
    model: str | None = None
    provider: Literal["openai", "ollama"] = "openai"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_context_tokens: int | None = Field(default=None, ge=512)
    ollama_think: bool | None = None
    request_timeout_seconds: float = Field(default=180, gt=0)
    temperature: float | None = 0.0
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    max_steps: int = Field(default=15, ge=1)
    max_tool_calls: int = Field(default=40, ge=1)
    max_input_tokens: int = Field(default=32000, ge=256)
    max_output_tokens: int = Field(default=2048, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    input_usd_per_million: float | None = Field(default=None, gt=0)
    output_usd_per_million: float | None = Field(default=None, gt=0)
    max_episodes: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_matrix(self):
        if not self.suites or not self.conditions or len(set(self.conditions)) != len(self.conditions):
            raise ValueError("Suites and unique conditions are required")
        if set(self.conditions) - CONDITIONS.keys():
            raise ValueError("Unknown condition")
        allowed = {
            "ignore_previous",
            "injecagent",
            "important_instructions",
            "tool_knowledge",
            "forged_approval",
            "permission_escalation",
        }
        if set(self.attacks) - allowed:
            raise ValueError("Unknown attack")
        for items in [self.suites, self.attacks, self.task_ids, self.injection_ids]:
            if len(set(items)) != len(items):
                raise ValueError("Duplicate matrix entries")
        if self.provider == "ollama":
            from agent_eval.providers import endpoint_url

            endpoint_url(self.ollama_url)
            if self.reasoning_effort is not None:
                raise ValueError(
                    "Use ollama_think for native Ollama runs; reasoning_effort is an OpenAI setting"
                )
            minimum = self.max_input_tokens + self.max_output_tokens + 2048
            if self.ollama_context_tokens is not None and self.ollama_context_tokens < minimum:
                raise ValueError(f"Ollama context must be at least {minimum} for these input/output bounds")
        return self


class PolicyDecision(StrictModel):
    outcome: Literal["allow", "deny"]
    stage: str
    reason: str


class ApprovalRequest(StrictModel):
    episode_id: str
    nonce: str
    tool: str
    args: dict[str, Any]
    request_sha256: str


class ActionEvent(StrictModel):
    sequence: int
    tool: str
    proposed_args: dict[str, Any]
    normalized_args: dict[str, Any] | None = None
    status: Literal["proposed", "denied", "executed", "failed"]
    stage: str
    reason: str
    approval_requested: bool = False
    approval_granted: bool | None = None
    policy_violation: bool = False
    duration_seconds: float = 0
    policy_seconds: float = 0
    approval_wait_seconds: float = 0


class EpisodeSpec(StrictModel):
    suite: str
    user_task: str
    injection_task: str | None
    attack: str | None
    condition: str
    repetition: int
    split: str

    @property
    def key(self) -> str:
        return digest(self)


class EpisodeResult(StrictModel):
    schema_version: int = 1
    experiment_sha256: str
    episode_id: str
    spec: EpisodeSpec
    status: Literal["completed", "api_error", "error", "incomplete", "budget_exhausted"]
    workflow: str
    policy_sha256: str
    payload_sha256: str
    environment_sha256: str | None = None
    upstream_utility: bool | None = None
    upstream_attacker_success: bool | None = None
    upstream_security_raw: bool | None = None
    execution_utility: bool | None = None
    execution_attacker_success: bool | None = None
    trace_evaluator: bool = False
    messages: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[ActionEvent] = Field(default_factory=list)
    injections: dict[str, str] = Field(default_factory=dict)
    requests: list[dict[str, Any]] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd_estimate: float = 0
    duration_seconds: float = 0
    error: str | None = None
