"""Plain-language, count-based views of existing results; never substitutes new scores."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

from agent_eval.schema import EpisodeResult
from agent_eval.storage import read_json

LABELS = {
    "r0v0a0": "Without protections",
    "r1v1a1": "With all protections",
    "r1v0a0": "Limit which tools can be used",
    "r0v1a0": "Check action details",
    "r0v0a1": "Require approval",
    "r1v1a0": "Tool limits + action checks",
    "r1v0a1": "Tool limits + approval",
    "r0v1a1": "Action checks + approval",
    "upstream_tool_filter": "AgentDojo's tool selection",
}

TOOLS = {
    "get_most_recent_transactions": "Read recent transactions",
    "get_balance": "Read account balance",
    "get_scheduled_transactions": "Read scheduled payments",
    "get_iban": "Read account number",
    "update_password": "Change the simulated account password",
    "send_money": "Send a simulated payment",
    "schedule_transaction": "Schedule a simulated payment",
    "update_scheduled_transaction": "Change a scheduled payment",
    "get_user_info": "Read account information",
    "update_user_info": "Change account information",
    "read_file": "Read a file",
    "get_file_by_id": "Read a file",
    "delete_file": "Delete a simulated file",
    "share_file": "Share a simulated file",
    "create_file": "Create a simulated file",
    "append_to_file": "Add content to a file",
    "get_unread_emails": "Read unread emails",
    "search_emails": "Search emails",
    "send_email": "Send a simulated email",
    "create_calendar_event": "Create a simulated calendar event",
    "search_calendar_events": "Search the calendar",
}


def label(condition):
    return LABELS.get(condition, condition.replace("_", " ").capitalize())


def case_key(row):
    spec = row.spec
    return spec.suite, spec.user_task, spec.injection_task, spec.attack, spec.repetition


def metrics(rows):
    finished = [r for r in rows if r.status == "completed"]
    ordinary = [r for r in finished if not r.spec.attack]
    attacked = [r for r in finished if r.spec.attack]
    return {
        "ordinary": {"yes": sum(bool(r.upstream_utility) for r in ordinary), "total": len(ordinary)},
        "attack": {"yes": sum(bool(r.upstream_attacker_success) for r in attacked), "total": len(attacked)},
        "under_attack": {"yes": sum(bool(r.upstream_utility) for r in attacked), "total": len(attacked)},
        "safe_under_attack": {
            "yes": sum(bool(r.upstream_utility) and not r.upstream_attacker_success for r in attacked),
            "total": len(attacked),
        },
    }


def comparison(rows, chosen):
    base = [r for r in rows if r.spec.condition == "r0v0a0"]
    other = [r for r in rows if r.spec.condition == chosen] if chosen else []
    left = {case_key(r): r for r in base if r.status == "completed"}
    right = {case_key(r): r for r in other if r.status == "completed"}
    paired = bool(base and other)
    if paired:
        matched = left.keys() & right.keys()
        baseline, protected = metrics([left[k] for k in matched]), metrics([right[k] for k in matched])
        missing = len({case_key(r) for r in base + other} - matched)
    else:
        baseline, protected, missing = metrics(base), metrics(other), 0
    data = {
        "condition": chosen or "r0v0a0",
        "name": label(chosen) if chosen else "No protected version tested",
        "without": baseline,
        "with": protected,
        "paired": paired,
        "missing_pairs": missing,
        "finished": sum(r.status == "completed" for r in base + other),
        "attempted": len(base + other),
        "unique_tasks": len({(r.spec.suite, r.spec.user_task) for r in base + other}),
    }
    data["explanation"] = interpret(data)
    return data


def interpret(data):
    if not data["paired"]:
        return "This run does not include both agent versions. Test both versions before judging what protections changed."
    left, right = data["without"], data["with"]
    text = []
    ordinary = left["ordinary"]["total"]
    attacks = left["attack"]["total"]
    if ordinary:
        delta = right["ordinary"]["yes"] - left["ordinary"]["yes"]
        text.append(
            "The protected version finished fewer ordinary tasks."
            if delta < 0
            else "The protected version finished more ordinary tasks."
            if delta > 0
            else "Neither version completed the ordinary task in this check."
            if left["ordinary"]["yes"] == 0
            else "Both versions finished the same number of ordinary tasks."
        )
    if attacks:
        a, b = left["attack"]["yes"], right["attack"]["yes"]
        text.append(
            "Neither version carried out the attacker's goal."
            if a == b == 0
            else "Fewer attacks succeeded with protections."
            if b < a
            else "More attacks succeeded with protections."
            if b > a
            else "The same number of attacks succeeded in both versions."
        )
        if right["under_attack"]["yes"] == 0:
            text.append("The protected version did not finish the user's task during the tested attacks.")
    if not ordinary and not attacks:
        text.append("There are no matching finished runs to compare yet. Check the run errors below.")
    return " ".join(text)


def build_summary(rows, manifest, coverage):
    conditions = sorted({r.spec.condition for r in rows})
    alternatives = [c for c in conditions if c != "r0v0a0"]
    chosen = "r1v1a1" if "r1v1a1" in alternatives else alternatives[0] if alternatives else "r0v0a0"
    return {
        "model": manifest["settings"].get("model") or "Scripted sample",
        "provider": manifest["settings"].get("provider", "openai"),
        "kind": manifest["kind"],
        "coverage": coverage,
        "default_condition": chosen,
        "conditions": conditions,
        "comparisons": [comparison(rows, c) for c in alternatives]
        if alternatives
        else [comparison(rows, None)],
        "outcomes": dict(Counter(outcome(r)[0] for r in rows)),
    }


def outcome(row):
    if row.status != "completed":
        return (
            "Run could not finish",
            "The software did not get a complete run. Its task and security outcome are unknown.",
            "unknown",
        )
    if row.spec.attack and row.upstream_attacker_success:
        return (
            "Attack succeeded",
            "The agent carried out the attacker's goal, even if it also did useful work.",
            "bad",
        )
    if row.upstream_utility:
        return (
            "User's task completed",
            (
                "The user's task was completed and the attacker's goal was not reached."
                if row.spec.attack
                else "The agent completed the ordinary task."
            ),
            "good",
        )
    return (
        "User's task not completed",
        (
            "The attacker did not achieve its goal, but the user's task was also unfinished."
            if row.spec.attack
            else "The run ended, but the agent did not accomplish what the user asked."
        ),
        "caution",
    )


@lru_cache(maxsize=256)
def task_story(suite, task, injection=None):
    try:
        from agentdojo.task_suite.load_suites import get_suite

        benchmark = get_suite("v1.2.2", suite)
        prompt = benchmark.user_tasks[task].PROMPT
        goal = benchmark.injection_tasks[injection].GOAL if injection else None
        return prompt, goal
    except (KeyError, ValueError):
        return (
            "Complete the requested simulated workflow.",
            "Carry out the separate attacker goal." if injection else None,
        )


def load_rows(directory):
    rows = []
    for path in sorted((Path(directory) / "episodes").glob("*.json")):
        data = read_json(path)
        data.update(messages=[], requests=[], injections={})
        # Exclude large arguments from this presentation-only aggregation.
        for action in data.get("actions", []):
            action.update(proposed_args={}, normalized_args=None)
        rows.append(EpisodeResult.model_validate(data))
    return rows


def read_dashboard(directory):
    directory = Path(directory)
    if (directory / "understand.json").exists():
        return read_json(directory / "understand.json")
    if (directory / "batch.json").exists():
        record = read_json(directory / "batch.json")
        models = []
        for item in record["models"]:
            path = directory / item["directory"] / "analysis/understand.json"
            if path.exists():
                models.extend(read_json(path).get("models", []))
            else:
                folder = directory / item["directory"]
                if (folder / "analysis/results.json").exists():
                    models.append(
                        build_summary(
                            load_rows(folder),
                            read_json(folder / "manifest.json"),
                            read_json(folder / "analysis/results.json")["coverage"],
                        )
                    )
        return {"models": models}
    manifest = read_json(directory / "manifest.json")
    coverage = read_json(directory / "analysis/results.json")["coverage"]
    return {"models": [build_summary(load_rows(directory), manifest, coverage)]}
