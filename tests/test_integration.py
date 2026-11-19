from types import SimpleNamespace

from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, load_system_message
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop, ToolsExecutor
from agentdojo.functions_runtime import FunctionsRuntime

from agent_eval.demo import assistant_call, run_demo
from agent_eval.models import InstrumentedLLM, ScriptedLLM
from agent_eval.pipeline import build_pipeline
from agent_eval.policy import GuardedRuntime
from agent_eval.runner import enumerate_episodes, evaluate_episode, split_tasks, validate
from agent_eval.schema import CONDITIONS, EpisodeSpec, ExperimentConfig


def responses():
    return [
        assistant_call("get_most_recent_transactions", {"n": 3}),
        assistant_call("update_password", {"password": "1j1l-2k3j"}, 1),
        {"role": "assistant", "content": [{"type": "text", "content": "Done"}], "tool_calls": None},
    ]


def test_native_baseline_parity_on_scripted_multi_step_workflow(banking, policies):
    suite, env = banking
    native = AgentPipeline(
        [
            SystemMessage(load_system_message(None)),
            InitQuery(),
            ScriptedLLM(responses()),
            ToolsExecutionLoop([ToolsExecutor(), ScriptedLLM(responses()[1:])]),
        ]
    )
    # Separate first-call and loop fixtures reproduce the same response stream as the shared test LLM.
    expected = native.query("fixture", FunctionsRuntime(suite.tools), env.model_copy(deep=True))
    guard = GuardedRuntime(
        suite.tools,
        policies["banking"],
        policies["banking"].tasks["user_task_14"],
        CONDITIONS["r0v0a0"],
        "fixture",
    )
    observed = build_pipeline(ScriptedLLM(responses()), CONDITIONS["r0v0a0"]).query(
        "fixture", guard, env.model_copy(deep=True)
    )
    assert expected[2].model_dump() == observed[2].model_dump()
    assert expected[3] == observed[3]


def test_batched_calls_are_each_checked(workspace, policies):
    suite, env = workspace
    before = env.model_dump()
    mixed = assistant_call("get_unread_emails", {})
    mixed["tool_calls"].append(assistant_call("delete_file", {"file_id": "13"}, 1)["tool_calls"][0])
    guard = GuardedRuntime(
        suite.tools,
        policies["workspace"],
        policies["workspace"].tasks["user_task_24"],
        CONDITIONS["r1v1a1"],
        "fixture",
    )
    build_pipeline(ScriptedLLM([mixed]), CONDITIONS["r1v1a1"]).query("fixture", guard, env)
    # get_unread_emails legitimately marks messages as read; the denied drive mutation must not occur.
    assert env.cloud_drive.model_dump() == before["cloud_drive"]
    assert len([e for e in guard.events if e.status == "proposed"]) == 2
    assert [e.tool for e in guard.events if e.status == "proposed"] == ["get_unread_emails", "delete_file"]
    assert any(e.tool == "delete_file" and e.status == "denied" for e in guard.events)


def test_error_keeps_partial_transcript_and_effect_ledger(policies):
    class FailingLLM(ScriptedLLM):
        def query(self, query, runtime, env=None, messages=(), extra_args=None):
            self.last_messages = list(messages)
            if any(m["role"] == "tool" for m in messages):
                raise RuntimeError("Simulated model failure after tool execution")
            return super().query(query, runtime, env, messages, extra_args)

    spec = EpisodeSpec(
        suite="banking",
        user_task="user_task_14",
        injection_task=None,
        attack=None,
        condition="r0v0a0",
        repetition=0,
        split="dev",
    )
    result = evaluate_episode(
        ExperimentConfig(),
        spec,
        policies["banking"],
        FailingLLM([assistant_call("update_password", {"password": "fixture"})]),
        "fixture",
    )
    assert result.status == "error"
    assert any(m["role"] == "tool" for m in result.messages)
    assert any(a.status == "executed" for a in result.actions)
    assert result.upstream_attacker_success is None


def test_benign_security_sentinel_not_attacker_success(policies):
    spec = EpisodeSpec(
        suite="banking",
        user_task="user_task_14",
        injection_task=None,
        attack=None,
        condition="r1v1a1",
        repetition=0,
        split="dev",
    )
    result = evaluate_episode(
        ExperimentConfig(), spec, policies["banking"], ScriptedLLM(responses()), "fixture"
    )
    assert result.status == "completed"
    assert result.upstream_utility
    assert result.upstream_security_raw is True
    assert result.upstream_attacker_success is None


def test_real_attack_generation_is_condition_independent(policies):
    from agentdojo.task_suite.load_suites import get_suite

    from agent_eval.attacks import make_payload

    suite = get_suite("v1.2.2", "banking")
    hashes = []
    for condition in ["r0v0a0", "r1v1a1"]:
        payload = make_payload(
            suite,
            build_pipeline(ScriptedLLM([]), CONDITIONS[condition]),
            suite.user_tasks["user_task_14"],
            suite.injection_tasks["injection_task_7"],
            "important_instructions",
        )
        hashes.append(payload)
    assert hashes[0] == hashes[1] and hashes[0]


def test_upstream_filter_uses_instrumented_transport(banking, policies):
    suite, env = banking
    from openai.types.chat import ChatCompletion

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return ChatCompletion(
            id="fixture",
            created=0,
            model="fixture",
            object="chat.completion",
            choices=[
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "get_balance" if len(calls) == 1 else "Done"},
                }
            ],
        )

    transport = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    config = ExperimentConfig(model="fixture")
    llm = InstrumentedLLM(transport, config)
    guard = GuardedRuntime(
        suite.tools,
        policies["banking"],
        policies["banking"].tasks["user_task_1"],
        CONDITIONS["upstream_tool_filter"],
        "fixture",
    )
    build_pipeline(llm, CONDITIONS["upstream_tool_filter"]).query("fixture", guard, env)
    assert len(calls) == 2
    assert set(guard.functions) == {"get_balance"}


def test_versioned_policies_and_splits(policies, banking):
    config = ExperimentConfig()
    validate(config, policies)
    suite, _ = banking
    split = split_tasks(suite, config)
    assert split == split_tasks(suite, config)
    assert sum(s == "dev" for s in split.values()) == 4
    specs = enumerate_episodes(config)
    assert all(s.split == "test" for s in specs)
    assert len({s.key for s in specs}) == len(specs)


def test_offline_demo_creates_analyzable_records(tmp_path):
    from agent_eval.analysis import analyze
    from agent_eval.storage import read_json

    result = run_demo(tmp_path / "demo")
    assert result["episodes"] == 32
    rows = [read_json(p) for p in (tmp_path / "demo/episodes").glob("*.json")]
    baseline_attacks = [r for r in rows if r["spec"]["attack"] and r["spec"]["condition"] == "r0v0a0"]
    assert len(baseline_attacks) == 2
    assert all(r["upstream_attacker_success"] for r in baseline_attacks)
    secured_attacks = [r for r in rows if r["spec"]["attack"] and r["spec"]["condition"] == "r1v1a1"]
    assert all(not r["upstream_attacker_success"] for r in secured_attacks)
    coverage = analyze(tmp_path / "demo")
    assert coverage["completed"] == 32 and coverage["kind"] == "offline"
    assert (tmp_path / "demo/analysis/tradeoffs.png").stat().st_size > 1000
