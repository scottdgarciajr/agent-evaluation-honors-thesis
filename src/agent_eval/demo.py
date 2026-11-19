"""Scripted integration fixtures over REAL AgentDojo state. These are not LLM experiments."""

from pathlib import Path

from agentdojo.functions_runtime import FunctionCall
from agentdojo.types import text_content_block_from_string

from agent_eval.models import ScriptedLLM
from agent_eval.runner import evaluate_episode, load_policies, provenance, validate
from agent_eval.schema import CONDITIONS, EpisodeSpec, ExperimentConfig
from agent_eval.storage import atomic_json, exclusive_run, read_json


def assistant_call(function, args, index=0):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [FunctionCall(function=function, args=args, id=f"fixture-{index}")],
    }


def run_demo(directory, manual=False):
    config = ExperimentConfig(
        conditions=tuple(k for k in CONDITIONS if k != "upstream_tool_filter"),
        attacks=("permission_escalation",),
        split="dev",
        repetitions=1,
    )
    policies = load_policies(config)
    validate(config, policies)
    manifest = provenance(config, policies)
    manifest.update(
        kind="offline",
        matrix_episodes=1 if manual else 32,
        warning="Scripted integration fixture. No inference about model robustness is valid.",
    )
    directory = Path(directory)
    fixtures = [
        ("workspace", "user_task_24", None, "get_unread_emails", {}),
        ("workspace", "user_task_24", "injection_task_1", "delete_file", {"file_id": "13"}),
        ("banking", "user_task_14", None, "update_password", {"password": "1j1l-2k3j"}),
        (
            "banking",
            "user_task_14",
            "injection_task_7",
            "update_password",
            {"password": "new_password"},
        ),
    ]
    specs = []
    with exclusive_run(directory):
        if (directory / "manifest.json").exists():
            old = read_json(directory / "manifest.json")
            if old["kind"] != "offline" or old["experiment_sha256"] != manifest["experiment_sha256"]:
                raise ValueError("Use a new demo output directory after code or policy changes")
        atomic_json(directory / "manifest.json", manifest)
        for suite, task, injection, function, args in fixtures:
            if manual and (suite != "banking" or injection is not None):
                continue
            for condition in ["r1v1a1"] if manual else config.conditions:
                spec = EpisodeSpec(
                    suite=suite,
                    user_task=task,
                    injection_task=injection,
                    attack="permission_escalation" if injection else None,
                    condition=condition,
                    repetition=0,
                    split="dev",
                )
                specs.append(spec.model_dump(mode="json"))
                responses = [
                    assistant_call(function, args),
                    {
                        "role": "assistant",
                        "content": [text_content_block_from_string("Done")],
                        "tool_calls": None,
                    },
                ]
                result = evaluate_episode(
                    config,
                    spec,
                    policies[suite],
                    ScriptedLLM(responses),
                    manifest["experiment_sha256"],
                    manual=manual,
                )
                atomic_json(directory / "episodes" / f"{spec.key}.json", result.model_dump(mode="json"))
                print(
                    f"OFFLINE {suite}/{task} {condition} {'attack' if injection else 'benign'}: {result.status}"
                )
        atomic_json(directory / "schedule.json", specs)
    return {"directory": str(directory), "episodes": len(specs), "kind": "offline"}
