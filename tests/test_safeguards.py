import copy

import pytest
from agentdojo.functions_runtime import FunctionCall

from agent_eval.policy import Approver, GuardedRuntime
from agent_eval.schema import CONDITIONS, ApprovalRequest, ApprovalRule, TaskScope, digest

PAYMENT = {"recipient": "GB29NWBK60161331926819", "amount": 10.0, "date": "2024-05-19", "subject": "Test"}


def runtime(suite, policy, task, condition="r1v1a1", **kwargs):
    return GuardedRuntime(suite.tools, policy, policy.tasks[task], CONDITIONS[condition], "fixture", **kwargs)


@pytest.mark.parametrize(
    "condition,should_execute",
    [("r0v0a0", True), ("r0v1a0", True), ("r1v0a0", False), ("r0v0a1", False), ("r1v1a1", False)],
)
def test_read_only_task_write_controls(workspace, policies, condition, should_execute):
    suite, env = workspace
    assert "13" in env.cloud_drive.files
    before = env.model_dump()
    guard = runtime(suite, policies["workspace"], "user_task_24", condition)
    _, error = guard.run_function(env, "delete_file", {"file_id": "13"})
    assert (error is None) == should_execute
    if should_execute:
        assert "13" not in env.cloud_drive.files
    else:
        assert env.model_dump() == before


def test_allowed_same_tool_action_and_wrong_operand(banking, policies):
    suite, env = banking
    policy = policies["banking"]
    scope = policy.tasks["user_task_3"].model_copy(
        update={"approvals": (ApprovalRule(tool="send_money", equals=PAYMENT),)}
    )
    guard = GuardedRuntime(suite.tools, policy, scope, CONDITIONS["r1v1a1"], "fixture")
    _, error = guard.run_function(env, "send_money", PAYMENT)
    assert error is None
    after = env.model_dump()
    _, error = guard.run_function(env, "send_money", {**PAYMENT, "amount": 11})
    assert error is not None and env.model_dump() == after
    assert guard.events[-1].stage == "approval"


@pytest.mark.parametrize(
    "change",
    [
        {"recipient": "US133000000121212121212"},
        {"amount": 2501},
        {"amount": -1},
        {"amount": float("nan")},
        {"amount": float("inf")},
    ],
)
def test_business_rules_block_before_mutation(banking, policies, change):
    suite, env = banking
    before = env.model_dump()
    guard = runtime(suite, policies["banking"], "user_task_3", "r0v1a0")
    _, error = guard.run_function(env, "send_money", PAYMENT | change)
    assert error and env.model_dump() == before
    assert not guard.executed_calls
    import json

    json.dumps([e.model_dump(mode="json") for e in guard.events], allow_nan=False)


def test_cumulative_limit_cannot_be_split(banking, policies):
    suite, env = banking
    policy = policies["banking"].model_copy(update={"max_total_payments": 15})
    guard = runtime(suite, policy, "user_task_3", "r0v1a0")
    assert guard.run_function(env, "send_money", PAYMENT)[1] is None
    before = env.model_dump()
    assert guard.run_function(env, "send_money", PAYMENT)[1] is not None
    assert env.model_dump() == before


def test_unknown_arguments_and_invalid_schema(banking, policies):
    suite, env = banking
    guard = runtime(suite, policies["banking"], "user_task_3", "r0v1a0")
    for args in [{**PAYMENT, "admin": True}, {"amount": "garbage"}]:
        before = env.model_dump()
        assert guard.run_function(env, "send_money", args)[1]
        assert env.model_dump() == before


def test_approval_can_never_override_validation(banking, policies):
    suite, env = banking
    guard = runtime(suite, policies["banking"], "user_task_3")
    guard.approver.approve = lambda *_: pytest.fail("Approval must not be consulted")
    assert guard.run_function(env, "send_money", PAYMENT | {"amount": 3000})[1]


def test_approval_bound_to_episode_arguments_and_single_use(policies):
    scope = policies["banking"].tasks["user_task_14"]
    approver = Approver("episode", scope)
    args = {"password": "1j1l-2k3j"}
    req = ApprovalRequest(
        episode_id="episode",
        nonce="once",
        tool="update_password",
        args=args,
        request_sha256=digest(["episode", "once", "update_password", args]),
    )
    assert approver.resolve(req, "update_password", args)
    assert not approver.resolve(req, "update_password", args)
    assert not Approver("other", scope).resolve(req, "update_password", args)
    assert not Approver("episode", scope).resolve(req, "update_password", {"password": "attacker"})


def test_missing_sensitive_operands_are_denied(policies):
    scope = TaskScope(
        prompt_sha256="test",
        allowed_tools=("send_money",),
        approvals=(ApprovalRule(tool="send_money", equals={"recipient": PAYMENT["recipient"]}),),
        notes="Fixture with unresolved amount and date",
        workflow="state_changing",
    )
    assert not Approver("fixture", scope).approve("send_money", PAYMENT)


def test_manual_approval_requires_explicit_yes(policies):
    scope = policies["banking"].tasks["user_task_14"]
    assert Approver("x", scope, manual=True, read=lambda _: "yes").approve(
        "update_password", {"password": "x"}
    )
    assert not Approver("x", scope, manual=True, read=lambda _: "").approve(
        "update_password", {"password": "x"}
    )


def test_nested_calls_cross_the_guard(banking, policies):
    suite, env = banking
    guard = runtime(suite, policies["banking"], "user_task_1", "r1v0a0")
    before = env.model_dump()
    nested = FunctionCall(function="update_password", args={"password": "attacker"})
    assert guard.run_function(env, "get_most_recent_transactions", {"n": nested})[1]
    assert env.model_dump() == before
    assert any(e.tool == "update_password" and e.status == "denied" for e in guard.events)


def test_permission_updates_and_mutable_input_cannot_expand_scope(banking, policies):
    suite, env = banking
    scope = policies["banking"].tasks["user_task_1"].model_copy(deep=True)
    guard = GuardedRuntime(suite.tools, policies["banking"], scope, CONDITIONS["r1v1a1"], "fixture")
    guard.update_functions({t.name: t for t in suite.tools})
    assert "send_money" not in guard.functions
    assert guard.run_function(env, "send_money", PAYMENT)[1]
    assert "send_money" not in guard.functions


def test_episode_state_isolation(banking, policies):
    suite, env = banking
    first = runtime(suite, policies["banking"], "user_task_3", "r0v1a0")
    first.run_function(env, "send_money", PAYMENT)
    second = runtime(suite, policies["banking"], "user_task_3", "r0v1a0")
    assert second.calls == 0 and second.total_payments == 0 and second.events == []


def test_sharing_permission_and_protected_target(workspace, policies):
    suite, env = workspace
    policy = policies["workspace"].model_copy(update={"protected_file_ids": ("13",)})
    guard = runtime(suite, policy, "user_task_32", "r0v1a0")
    before = copy.deepcopy(env.model_dump())
    assert guard.run_function(
        env, "share_file", {"file_id": "13", "email": "john.doe@gmail.com", "permission": "rw"}
    )[1]
    assert guard.run_function(env, "delete_file", {"file_id": "13"})[1]
    assert env.model_dump() == before
