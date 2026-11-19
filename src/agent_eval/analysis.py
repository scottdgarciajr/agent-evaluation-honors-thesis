from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from agent_eval.schema import EpisodeResult
from agent_eval.storage import atomic_json, read_json


def cluster_interval(values_by_task, samples=2000, seed=20261117):
    """Resample whole user tasks; preserve all case/repetition observations within each task."""
    if not values_by_task:
        return None, None
    clusters = [np.asarray(v, dtype=float) for _, v in sorted(values_by_task.items()) if v]
    if len(clusters) < 2:
        return None, None
    sums = np.array([v.sum() for v in clusters])
    counts = np.array([len(v) for v in clusters])
    picks = np.random.default_rng(seed).integers(0, len(clusters), size=(samples, len(clusters)))
    estimates = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    return tuple(float(x) for x in np.quantile(estimates, [0.025, 0.975]))


def metric(row, name):
    if name == "safe_completion":
        return float(row.upstream_utility and not row.upstream_attacker_success)
    return float(getattr(row, name))


def write_csv(path, rows):
    if not rows:
        Path(path).write_text("", encoding="utf-8")
        return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def summarize(results):
    groups = defaultdict(list)
    for row in results:
        key = (row.spec.suite, row.spec.condition, row.spec.attack or "benign", row.workflow, row.spec.split)
        groups[key].append(row)
    summaries = []
    for key, rows in sorted(groups.items()):
        completed = [r for r in rows if r.status == "completed"]
        item = dict(zip(["suite", "condition", "attack", "workflow", "split"], key))
        item.update(attempted=len(rows), completed=len(completed), coverage=len(completed) / len(rows))
        item.update({f"status_{k}": v for k, v in Counter(r.status for r in rows).items()})
        names = ["upstream_utility", "execution_utility"]
        if key[2] != "benign":
            names += ["upstream_attacker_success", "execution_attacker_success", "safe_completion"]
        for name in names:
            valid = [r for r in completed if name == "safe_completion" or getattr(r, name) is not None]
            values = defaultdict(list)
            for r in valid:
                values[r.spec.user_task].append(metric(r, name))
            item[name] = float(np.mean([v for vs in values.values() for v in vs])) if valid else None
            item[f"{name}_ci_low"], item[f"{name}_ci_high"] = cluster_interval(values)
            successes = sum(metric(r, name) for r in valid)
            item[f"{name}_attempted_lower_bound"] = successes / len(rows)
            item[f"{name}_attempted_upper_bound"] = (successes + len(rows) - len(valid)) / len(rows)
        terminal = [a for r in rows for a in r.actions if a.status != "proposed"]
        item.update(
            actions_proposed=sum(a.status == "proposed" for r in rows for a in r.actions),
            actions_executed=sum(a.status == "executed" for a in terminal),
            actions_denied=sum(a.status == "denied" for a in terminal),
            policy_violations_attempted=sum(a.policy_violation for a in terminal),
            policy_violations_executed=sum(a.policy_violation and a.status == "executed" for a in terminal),
            approvals_per_episode=sum(a.approval_requested for a in terminal) / len(rows),
            approval_denials=sum(a.approval_granted is False for a in terminal),
            cost_usd_estimate=sum(r.cost_usd_estimate for r in rows),
            prompt_tokens=sum(r.prompt_tokens for r in rows),
            completion_tokens=sum(r.completion_tokens for r in rows),
            mean_duration_seconds=float(np.mean([r.duration_seconds for r in rows])),
            mean_action_boundary_seconds=float(
                np.mean([sum(a.duration_seconds for a in r.actions if a.status != "proposed") for r in rows])
            ),
            mean_policy_seconds=float(
                np.mean([sum(a.policy_seconds for a in r.actions if a.status != "proposed") for r in rows])
            ),
            mean_manual_approval_wait_seconds=float(
                np.mean(
                    [sum(a.approval_wait_seconds for a in r.actions if a.status != "proposed") for r in rows]
                )
            ),
        )
        summaries.append(item)
    return summaries


def paired_differences(results):
    baseline = {
        (r.spec.suite, r.spec.user_task, r.spec.injection_task, r.spec.attack, r.spec.repetition): r
        for r in results
        if r.spec.condition == "r0v0a0" and r.status == "completed"
    }
    groups = defaultdict(list)
    for row in results:
        if row.spec.condition == "r0v0a0" or row.status != "completed":
            continue
        base = baseline.get(
            (
                row.spec.suite,
                row.spec.user_task,
                row.spec.injection_task,
                row.spec.attack,
                row.spec.repetition,
            )
        )
        if base is None:
            continue
        for name in ["upstream_utility", "execution_utility"] + (
            ["upstream_attacker_success", "safe_completion"] if row.spec.attack else []
        ):
            key = (
                row.spec.suite,
                row.spec.condition,
                row.spec.attack or "benign",
                row.workflow,
                row.spec.split,
                name,
            )
            groups[key].append((row.spec.user_task, metric(row, name) - metric(base, name)))
    output = []
    for key, pairs in sorted(groups.items()):
        by_task = defaultdict(list)
        for task, value in pairs:
            by_task[task].append(value)
        low, high = cluster_interval(by_task)
        output.append(
            dict(zip(["suite", "condition", "attack", "workflow", "split", "metric"], key))
            | {
                "matched_episodes": len(pairs),
                "user_task_clusters": len(by_task),
                "delta_vs_baseline": float(np.mean([v for _, v in pairs])),
                "ci_low": low,
                "ci_high": high,
            }
        )
    return output


def portfolio_results(results, expected_attacks):
    groups = defaultdict(list)
    for r in results:
        if r.spec.attack:
            groups[
                (r.spec.suite, r.spec.user_task, r.spec.injection_task, r.spec.condition, r.spec.repetition)
            ].append(r)
    output = []
    for key, rows in sorted(groups.items()):
        complete = {r.spec.attack for r in rows if r.status == "completed"} == set(expected_attacks)
        any_success = any(r.upstream_attacker_success for r in rows if r.status == "completed")
        output.append(
            dict(zip(["suite", "user_task", "injection_task", "condition", "repetition"], key))
            | {
                "portfolio_complete": complete,
                "any_attacker_success": any_success if complete else None,
                "observed_success_lower_bound": any_success,
            }
        )
    return output


def analyze(directory, output=None):
    directory = Path(directory)
    output = Path(output) if output else directory / "analysis"
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(directory / "manifest.json")
    results = []
    for path in sorted((directory / "episodes").glob("*.json")):
        row = EpisodeResult.model_validate(read_json(path))
        # Raw trajectories stay on disk; analysis retains only fields needed for aggregation.
        row = row.model_copy(
            update={
                "messages": [],
                "requests": [],
                "injections": {},
                "actions": [
                    a.model_copy(update={"proposed_args": {}, "normalized_args": None}) for a in row.actions
                ],
            }
        )
        results.append(row)
    if not results:
        raise ValueError("No episode records to analyze")
    if any(r.experiment_sha256 != manifest["experiment_sha256"] for r in results):
        raise ValueError("Mixed experiment hashes")
    summary = summarize(results)
    paired = paired_differences(results)
    portfolio = portfolio_results(results, manifest["settings"]["attacks"])
    write_csv(output / "summary.csv", summary)
    write_csv(output / "paired_differences.csv", paired)
    write_csv(output / "attack_portfolio.csv", portfolio)
    write_csv(
        output / "episodes.csv",
        [
            {
                **r.spec.model_dump(),
                "status": r.status,
                "upstream_utility": r.upstream_utility,
                "upstream_attacker_success": r.upstream_attacker_success,
                "execution_attacker_success": r.execution_attacker_success,
                "cost_usd_estimate": r.cost_usd_estimate,
                "duration_seconds": r.duration_seconds,
                "error": r.error,
            }
            for r in results
        ],
    )
    scheduled = manifest["matrix_episodes"]
    coverage = {
        "scheduled": scheduled,
        "recorded": len(results),
        "completed": sum(r.status == "completed" for r in results),
        "unattempted": scheduled - len(results),
        "kind": manifest["kind"],
    }
    if (directory / "budget.json").exists():
        coverage["budget_accounted_usd"] = read_json(directory / "budget.json")["accounted_usd"]
    archived_cost = 0.0
    archived_count = 0
    for path in (directory / "attempts").glob("*.json"):
        archived_count += 1
        archived_cost += read_json(path)["cost_usd_estimate"]
    coverage["archived_attempts"] = archived_count
    coverage["archived_cost_usd_estimate"] = archived_cost
    atomic_json(
        output / "results.json",
        {"coverage": coverage, "summary": summary, "paired": paired, "attack_portfolio": portfolio},
    )
    label = (
        "OFFLINE SCRIPTED FIXTURE — not LLM evidence"
        if manifest["kind"] == "offline"
        else "Live model evaluation"
    )
    _plot(results, output, label)
    lines = [
        f"# {label}",
        "",
        f"Scheduled: {scheduled}; recorded: {len(results)}; completed: {coverage['completed']}.",
        "",
        "Rates use completed episodes. Inspect coverage and missing-outcome bounds in summary.csv.",
        "Paired comparisons use matching completed episodes; intervals resample entire user tasks.",
        "Intervals are omitted for fewer than two task clusters. Deltas are treatment minus baseline.",
        "A negative benign-utility delta is utility lost. Policy violations refer to the configured deployment policy.",
        "",
        "| Suite | Condition | Attack | Workflow | Completed / attempted | Utility | Attacker success |",
        "|---|---|---|---|---|---|---|",
    ]

    def fmt(x):
        return "—" if x is None else f"{x:.1%}"

    for row in summary:
        lines.append(
            f"| {row['suite']} | {row['condition']} | {row['attack']} | {row['workflow']} | "
            f"{row['completed']}/{row['attempted']} | {fmt(row['upstream_utility'])} | "
            f"{fmt(row.get('upstream_attacker_success'))} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    from agent_eval.report import write_html

    write_html(output, directory, manifest, coverage, summary, results)
    return coverage


def _plot(results, output, label):
    import matplotlib

    matplotlib.use("Agg")
    from textwrap import fill

    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    from agent_eval.understand import label as readable_label

    conditions = sorted({r.spec.condition for r in results})
    fig, axes = plt.subplots(
        1, 2, figsize=(14, max(5, 0.65 * len(conditions) + 2)), sharey=True, constrained_layout=True
    )
    for ax, attacked, title, field in [
        (axes[0], False, "User's task completed\nOrdinary inputs · more is better", "upstream_utility"),
        (
            axes[1],
            True,
            "Attacker's goal achieved\nInjected inputs · fewer is better",
            "upstream_attacker_success",
        ),
    ]:
        values = []
        counts = []
        for condition in conditions:
            rows = [
                r
                for r in results
                if r.spec.condition == condition
                and bool(r.spec.attack) == attacked
                and r.status == "completed"
            ]
            yes = sum(bool(getattr(r, field)) for r in rows)
            values.append(yes / len(rows) if rows else 0)
            counts.append((yes, len(rows)))
        colors = [
            "#5168c9" if c == "r0v0a0" else "#087f7c" if c == "r1v1a1" else "#7590b0" for c in conditions
        ]
        ax.barh(range(len(conditions)), values, color=colors, height=0.6)
        ax.set_yticks(range(len(conditions)), [fill(readable_label(c), 25) for c in conditions])
        for position, (value, (yes, n)) in enumerate(zip(values, counts)):
            ax.text(
                0.97 if value > 0.8 else value + 0.02,
                position,
                f"{yes} of {n}" if n else "No finished runs",
                va="center",
                ha="right" if value > 0.8 else "left",
                color="white" if value > 0.8 else "#25364c",
                fontsize=10,
            )
        ax.set_xlim(0, 1)
        ax.set_title(title)
        ax.xaxis.set_major_formatter(PercentFormatter(1))
        ax.set_xlabel("Share of finished test runs")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].invert_yaxis()
    fig.suptitle(
        label + "\nA finished run is not necessarily a successful task. Counts are printed on the bars.",
        fontsize=11,
    )
    fig.savefig(output / "tradeoffs.png", dpi=200)
    fig.savefig(output / "tradeoffs.pdf")
    plt.close(fig)
