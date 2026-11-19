from test_runner_analysis import result

from agent_eval.report import condition_label, write_html
from agent_eval.storage import atomic_json


def test_report_escapes_text_and_keeps_template_tokens_literal(tmp_path):
    from agent_eval.analysis import summarize

    row = result(status="error").model_copy(update={"error": "<script>alert(1)</script> @@TITLE@@"})
    (tmp_path / "tradeoffs.png").write_bytes(b"fixture-image")
    atomic_json(tmp_path / "episodes" / f"{row.spec.key}.json", row.model_dump(mode="json"))
    write_html(
        tmp_path,
        tmp_path,
        {"kind": "offline", "settings": {"model": None}},
        {"completed": 0, "scheduled": 1, "recorded": 1, "unattempted": 0},
        summarize([row]),
        [row],
    )
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt; @@TITLE@@" in html
    assert "<script>alert(1)</script>" not in html
    assert "Scripted integration tests" in html
    assert "0 / 1" in html
    assert f"episodes/{row.spec.key}.json" in html
    assert "data:image/png;base64," in html
    assert "summary.csv" in html


def test_condition_labels_explain_the_controls():
    assert condition_label("r0v0a0") == "Baseline"
    assert condition_label("r1v0a1") == "Tool restriction + Approval"
    assert condition_label("upstream_tool_filter") == "AgentDojo tool filter"
