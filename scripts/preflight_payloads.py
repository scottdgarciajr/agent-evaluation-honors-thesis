"""Check every selected user task and injection goal against all shipped attacks, without model calls."""

from agentdojo.task_suite.load_suites import get_suite

from agent_eval.attacks import make_payload
from agent_eval.models import ScriptedLLM
from agent_eval.pipeline import build_pipeline
from agent_eval.schema import CONDITIONS, ExperimentConfig


def main():
    checked = 0
    failures = []
    config = ExperimentConfig()
    pipeline = build_pipeline(ScriptedLLM([]), CONDITIONS["r0v0a0"])
    for name in config.suites:
        suite = get_suite(config.benchmark_version, name)
        first_user = next(iter(suite.user_tasks.values()))
        first_goal = next(iter(suite.injection_tasks.values()))
        # Cross every user with a reference goal; cross every goal with a reference user.
        pairs = [(task, first_goal) for task in suite.user_tasks.values()]
        pairs += [(first_user, goal) for goal in suite.injection_tasks.values()]
        for attack in (*config.attacks, "forged_approval", "permission_escalation"):
            for task, goal in pairs:
                try:
                    payload = make_payload(suite, pipeline, task, goal, attack)
                    suite.load_and_inject_default_environment(payload)
                    assert payload
                    checked += 1
                except Exception as exc:
                    failures.append(f"{name}/{task.ID}/{goal.ID}/{attack}: {type(exc).__name__}: {exc}")
    print(f"Validated {checked} local payload/environment combinations; no model calls.")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
