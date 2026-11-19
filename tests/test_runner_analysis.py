import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from agent_eval.analysis import cluster_interval, paired_differences, portfolio_results, summarize
from agent_eval.models import Budget, BudgetExhausted, InputLimit, MeteredTransport
from agent_eval.runner import run_live
from agent_eval.schema import EpisodeResult, EpisodeSpec, ExperimentConfig
from agent_eval.storage import read_json


def result(
    task="user_task_0",
    condition="r0v0a0",
    attack="ignore_previous",
    utility=True,
    success=False,
    status="completed",
    repetition=0,
):
    return EpisodeResult(
        experiment_sha256="fixture",
        episode_id=f"{task}-{condition}",
        spec=EpisodeSpec(
            suite="banking",
            user_task=task,
            injection_task="injection_task_0" if attack else None,
            attack=attack,
            condition=condition,
            repetition=repetition,
            split="test",
        ),
        status=status,
        workflow="state_changing",
        policy_sha256="fixture",
        payload_sha256="fixture",
        upstream_utility=utility,
        execution_utility=utility,
        upstream_attacker_success=success if attack else None,
        execution_attacker_success=success if attack else None,
    )


def test_error_coverage_and_attack_direction():
    rows = [result(success=True), result(task="user_task_1", status="api_error", utility=None, success=None)]
    summary = summarize(rows)[0]
    assert summary["upstream_attacker_success"] == 1
    assert summary["coverage"] == 0.5
    assert summary["upstream_attacker_success_attempted_lower_bound"] == 0.5
    assert summary["upstream_attacker_success_attempted_upper_bound"] == 1
    assert summary["safe_completion"] == 0


def test_benign_rows_never_enter_attack_rate():
    assert "upstream_attacker_success" not in summarize([result(attack=None)])[0]


def test_paired_matching_and_cluster_intervals():
    rows = [
        result(task="user_task_0", success=True),
        result(task="user_task_0", condition="r1v1a1", success=False),
        result(task="user_task_1", success=True),
        result(task="user_task_1", condition="r1v1a1", success=False),
        result(task="unmatched", condition="r1v1a1", success=True),
    ]
    attack = next(r for r in paired_differences(rows) if r["metric"] == "upstream_attacker_success")
    assert attack["matched_episodes"] == 2
    assert attack["delta_vs_baseline"] == -1
    assert attack["ci_low"] == attack["ci_high"] == -1
    # One task with many repetitions is still one independent cluster.
    assert cluster_interval({"one": [0] * 100}) == (None, None)


def test_portfolio_requires_every_attack_family():
    rows = [result(success=False)]
    portfolio = portfolio_results(rows, ["ignore_previous", "injecagent"])[0]
    assert not portfolio["portfolio_complete"]
    assert portfolio["any_attacker_success"] is None


def test_budget_persists_reservations_and_checks_before_call(tmp_path):
    path = tmp_path / "budget.json"
    first = Budget(path, 1)
    first.reserve(0.8)
    recovered = Budget(path, 1)
    assert recovered.accounted == 0.8
    with pytest.raises(BudgetExhausted):
        recovered.reserve(0.3)
    recovered.settle(0.8, 0.2)
    assert recovered.accounted == pytest.approx(0.2)


def test_token_bound_prevents_network_request(tmp_path):
    cfg = ExperimentConfig(
        model="fixture",
        max_cost_usd=1,
        input_usd_per_million=1,
        output_usd_per_million=1,
        max_input_tokens=256,
    )
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: pytest.fail("No request should be made"))
        )
    )
    transport = MeteredTransport(sdk, cfg, Budget(tmp_path / "budget.json", 1))
    with pytest.raises(InputLimit):
        transport.create(model="fixture", messages=[{"role": "user", "content": "too large"}])
    assert not transport.requests


def test_resume_skips_completed_and_preserves_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-fixture-key")
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return ChatCompletion(
            id="fixture",
            created=0,
            model="fixture",
            object="chat.completion",
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            choices=[
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Done"}}
            ],
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("agent_eval.runner.openai.OpenAI", lambda **_: client)
    cfg = ExperimentConfig(
        suites=("banking",),
        conditions=("r0v0a0",),
        attacks=(),
        task_ids=("user_task_14",),
        split="dev",
        repetitions=1,
        model="fixture",
        max_cost_usd=1,
        input_usd_per_million=1,
        output_usd_per_million=1,
    )
    first = run_live(cfg, tmp_path / "run")
    second = run_live(cfg, tmp_path / "run")
    assert first["attempted_this_invocation"] == 1
    assert second["attempted_this_invocation"] == 0
    assert len(requests) == 1
    assert second["accounted_usd"] == first["accounted_usd"]
    changed = cfg.model_copy(update={"model": "different"})
    with pytest.raises(ValueError, match="changed"):
        run_live(changed, tmp_path / "run")
    paths = list((tmp_path / "run/episodes").glob("*.json"))
    assert read_json(paths[0])["requests"][0]["response_model"] == "fixture"
    assert "offline-fixture-key" not in json.dumps(read_json(paths[0]))


def test_live_requires_explicit_model_pricing_and_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        run_live(ExperimentConfig(), Path(tmp_path))
