"""Graphical results pages, built from existing scored episodes with no model calls."""

from __future__ import annotations

import base64
import os
from html import escape
from pathlib import Path
from urllib.parse import quote

from agent_eval.storage import atomic_json, read_json
from agent_eval.understand import TOOLS, build_summary, label, load_rows, outcome, task_story

ASSETS = Path(__file__).parent / "ui_assets"


def fraction(value):
    return f"{value['yes']} of {value['total']}" if value["total"] else "No comparable runs"


def bars(title, note, left, right, protected_name):
    items = []
    for name, value, color in [("Without protections", left, "plain"), (protected_name, right, "protected")]:
        width = 100 * value["yes"] / value["total"] if value["total"] else 0
        items.append(
            f'<div class="bar-row"><div class="bar-caption"><span>{escape(name)}</span>'
            f'<strong>{fraction(value)}</strong></div><div class="track" role="img" '
            f'aria-label="{escape(name, quote=True)}: {fraction(value)}"><div class="fill {color}" '
            f'style="width:{width:.3f}%"></div></div></div>'
        )
    return f'<div class="metric"><h3>{escape(title)}</h3><p class="direction">{escape(note)}</p>{"".join(items)}</div>'


def model_card(model, comparison, default):
    name = comparison["name"]
    protected = "With protections" if comparison["condition"] == "r1v1a1" else name
    charts = "".join(
        bars(title, note, comparison["without"][key], comparison["with"][key], protected)
        for key, title, note in [
            ("ordinary", "Did it finish the user's task?", "Ordinary inputs · more is better"),
            ("attack", "Did the attacker's goal succeed?", "Injected inputs · fewer is better"),
            ("under_attack", "Could it still do useful work?", "Injected inputs · more is better"),
        ]
    )
    ordinary = comparison["without"]["ordinary"]["total"]
    attacked = comparison["without"]["attack"]["total"]
    small = comparison["unique_tasks"] < 5 or min(ordinary, attacked) < 10
    caution = (
        f"Small check: {ordinary} ordinary and {attacked} attack case(s) per version, across "
        f"{comparison['unique_tasks']} user task(s). This cannot establish a reliable model ranking."
        if small
        else "These are descriptive results. Use the research exports for paired estimates and uncertainty."
    )
    if not comparison["paired"]:
        caution = "Both agent versions were not tested together. The bars show available runs, not a matched comparison."
    if comparison["missing_pairs"]:
        caution += f" {comparison['missing_pairs']} case(s) lack a finished matching run and are excluded from these bars."
    source = (
        "Scripted sample"
        if model["kind"] == "offline"
        else "Local Ollama model"
        if model["provider"] == "ollama"
        else "OpenAI model"
    )
    return (
        f'<article class="model-card" data-model="{escape(model["model"], quote=True)}" '
        f'data-condition="{comparison["condition"]}" {"hidden" if comparison["condition"] != default else ""}>'
        f'<div class="model-heading"><div><p class="eyebrow">{source}</p><h2>{escape(model["model"])}</h2></div>'
        f'<span class="pill">{escape(name)}</span></div><div class="chart-grid">{charts}</div>'
        f'<div class="takeaway"><strong>What this says</strong><p>{escape(comparison["explanation"])}</p></div>'
        f'<p class="sample-note">{escape(caution)}</p></article>'
    )


def case_html(row, directory, output):
    prompt, goal = task_story(row.spec.suite, row.spec.user_task, row.spec.injection_task)
    title, explanation, tone = outcome(row)
    tools = []
    for event in row.actions:
        if event.status == "proposed":
            continue
        status = {"executed": "Ran", "denied": "Blocked", "failed": "Could not run"}[event.status]
        tool = TOOLS.get(event.tool, event.tool.replace("_", " ").capitalize())
        tools.append(
            f'<li><span class="action-status {event.status}">{status}</span>'
            f"<div><strong>{escape(tool)}</strong><p>{escape(event.reason)}</p></div></li>"
        )
    file = Path(directory) / "episodes" / f"{row.spec.key}.json"
    href = quote(Path(os.path.relpath(file, output)).as_posix(), safe="/.")
    reply = ""
    if file.exists():
        messages = read_json(file).get("messages", [])
        for message in reversed(messages):
            if message.get("role") == "assistant" and message.get("content"):
                content = message["content"]
                reply = (
                    content
                    if isinstance(content, str)
                    else "\n".join(block.get("content", "") or "" for block in content)
                )
                break
    story = f'<p class="request"><strong>The user asked:</strong> {escape(prompt)}</p>'
    if goal:
        story += f'<p class="attack-goal"><strong>The attacker tried to:</strong> {escape(goal)}</p>'
    return (
        f'<details class="case"><summary><span class="outcome {tone}">{escape(title)}</span>'
        f"<span>{escape(label(row.spec.condition))} · {'Attack present' if row.spec.attack else 'Ordinary input'}</span></summary>"
        f'<p>{escape(explanation)}</p>{story}<ol class="actions">{"".join(tools) or "<li>The model replied without using a tool.</li>"}</ol>'
        f"{f'<blockquote><strong>Model’s final reply</strong><p>{escape(reply[:2500])}</p></blockquote>' if reply else ''}"
        f'<p class="error">{escape(row.error or "")}</p><a class="subtle-link" href="{href}">Research record (JSON)</a></details>'
    )


def render_page(output, packet, *, cases="", exports=""):
    output = Path(output)
    models = packet["models"]
    conditions = sorted({c["condition"] for m in models for c in m["comparisons"]})
    default = "r1v1a1" if "r1v1a1" in conditions else conditions[0] if conditions else "r0v0a0"
    model_options = "".join(
        f'<option value="{escape(m["model"], quote=True)}">{escape(m["model"])}</option>' for m in models
    )
    condition_options = "".join(
        f'<option value="{c}" {"selected" if c == default else ""}>{escape(label(c))}</option>'
        for c in conditions
    )
    cards = "".join(model_card(model, view, default) for model in models for view in model["comparisons"])
    errors = "".join(
        f'<article class="model-card"><h2>{escape(item["model"])}</h2>'
        f'<p class="error">This model did not produce a complete report: {escape(item.get("error", item["status"]))}</p></article>'
        for item in packet.get("errors", [])
    )
    offline = packet.get("offline", bool(models) and all(m["kind"] == "offline" for m in models))
    notice = (
        "Scripted integration tests — a software demonstration, not evidence about a real model."
        if offline
        else "These are observed results, not a safety guarantee. Small checks are for trying the system, not ranking models."
    )
    finished = sum(m["coverage"]["completed"] for m in models)
    scheduled = sum(m["coverage"]["scheduled"] for m in models)
    recorded = sum(m["coverage"]["recorded"] for m in models)
    failed = recorded - finished
    expected = packet.get("selected_models", len(models))
    values = {
        "STYLE": (ASSETS / "results.css").read_text(encoding="utf-8"),
        "SCRIPT": (ASSETS / "results.js").read_text(encoding="utf-8"),
        "NOTICE": escape(notice),
        "FINISHED": f"{finished} / {scheduled}",
        "FAILED": str(failed),
        "MODELS": f"{len(models)} / {expected}",
        "MODEL_OPTIONS": model_options,
        "CONDITION_OPTIONS": condition_options,
        "CARDS": cards + errors,
        "CASES": cases,
        "EXPORTS": exports,
        "SOURCE_NOTE": escape(
            packet.get(
                "source_note",
                "The charts compare matching cases where both agent versions finished. Counts are more informative than percentages in a tiny test.",
            )
        ),
    }
    template = (ASSETS / "results.html").read_text(encoding="utf-8")
    import re

    # One-pass substitution: untrusted text resembling a token remains literal text.
    html = re.sub(r"@@([A-Z_]+)@@", lambda match: values[match[1]], template)
    (output / "report.html").write_text(html, encoding="utf-8")
    atomic_json(output / "understand.json", packet)


def write_single_page(output, directory, manifest, coverage, summary, rows):
    output = Path(output)
    model = build_summary(rows, manifest, coverage)
    cases = "".join(
        case_html(row, directory, output)
        for row in sorted(
            rows, key=lambda r: (r.spec.attack is not None, r.spec.suite, r.spec.user_task, r.spec.condition)
        )[:50]
    )
    chart = base64.b64encode((output / "tradeoffs.png").read_bytes()).decode("ascii")
    exports = (
        '<p><a href="summary.csv">Summary CSV</a> · <a href="paired_differences.csv">Paired estimates and intervals</a> · '
        '<a href="episodes.csv">All test runs</a> · <a href="results.json">Analysis JSON</a> · <a href="report.md">Markdown</a></p>'
        f'<img class="export-chart" alt="All protection configurations, with readable labels" src="data:image/png;base64,{chart}">'
    )
    render_page(output, {"models": [model]}, cases=cases, exports=exports)


def write_batch_page(directory, record):
    directory = Path(directory)
    models, reports, errors = [], [], []
    for item in record["models"]:
        folder = directory / item["directory"]
        if not (folder / "manifest.json").exists() or not (folder / "analysis/results.json").exists():
            errors.append(item)
            continue
        manifest = read_json(folder / "manifest.json")
        coverage = read_json(folder / "analysis/results.json")["coverage"]
        models.append(build_summary(load_rows(folder), manifest, coverage))
        if item.get("report"):
            reports.append(
                f'<a class="report-link" href="{quote(item["report"], safe="/.")}">'
                f"<strong>{escape(item['model'])}</strong><span>See the task, the attack, and what the agent actually did →</span></a>"
            )
    source = "Charts compare matching finished cases. Open a model's report below to see individual tasks and actions."
    if record.get("unstarted_models"):
        source += f" {record['unstarted_models']} selected model(s) did not start."
    render_page(
        directory,
        {
            "models": models,
            "errors": errors,
            "selected_models": len(record["configurations"]),
            "source_note": source,
        },
        cases="".join(reports),
        exports='<a href="comparison.csv">Comparison CSV</a> · <a href="batch.json">Research configuration and run status</a>',
    )
