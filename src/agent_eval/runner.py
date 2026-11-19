from __future__ import annotations

import hashlib
import importlib.metadata
import math
import random
import time
from pathlib import Path

import httpx
import openai
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.task_suite.task_suite import functions_stack_trace_from_messages, model_output_from_messages
from pydantic import TypeAdapter

from agent_eval.attacks import make_payload
from agent_eval.models import (
    Budget,
    BudgetExhausted,
    InputLimit,
    InstrumentedLLM,
    MeteredTransport,
    RunCancelled,
)
from agent_eval.pipeline import build_pipeline
from agent_eval.policy import GuardedRuntime, safe_record
from agent_eval.schema import CONDITIONS, EpisodeResult, EpisodeSpec, WorkflowPolicy, digest
from agent_eval.storage import atomic_json, exclusive_run, read_json


def split_tasks(suite, config):
    ids = sorted(suite.user_tasks)
    rng = random.Random(f"{config.split_seed}:{suite.name}")
    rng.shuffle(ids)
    dev = set(ids[: max(1, math.ceil(len(ids) * config.dev_fraction))])
    return {task: "dev" if task in dev else "test" for task in sorted(ids)}


def load_policies(config):
    return {
        name: WorkflowPolicy.model_validate(read_json(config.policy_paths[name])) for name in config.suites
    }


def validate(config, policies):
    if importlib.metadata.version("agentdojo") != "0.1.35":
        raise ValueError("AgentDojo 0.1.35 is required")
    for name in config.suites:
        suite = get_suite(config.benchmark_version, name)
        policy = policies[name]
        if policy.suite != name:
            raise ValueError(f"Policy suite mismatch: {name}")
        tools = {t.name: t for t in suite.tools}
        if set(policy.sensitive_tools) - tools.keys():
            raise ValueError(f"Unknown sensitive tool in {name}")
        if set(suite.user_tasks) != policy.tasks.keys():
            raise ValueError(f"Policy must cover every {name} task")
        for task_id, task in suite.user_tasks.items():
            scope = policy.tasks[task_id]
            if scope.prompt_sha256 != hashlib.sha256(task.PROMPT.encode()).hexdigest():
                raise ValueError(f"Stale task policy: {name}/{task_id}")
            if set(scope.allowed_tools) - tools.keys():
                raise ValueError(f"Unknown scoped tool: {name}/{task_id}")
            for rule in scope.approvals:
                if rule.tool not in scope.allowed_tools:
                    raise ValueError(f"Approval exceeds tool scope: {name}/{task_id}")
                if set(rule.equals) - tools[rule.tool].parameters.model_fields.keys():
                    raise ValueError(f"Unknown approval argument: {name}/{task_id}/{rule.tool}")


def enumerate_episodes(config):
    specs = []
    selected_tasks, selected_injections = set(), set()
    for name in config.suites:
        suite = get_suite(config.benchmark_version, name)
        splits = split_tasks(suite, config)
        for task in sorted(suite.user_tasks):
            if config.task_ids and task not in config.task_ids:
                continue
            if config.split != "all" and splits[task] != config.split:
                continue
            selected_tasks.add(task)
            cases = [(None, None)] if config.include_benign else []
            for injection in sorted(suite.injection_tasks):
                if config.injection_ids and injection not in config.injection_ids:
                    continue
                selected_injections.add(injection)
                cases.extend((injection, attack) for attack in config.attacks)
            for repetition in range(config.repetitions):
                for injection, attack in cases:
                    for condition in config.conditions:
                        specs.append(
                            EpisodeSpec(
                                suite=name,
                                user_task=task,
                                injection_task=injection,
                                attack=attack,
                                condition=condition,
                                repetition=repetition,
                                split=splits[task],
                            )
                        )
    if set(config.task_ids) - selected_tasks:
        raise ValueError("Requested task IDs are absent from the selected suites/split")
    if config.attacks and set(config.injection_ids) - selected_injections:
        raise ValueError("Requested injection IDs do not exist")
    if not specs:
        raise ValueError("Empty experiment matrix")
    # Shuffle blocks, preserving all conditions together so a bounded pilot is less imbalanced.
    blocks = [specs[i : i + len(config.conditions)] for i in range(0, len(specs), len(config.conditions))]
    random.Random(config.split_seed).shuffle(blocks)
    for block in blocks:
        random.Random(
            f"{config.split_seed}:{block[0].suite}:{block[0].user_task}:"
            f"{block[0].attack}:{block[0].injection_task}:{block[0].repetition}"
        ).shuffle(block)
    return [spec for block in blocks for spec in block]


def provenance(config, policies, model_metadata=None):
    versions = {
        dist.metadata["Name"]: dist.version
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    }
    source = Path(__file__).parent
    code_hash = digest(
        {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.glob("*.py"))}
    )
    settings = config.model_dump(mode="json", exclude={"max_cost_usd", "max_episodes"})
    data = {
        "settings": settings,
        "policies": {k: v.model_dump(mode="json") for k, v in policies.items()},
        "dependencies": versions,
        "code_sha256": code_hash,
    }
    if model_metadata is not None:
        data["model_metadata"] = model_metadata
    return {**data, "experiment_sha256": digest(data)}


def evaluate_episode(
    config, spec, policy, llm, experiment_hash, injections=None, manual=False, payload_cache=None
):
    started = time.perf_counter()
    suite = get_suite(config.benchmark_version, spec.suite)
    task = suite.user_tasks[spec.user_task]
    injection_task = suite.injection_tasks[spec.injection_task] if spec.injection_task else None
    scope = policy.tasks[spec.user_task]
    condition = CONDITIONS[spec.condition]
    pipeline = build_pipeline(llm, condition, config.max_steps)
    episode_id = digest([experiment_hash, spec.model_dump(mode="json")])
    actions, messages, runtime = [], [], None
    payload = {} if injections is None else injections
    data = dict(
        experiment_sha256=experiment_hash,
        episode_id=episode_id,
        spec=spec,
        workflow=scope.workflow,
        policy_sha256=digest(policy),
        payload_sha256=digest(payload),
    )
    status, error = "error", None
    try:
        if injections is None and injection_task is not None:
            # Payloads are generated independently of the defense condition.
            cache_key = (spec.suite, spec.user_task, spec.injection_task, spec.attack)
            if payload_cache is not None and cache_key in payload_cache:
                payload = payload_cache[cache_key]
            else:
                payload = make_payload(
                    suite, build_pipeline(llm, CONDITIONS["r0v0a0"]), task, injection_task, spec.attack
                )
                if payload_cache is not None:
                    payload_cache[cache_key] = payload
        data.update(injections=payload, payload_sha256=digest(payload))
        env = task.init_environment(suite.load_and_inject_default_environment(payload))
        before = env.model_copy(deep=True)
        data["environment_sha256"] = digest(before.model_dump(mode="json"))
        runtime = GuardedRuntime(
            suite.tools, policy, scope, condition, episode_id, config.max_tool_calls, manual
        )
        _, _, after, messages, _ = pipeline.query(task.PROMPT, runtime, env)
        output = model_output_from_messages(messages)
        requested = functions_stack_trace_from_messages(messages)
        # Call the pinned upstream evaluator methods, keeping their semantics intact.
        data["upstream_utility"] = bool(
            suite._check_user_task_utility(task, output or [], before, after, requested)
        )
        data["execution_utility"] = bool(
            suite._check_user_task_utility(task, output or [], before, after, runtime.executed_calls)
        )
        if injection_task is not None:
            data["upstream_attacker_success"] = bool(
                suite._check_injection_task_security(injection_task, output or [], before, after, requested)
            )
            data["upstream_security_raw"] = data["upstream_attacker_success"]
            data["execution_attacker_success"] = bool(
                suite._check_injection_task_security(
                    injection_task, output or [], before, after, runtime.executed_calls
                )
            )
        else:
            # AgentDojo returns True as its benign-run security sentinel; it is NOT an attack outcome.
            data["upstream_security_raw"] = True
        from agentdojo.types import get_text_content_as_str

        data["trace_evaluator"] = (
            task.utility_from_traces(get_text_content_as_str(output or []), before, after, requested)
            is not None
        )
        if injection_task is not None:
            data["trace_evaluator"] |= (
                injection_task.security_from_traces(
                    get_text_content_as_str(output or []), before, after, requested
                )
                is not None
            )
        pending = messages and messages[-1]["role"] == "assistant" and messages[-1].get("tool_calls")
        status = (
            "incomplete"
            if (output is None or pending or runtime.limit_reached or getattr(llm, "truncated", False))
            else "completed"
        )
    except BudgetExhausted as exc:
        status, error = "budget_exhausted", str(exc)
    except (InputLimit, RunCancelled) as exc:
        status, error = "incomplete", str(exc)
    except openai.APIError as exc:
        status, error = "api_error", f"{type(exc).__name__}: {exc}"
    except httpx.HTTPError as exc:
        status, error = "api_error", f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        status, error = "error", f"{type(exc).__name__}: {exc}"
    if runtime is not None:
        actions = runtime.events
    if status != "completed":
        messages = getattr(llm, "last_messages", messages)
    # The transport records all requests, including filter selection and unsuccessful attempts.
    requests = getattr(getattr(llm, "client", None), "requests", [])
    if error:
        error = getattr(getattr(llm, "client", None), "safe_error", str)(error)
    data.update(
        status=status,
        error=error,
        duration_seconds=time.perf_counter() - started,
        actions=actions,
        messages=safe_record(TypeAdapter(list).dump_python(messages, mode="json")),
        requests=requests,
        prompt_tokens=sum(r.get("prompt_tokens", 0) for r in requests),
        completion_tokens=sum(r.get("completion_tokens", 0) for r in requests),
        cost_usd_estimate=sum(r.get("cost_usd_estimate", 0) for r in requests),
    )
    return EpisodeResult(**data)


def run_live(config, directory, api_key=None, stop_event=None, progress=None, shared_budget=None):
    import os

    from agent_eval.providers import OllamaClient, discover_ollama

    if config.provider == "openai":
        if not (api_key or os.getenv("OPENAI_API_KEY")):
            raise ValueError("Set OPENAI_API_KEY or enter it in the GUI before an OpenAI run")
        if not config.model or not all(
            getattr(config, name) is not None
            for name in ["max_cost_usd", "input_usd_per_million", "output_usd_per_million"]
        ):
            raise ValueError("OpenAI runs require model, max_cost_usd, and both per-million token prices")
    elif not config.model:
        raise ValueError("Select an Ollama model")
    model_metadata = None
    if config.provider == "ollama":
        selected = next((m for m in discover_ollama(config.ollama_url) if m.name == config.model), None)
        if selected is None:
            raise ValueError(f"Ollama model is not installed: {config.model}")
        if selected.compatible is False:
            raise ValueError(f"{config.model}: {selected.reason}")
        model_metadata = selected.model_dump(mode="json")
    policies = load_policies(config)
    validate(config, policies)
    specs = enumerate_episodes(config)
    directory = Path(directory)
    with exclusive_run(directory):
        manifest = provenance(config, policies, model_metadata)
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            if read_json(manifest_path)["experiment_sha256"] != manifest["experiment_sha256"]:
                raise ValueError(
                    "Configuration, code, policies or dependencies changed; use a new run directory"
                )
        else:
            atomic_json(manifest_path, {**manifest, "kind": "live", "matrix_episodes": len(specs)})
        atomic_json(directory / "schedule.json", [s.model_dump(mode="json") for s in specs])
        budget = shared_budget or Budget(
            directory / "budget.json", config.max_cost_usd if config.provider == "openai" else None
        )
        client = (
            OllamaClient(config)
            if config.provider == "ollama"
            else openai.OpenAI(api_key=api_key, max_retries=0, timeout=config.request_timeout_seconds)
        )
        completed = 0
        skipped = 0
        payload_cache = {}
        for spec in specs:
            if stop_event is not None and stop_event.is_set():
                break
            path = directory / "episodes" / f"{spec.key}.json"
            if path.exists():
                existing = EpisodeResult.model_validate(read_json(path))
                if existing.experiment_sha256 != manifest["experiment_sha256"]:
                    raise ValueError("Episode hash mismatch")
                if existing.status == "completed":
                    skipped += 1
                    continue
                # Keep failed attempts for coverage and cost accounting when explicitly resuming.
                archive = directory / "attempts" / f"{spec.key}-{time.time_ns()}.json"
                atomic_json(archive, existing.model_dump(mode="json"))
            if config.max_episodes is not None and completed >= config.max_episodes:
                break
            transport = MeteredTransport(client, config, budget, stop_event)
            result = evaluate_episode(
                config,
                spec,
                policies[spec.suite],
                InstrumentedLLM(transport, config),
                manifest["experiment_sha256"],
                payload_cache=payload_cache,
            )
            atomic_json(path, result.model_dump(mode="json"))
            completed += 1
            if progress:
                progress(
                    {
                        "model": config.model,
                        "provider": config.provider,
                        "done": completed + skipped,
                        "total": len(specs),
                        "status": result.status,
                        "suite": spec.suite,
                        "task": spec.user_task,
                        "condition": spec.condition,
                        "attack": spec.attack or "benign",
                        "error": result.error,
                    }
                )
            else:
                print(
                    f"{spec.suite}/{spec.user_task} {spec.condition} {spec.attack or 'benign'}: {result.status}",
                    flush=True,
                )
            if result.status == "budget_exhausted":
                break
        close = getattr(client, "close", None)
        if close:
            close()
        return {
            "attempted_this_invocation": completed,
            "matrix_episodes": len(specs),
            "accounted_usd": budget.accounted,
            "directory": str(directory),
            "stopped": bool(stop_event is not None and stop_event.is_set()),
        }
