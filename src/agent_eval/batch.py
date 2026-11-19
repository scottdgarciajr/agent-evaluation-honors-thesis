"""Sequential multi-model evaluation with a shared OpenAI budget and comparison report."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from agent_eval.analysis import analyze
from agent_eval.models import Budget
from agent_eval.providers import redact_error
from agent_eval.runner import run_live
from agent_eval.schema import digest
from agent_eval.storage import atomic_json, exclusive_run, read_json


def model_folder(provider, name):
    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip(".-")[:70] or "model"
    return f"{provider}-{label}-{digest([provider, name])[:10]}"


def set_latest(directory, project):
    import os

    report = Path(directory).resolve() / "report.html"
    atomic_json(
        Path(project) / "output/latest-results.json",
        {
            "report": Path(os.path.relpath(report, project)).as_posix(),
            "run": Path(os.path.relpath(directory, project)).as_posix(),
            "mode": "Batch",
        },
    )


def run_batch(configs, directory, api_key=None, stop_event=None, progress=None):
    configs = list(configs)
    if not configs or len({(c.provider, c.model) for c in configs}) != len(configs):
        raise ValueError("Select at least one unique provider/model combination")
    directory = Path(directory)

    def emit(event):
        if progress:
            progress(event)

    with exclusive_run(directory):
        batch_path = directory / "batch.json"
        scientific = [c.model_dump(mode="json", exclude={"max_cost_usd", "max_episodes"}) for c in configs]
        signature = digest(scientific)
        if batch_path.exists() and read_json(batch_path)["selection_sha256"] != signature:
            raise ValueError("Batch selection/configuration changed; use a new output folder")
        openai_configs = [c for c in configs if c.provider == "openai"]
        shared = None
        if openai_configs:
            caps = {c.max_cost_usd for c in openai_configs}
            if None in caps or len(caps) != 1:
                raise ValueError("All OpenAI selections require the same total batch budget")
            shared = Budget(directory / "budget.json", next(iter(caps)))
        record = {
            "selection_sha256": signature,
            "configurations": scientific,
            "models": [],
            "stopped": False,
            "api_keys_saved": False,
        }
        atomic_json(batch_path, record)
        try:
            for index, config in enumerate(configs):
                if stop_event is not None and stop_event.is_set():
                    break
                relative = "models/" + model_folder(config.provider, config.model)
                output = directory / relative
                item = {
                    "provider": config.provider,
                    "model": config.model,
                    "directory": relative,
                    "status": "running",
                    "completed": 0,
                    "scheduled": 0,
                }
                record["models"].append(item)
                atomic_json(batch_path, record)
                emit(
                    {
                        "stage": "model_start",
                        "model": config.model,
                        "index": index + 1,
                        "models": len(configs),
                    }
                )
                try:
                    outcome = run_live(
                        config,
                        output,
                        api_key=api_key,
                        stop_event=stop_event,
                        progress=lambda event: emit({"stage": "episode", **event}),
                        shared_budget=shared if config.provider == "openai" else None,
                    )
                    if outcome["stopped"] and not any((output / "episodes").glob("*.json")):
                        item.update(status="stopped", scheduled=len(read_json(output / "schedule.json")))
                    else:
                        coverage = analyze(output)
                        item.update(coverage)
                        item["status"] = (
                            "completed" if coverage["completed"] == coverage["scheduled"] else "partial"
                        )
                        item["report"] = relative + "/analysis/report.html"
                except Exception as exc:
                    item.update(status="error", error=redact_error(exc, api_key))
                emit({"stage": "model_done", **item})
                atomic_json(batch_path, record)
                # A shared budget stop applies to the batch, not just the current model.
                if shared is not None and (output / "episodes").exists():
                    if any(
                        read_json(p)["status"] == "budget_exhausted"
                        for p in (output / "episodes").glob("*.json")
                    ):
                        break
        finally:
            record["stopped"] = bool(stop_event is not None and stop_event.is_set())
            record["unstarted_models"] = len(configs) - len(record["models"])
            record["accounted_usd"] = shared.accounted if shared else 0
            atomic_json(batch_path, record)
            write_comparison(directory, record)
        return record


def write_comparison(directory, record):
    rows = []
    for model in record["models"]:
        folder = directory / model["directory"]
        path = folder / "analysis/results.json"
        if not path.exists():
            continue
        # Pool only matching condition/scenario strata within each model, never across models.
        groups = {}
        for entry in read_json(path)["summary"]:
            key = (entry["condition"], "attack" if entry["attack"] != "benign" else "benign")
            group = groups.setdefault(
                key, {"completed": 0, "attempted": 0, "utility_sum": 0, "attacker_sum": 0}
            )
            n = entry["completed"]
            group["completed"] += n
            group["attempted"] += entry["attempted"]
            group["utility_sum"] += (entry["upstream_utility"] or 0) * n
            group["attacker_sum"] += (entry.get("upstream_attacker_success") or 0) * n
        for (condition, scenario), counts in groups.items():
            n = counts["completed"]
            rows.append(
                {
                    "provider": model["provider"],
                    "model": model["model"],
                    "condition": condition,
                    "scenario": scenario,
                    "completed": n,
                    "attempted": counts["attempted"],
                    "task_completion": counts["utility_sum"] / n if n else None,
                    "attacker_success": counts["attacker_sum"] / n if n and scenario == "attack" else None,
                }
            )
    fields = [
        "provider",
        "model",
        "condition",
        "scenario",
        "completed",
        "attempted",
        "task_completion",
        "attacker_success",
    ]
    with (directory / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    from agent_eval.result_pages import write_batch_page

    write_batch_page(directory, record)
