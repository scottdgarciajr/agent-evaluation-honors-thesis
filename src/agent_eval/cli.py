from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

from agent_eval.schema import ExperimentConfig
from agent_eval.storage import read_json


def configuration(args):
    data = read_json(args.config) if args.config else {}
    for field in [
        "model",
        "provider",
        "ollama_url",
        "max_cost_usd",
        "input_usd_per_million",
        "output_usd_per_million",
        "max_episodes",
    ]:
        value = getattr(args, field, None)
        if value is not None:
            data[field] = value
    return ExperimentConfig.model_validate(data)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentDojo thesis evaluation; offline unless run --live is explicit"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check versions and benchmark imports without API calls")
    sub.add_parser("gui", help="Open the native research console")
    models = sub.add_parser("models", help="Discover installed Ollama or available OpenAI models")
    models.add_argument("--provider", choices=("ollama", "openai"), default="ollama")
    models.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    tasks = sub.add_parser("tasks", help="List legitimate prompts and development/test assignments")
    tasks.add_argument("--config")
    for name in ["validate", "enumerate", "run", "resume", "batch"]:
        p = sub.add_parser(name)
        p.add_argument("--config", default="configs/quick.json" if name == "batch" else "configs/pilot.json")
        if name in {"run", "resume", "batch"}:
            p.add_argument("--live", action="store_true", help="Enable real model inference")
            p.add_argument("--output", default="runs/pilot")
            p.add_argument("--model")
            p.add_argument("--provider", choices=("ollama", "openai"))
            p.add_argument("--ollama-url")
            p.add_argument("--max-cost-usd", type=float)
            p.add_argument("--input-usd-per-million", type=float)
            p.add_argument("--output-usd-per-million", type=float)
            p.add_argument("--max-episodes", type=int)
            if name == "batch":
                selection = p.add_mutually_exclusive_group(required=True)
                selection.add_argument("--models", nargs="+")
                selection.add_argument("--all-models", action="store_true")
    demo = sub.add_parser("demo", help="Run labeled scripted fixtures on AgentDojo environments")
    demo.add_argument("--output", default="runs/offline-demo")
    demo.add_argument(
        "--manual", action="store_true", help="Request terminal approval for one scripted benign action"
    )
    analysis = sub.add_parser("analyze")
    analysis.add_argument("directory")
    analysis.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from agent_eval.gui import main as gui_main

            gui_main()
        elif args.command == "models":
            from agent_eval.providers import discover_ollama, discover_openai

            items = discover_ollama(args.ollama_url) if args.provider == "ollama" else discover_openai()
            print(json.dumps([item.model_dump(mode="json") for item in items], indent=2))
        elif args.command == "doctor":
            from agentdojo.task_suite.load_suites import get_suite

            print(f"Python {sys.version.split()[0]}; AgentDojo {importlib.metadata.version('agentdojo')}")
            for name in ["workspace", "banking"]:
                suite = get_suite("v1.2.2", name)
                print(
                    f"{name}: {len(suite.user_tasks)} user tasks, {len(suite.injection_tasks)} injection goals"
                )
            print("Offline imports OK. No model request made.")
        elif args.command == "demo":
            from agent_eval.demo import run_demo

            print(json.dumps(run_demo(args.output, args.manual), indent=2))
        elif args.command == "analyze":
            from agent_eval.analysis import analyze

            print(json.dumps(analyze(args.directory, args.output), indent=2))
        else:
            from agentdojo.task_suite.load_suites import get_suite

            from agent_eval.runner import enumerate_episodes, load_policies, run_live, split_tasks, validate

            config = configuration(args)
            if args.command == "tasks":
                for name in config.suites:
                    suite = get_suite(config.benchmark_version, name)
                    splits = split_tasks(suite, config)
                    for key, task in sorted(suite.user_tasks.items()):
                        print(
                            json.dumps(
                                {"suite": name, "task": key, "split": splits[key], "prompt": task.PROMPT}
                            )
                        )
            elif args.command == "batch":
                from agent_eval.batch import run_batch
                from agent_eval.providers import discover_ollama, discover_openai

                names = args.models
                if args.all_models:
                    items = (
                        discover_ollama(config.ollama_url)
                        if config.provider == "ollama"
                        else discover_openai()
                    )
                    names = [
                        m.name
                        for m in items
                        if m.compatible is True or (config.provider == "openai" and m.compatible is None)
                    ]
                configs = [
                    ExperimentConfig.model_validate({**config.model_dump(), "model": name}) for name in names
                ]
                if not configs:
                    raise ValueError("No compatible models found")
                if args.live:
                    print(json.dumps(run_batch(configs, Path(args.output)), indent=2))
                else:
                    print(
                        json.dumps(
                            {
                                "models": names,
                                "episodes_per_model": len(enumerate_episodes(config)),
                                "live_requests": False,
                            },
                            indent=2,
                        )
                    )
            else:
                policies = load_policies(config)
                validate(config, policies)
                specs = enumerate_episodes(config)
                if args.command in {"run", "resume"} and args.live:
                    print(json.dumps(run_live(config, Path(args.output)), indent=2))
                else:
                    from collections import Counter

                    print(
                        json.dumps(
                            {
                                "valid": True,
                                "scheduled_episodes": len(specs),
                                "by_suite": dict(Counter(s.suite for s in specs)),
                                "by_condition": dict(Counter(s.condition for s in specs)),
                                "max_episodes_per_invocation": config.max_episodes,
                                "live_requests": False,
                            },
                            indent=2,
                        )
                    )
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
