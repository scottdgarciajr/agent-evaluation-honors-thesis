"""Local, self-contained results viewer. All model-controlled text is HTML escaped."""


def condition_label(name):
    if name == "upstream_tool_filter":
        return "AgentDojo tool filter"
    if name == "r0v0a0":
        return "Baseline"
    labels = [
        label
        for position, label in [(1, "Tool restriction"), (3, "Validation"), (5, "Approval")]
        if len(name) == 6 and name[position] == "1"
    ]
    return " + ".join(labels) or name


def write_html(output, directory, manifest, coverage, summary, results):
    from agent_eval.result_pages import write_single_page

    write_single_page(output, directory, manifest, coverage, summary, results)
