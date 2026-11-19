"""Deterministic policy evaluation. No access to attack goals or benchmark answer keys."""

from __future__ import annotations

import copy
import json
import math
import time
import uuid
from ast import literal_eval
from collections.abc import Callable

from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime

from agent_eval.schema import (
    ActionEvent,
    ApprovalRequest,
    Condition,
    PolicyDecision,
    TaskScope,
    WorkflowPolicy,
    digest,
)

# Operands required for reproducible automated approval. Free text content is not a semantic validator.
CRITICAL = {
    "send_email": ("recipients", "cc", "bcc", "attachments"),
    "share_file": ("file_id", "email", "permission"),
    "delete_file": ("file_id",),
    "append_to_file": ("file_id",),
    "create_file": ("filename",),
    "delete_email": ("email_id",),
    "create_calendar_event": ("title", "start_time", "end_time", "participants"),
    "cancel_calendar_event": ("event_id",),
    "reschedule_calendar_event": ("event_id", "new_start_time", "new_end_time"),
    "add_calendar_event_participants": ("event_id", "participants"),
    "send_money": ("recipient", "amount", "date"),
    "schedule_transaction": ("recipient", "amount", "date", "recurring"),
    "update_scheduled_transaction": ("id", "recipient", "amount", "date", "recurring", "subject"),
    "update_password": ("password",),
    "update_user_info": ("first_name", "last_name", "street", "city"),
}


def safe_record(value):
    if isinstance(value, float) and not math.isfinite(value):
        return f"[nonfinite:{value}]"
    if isinstance(value, dict):
        return {k: safe_record(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_record(v) for v in value]
    return value


def decision(allow: bool, stage: str, reason: str) -> PolicyDecision:
    return PolicyDecision(outcome="allow" if allow else "deny", stage=stage, reason=reason)


def business_check(policy: WorkflowPolicy, tool: str, args: dict, total: float = 0) -> PolicyDecision:
    recipients = []
    if tool == "send_email":
        recipients = [*(args.get("recipients") or []), *(args.get("cc") or []), *(args.get("bcc") or [])]
    elif tool == "share_file":
        recipients = [args["email"]]
        if args["permission"] not in policy.sharing_permissions:
            return decision(False, "validation", "Sharing permission exceeds deployment policy")
    elif tool in {"create_calendar_event", "add_calendar_event_participants"}:
        recipients = args.get("participants") or []
    if any(r.casefold() not in {a.casefold() for a in policy.allowed_recipients} for r in recipients):
        return decision(False, "validation", "Recipient outside deployment allowlist")
    if tool in {"delete_file", "append_to_file", "share_file"}:
        if args.get("file_id") in policy.protected_file_ids:
            return decision(False, "validation", "Protected file")
    if tool == "delete_email" and args.get("email_id") in policy.protected_email_ids:
        return decision(False, "validation", "Protected email")
    if tool in {"send_money", "schedule_transaction", "update_scheduled_transaction"}:
        recipient, amount = args.get("recipient"), args.get("amount")
        if recipient is None or amount is None:
            return decision(False, "validation", "Payment change requires explicit recipient and amount")
        if recipient.casefold() not in {a.casefold() for a in policy.allowed_accounts}:
            return decision(False, "validation", "Account outside deployment allowlist")
        if isinstance(amount, bool) or not math.isfinite(amount) or not 0 < amount <= policy.max_payment:
            return decision(False, "validation", "Payment outside per-action limit")
        if total + amount > policy.max_total_payments:
            return decision(False, "validation", "Cumulative payment limit exceeded")
    return decision(True, "validation", "Deployment constraints satisfied")


class Approver:
    def __init__(
        self, episode_id: str, scope: TaskScope, manual: bool = False, read: Callable[[str], str] = input
    ):
        self.episode_id, self.scope, self.manual, self.read = episode_id, scope, manual, read
        self._consumed: set[str] = set()

    def approve(self, tool: str, args: dict) -> bool:
        nonce = uuid.uuid4().hex
        request = ApprovalRequest(
            episode_id=self.episode_id,
            nonce=nonce,
            tool=tool,
            args=copy.deepcopy(args),
            request_sha256=digest([self.episode_id, nonce, tool, args]),
        )
        return self.resolve(request, tool, args)

    def resolve(self, request: ApprovalRequest, tool: str, args: dict) -> bool:
        if request.nonce in self._consumed or request.episode_id != self.episode_id:
            return False
        self._consumed.add(request.nonce)
        if (
            request.tool != tool
            or request.args != args
            or request.request_sha256 != digest([self.episode_id, request.nonce, tool, args])
        ):
            return False
        if self.manual:
            try:
                return (
                    self.read(
                        f"Approve exactly {tool} {json.dumps(args, ensure_ascii=True)}? [yes/NO] "
                    ).strip()
                    == "yes"
                )
            except (EOFError, KeyboardInterrupt):
                return False
        critical = CRITICAL.get(tool)
        if critical is None:
            return False
        for rule in self.scope.approvals:
            if rule.tool == tool and set(critical) <= rule.equals.keys():
                if all(args.get(k) == v for k, v in rule.equals.items()):
                    return True
        return False


class GuardedRuntime(FunctionsRuntime):
    """One instance per episode. All dispatch, including nested calls, crosses this boundary."""

    def __init__(
        self,
        functions,
        policy: WorkflowPolicy,
        scope: TaskScope,
        condition: Condition,
        episode_id: str,
        max_calls: int = 40,
        manual: bool = False,
    ):
        super().__init__(functions)
        # Deep-copy frozen models: their nested dicts are mutable in Pydantic.
        self._policy = policy.model_copy(deep=True)
        self._scope = scope.model_copy(deep=True)
        self._condition = condition
        self._registry = dict(self.functions)
        self._allowed = frozenset(scope.allowed_tools) if condition.restriction else frozenset(self._registry)
        self.functions = {k: v for k, v in self.functions.items() if k in self._allowed}
        self.events: list[ActionEvent] = []
        self.executed_calls: list[FunctionCall] = []
        self.approver = Approver(episode_id, self._scope, manual)
        self.max_calls, self.calls, self.total_payments = max_calls, 0, 0.0
        self.limit_reached = False

    def update_functions(self, new_functions):
        # Used by upstream tool filtering; selection can only shrink advertised/executable tools.
        permitted = frozenset(self.functions) & frozenset(new_functions) & self._allowed
        self.functions = {k: self._registry[k] for k in permitted}

    def _resolve_nested(self, env, value):
        if isinstance(value, FunctionCall):
            result, error = self.run_function(env, value.function, value.args)
            if error:
                raise ValueError(error)
            return result
        if isinstance(value, dict):
            return {k: self._resolve_nested(env, v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._resolve_nested(env, v) for v in value]
        return value

    def run_function(self, env, function, kwargs, raise_on_error=False):
        start = time.perf_counter()
        proposed = safe_record(
            json.loads(
                json.dumps(kwargs, default=lambda x: x.model_dump() if hasattr(x, "model_dump") else str(x))
            )
        )
        self.calls += 1
        sequence = self.calls
        self.events.append(
            ActionEvent(
                sequence=sequence,
                tool=function,
                proposed_args=proposed,
                status="proposed",
                stage="proposal",
                reason="Tool requested",
            )
        )
        normalized = None
        approval_requested, approved, violation = False, None, False
        execution_elapsed, nested_elapsed, approval_wait = 0.0, 0.0, 0.0

        def finish(status, stage, reason, result=""):
            duration = time.perf_counter() - start
            self.events.append(
                ActionEvent(
                    sequence=sequence,
                    tool=function,
                    proposed_args=proposed,
                    normalized_args=safe_record(normalized),
                    status=status,
                    stage=stage,
                    reason=reason,
                    approval_requested=approval_requested,
                    approval_granted=approved,
                    policy_violation=violation,
                    duration_seconds=duration,
                    policy_seconds=max(0, duration - execution_elapsed - nested_elapsed - approval_wait),
                    approval_wait_seconds=approval_wait,
                )
            )
            if status == "executed":
                return result, None
            error = json.dumps(
                {
                    "type": "policy_denial" if status == "denied" else "tool_error",
                    "stage": stage,
                    "reason": reason,
                }
            )
            if raise_on_error:
                raise ValueError(error)
            return "", error

        if self.calls > self.max_calls:
            self.limit_reached = True
            return finish("denied", "limit", "Episode tool-call limit exceeded")
        if function not in self.functions:
            violation = True
            return finish("denied", "restriction", "Tool unavailable in this episode")
        try:
            nested_started = time.perf_counter()
            resolved = self._resolve_nested(env, copy.deepcopy(dict(kwargs)))
            nested_elapsed = time.perf_counter() - nested_started
            # Match upstream list-string normalization before policy evaluation.
            for key, value in resolved.items():
                if isinstance(value, str):
                    try:
                        parsed = literal_eval(value)
                        if isinstance(parsed, list):
                            resolved[key] = parsed
                    except (SyntaxError, ValueError):
                        pass
            f = self._registry[function]
            if self._condition.validation and set(resolved) - f.parameters.model_fields.keys():
                raise ValueError("Unexpected tool arguments")
            normalized = f.parameters.model_validate(resolved).model_dump(mode="json")
        except Exception as exc:
            return finish("failed", "schema", f"{type(exc).__name__}: {exc}")
        check = business_check(self._policy, function, normalized, self.total_payments)
        # Counterfactual policy violations are recorded in every arm, without enforcing disabled controls.
        violation = function not in self._scope.allowed_tools or check.outcome == "deny"
        if self._condition.validation and check.outcome == "deny":
            return finish("denied", check.stage, check.reason)
        if self._condition.approval and function in self._policy.sensitive_tools:
            approval_requested = True
            approval_started = time.perf_counter()
            approved = self.approver.approve(function, normalized)
            if self.approver.manual:
                approval_wait = time.perf_counter() - approval_started
            if not approved:
                return finish("denied", "approval", "Approval absent or outside trusted task scope")
        execution_started = time.perf_counter()
        result, error = super().run_function(env, function, normalized, raise_on_error=False)
        execution_elapsed = time.perf_counter() - execution_started
        if error:
            return finish("failed", "execution", error)
        self.executed_calls.append(FunctionCall(function=function, args=copy.deepcopy(normalized)))
        if function in {"send_money", "schedule_transaction", "update_scheduled_transaction"}:
            self.total_payments += normalized.get("amount") or 0
        return finish("executed", "execution", "Tool completed", result)
