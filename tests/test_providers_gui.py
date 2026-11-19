import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from openai.types.chat import ChatCompletion

from agent_eval.batch import model_folder, run_batch
from agent_eval.models import Budget, MeteredTransport
from agent_eval.providers import OllamaClient, discover_ollama, endpoint_url, redact_error
from agent_eval.runner import run_live
from agent_eval.schema import ExperimentConfig
from agent_eval.storage import read_json


@pytest.mark.parametrize(
    "url",
    [
        "http://user:key@localhost:11434",
        "http://localhost:11434?token=key",
        "file:///tmp/server",
        "http://localhost/api",
        "https://localhost/#key",
    ],
)
def test_ollama_endpoint_rejects_embedded_credentials_and_ambiguous_paths(url):
    with pytest.raises(ValueError):
        endpoint_url(url)


def test_discovery_separates_tools_embeddings_and_unsupported_models(monkeypatch):
    original = httpx.Client

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "tool:small",
                            "capabilities": ["completion", "tools"],
                            "digest": "pinned",
                            "size": 100,
                        },
                        {"name": "embedding", "capabilities": ["embedding"]},
                        {"name": "older"},
                    ]
                },
            )
        assert request.url.path == "/api/show"
        return httpx.Response(200, json={"capabilities": ["completion"]})

    monkeypatch.setattr(
        "agent_eval.providers.httpx.Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    models = {m.name: m for m in discover_ollama()}
    assert models["tool:small"].compatible and models["tool:small"].digest == "pinned"
    assert models["embedding"].compatible is False
    assert models["older"].compatible is False


def test_native_ollama_translation_preserves_context_tools_and_tool_results():
    cfg = ExperimentConfig(
        provider="ollama",
        model="fixture",
        max_input_tokens=4096,
        max_output_tokens=256,
        ollama_context_tokens=8192,
        ollama_think=False,
    )
    client = OllamaClient(cfg)
    client.http.close()
    observed = []

    def handle(request):
        body = json.loads(request.content)
        observed.append(body)
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "model": "fixture",
                "done": True,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "add", "arguments": {"a": 2, "b": 3}}}],
                },
                "prompt_eval_count": 10,
                "eval_count": 4,
                "done_reason": "stop",
            },
        )

    client.http = httpx.Client(base_url="http://fixture", transport=httpx.MockTransport(handle))
    try:
        response = client.create(
            model="fixture",
            max_tokens=256,
            messages=[
                {"role": "developer", "content": [{"type": "text", "text": "Trusted"}]},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "old",
                            "type": "function",
                            "function": {"name": "add", "arguments": '{"a":2,"b":3}'},
                        }
                    ],
                },
                {"role": "tool", "name": "add", "tool_call_id": "old", "content": "5"},
            ],
        )
    finally:
        client.close()
    assert observed[0]["options"] == {"num_ctx": 8192, "num_predict": 256}
    assert observed[0]["messages"][0] == {"role": "system", "content": "Trusted"}
    assert observed[0]["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"a": 2, "b": 3}
    assert observed[0]["messages"][2]["tool_name"] == "add"
    assert response.choices[0].finish_reason == "tool_calls"
    assert response.usage.total_tokens == 14
    assert json.loads(response.choices[0].message.tool_calls[0].function.arguments) == {"a": 2, "b": 3}


def test_ollama_metering_uses_zero_api_charge_without_prices(tmp_path):
    cfg = ExperimentConfig(provider="ollama", model="fixture")
    observed = []

    def create(**kwargs):
        observed.append(kwargs)
        return completion()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    budget = Budget(tmp_path / "budget.json", None)
    transport = MeteredTransport(client, cfg, budget)
    transport.create(model="fixture", messages=[{"role": "user", "content": "hello"}])
    assert "max_tokens" in observed[0] and "max_completion_tokens" not in observed[0]
    assert budget.accounted == 0 and budget.requests == 1


def completion():
    return ChatCompletion(
        id="fixture",
        created=0,
        model="fixture",
        object="chat.completion",
        usage={"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000},
        choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Done"}}],
    )


def test_ollama_runner_needs_no_openai_key_and_captures_model_digest(tmp_path, monkeypatch):
    from agent_eval.providers import ModelInfo

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "agent_eval.providers.discover_ollama",
        lambda _: [ModelInfo(name="fixture", provider="ollama", compatible=True, digest="fixed")],
    )
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: completion())))
    monkeypatch.setattr("agent_eval.providers.OllamaClient", lambda _: fake)
    cfg = ExperimentConfig(
        provider="ollama",
        model="fixture",
        suites=("banking",),
        conditions=("r0v0a0",),
        attacks=(),
        task_ids=("user_task_14",),
        split="dev",
        repetitions=1,
    )
    result = run_live(cfg, tmp_path)
    assert result["attempted_this_invocation"] == 1 and result["accounted_usd"] == 0
    assert read_json(tmp_path / "manifest.json")["model_metadata"]["digest"] == "fixed"
    assert next((tmp_path / "episodes").glob("*.json")).is_file()


def test_batch_shares_openai_budget_across_models_and_never_saves_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return completion()

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("agent_eval.runner.openai.OpenAI", lambda **_: fake)
    configs = [
        ExperimentConfig(
            provider="openai",
            model=name,
            suites=("banking",),
            conditions=("r0v0a0",),
            attacks=(),
            task_ids=("user_task_14",),
            split="dev",
            repetitions=1,
            max_cost_usd=0.035,
            input_usd_per_million=1,
            output_usd_per_million=1,
        )
        for name in ["first", "second"]
    ]
    record = run_batch(configs, tmp_path, api_key="sk-fixture-secret")
    assert len(calls) == 1
    assert record["models"][0]["status"] == "completed"
    assert record["models"][1]["status"] == "partial"
    assert record["accounted_usd"] == pytest.approx(0.003)
    assert (tmp_path / "report.html").is_file()
    assert all("sk-fixture-secret" not in p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.json"))


def test_cancel_before_batch_does_not_start_any_models(tmp_path):
    stop = threading.Event()
    stop.set()
    record = run_batch([ExperimentConfig(provider="ollama", model="fixture")], tmp_path, stop_event=stop)
    assert record["stopped"] and record["unstarted_models"] == 1
    assert not record["models"]


def test_stop_after_model_start_is_not_reported_as_an_error(tmp_path, monkeypatch):
    from agent_eval.providers import ModelInfo

    stop = threading.Event()
    monkeypatch.setattr(
        "agent_eval.providers.discover_ollama",
        lambda _: [ModelInfo(name="fixture", provider="ollama", compatible=True)],
    )
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_: pytest.fail("A stopped batch must not make a model request")
            )
        )
    )
    monkeypatch.setattr("agent_eval.providers.OllamaClient", lambda _: fake)
    cfg = ExperimentConfig(
        provider="ollama",
        model="fixture",
        suites=("banking",),
        conditions=("r0v0a0",),
        attacks=(),
        task_ids=("user_task_14",),
        split="dev",
        repetitions=1,
    )

    def progress(event):
        if event["stage"] == "model_start":
            stop.set()

    record = run_batch([cfg], tmp_path, stop_event=stop, progress=progress)
    assert record["models"][0]["status"] == "stopped"
    assert record["models"][0]["scheduled"] == 1


def test_errors_and_folder_names_do_not_leak_keys_or_escape_output():
    assert "sk-" not in redact_error(RuntimeError("Incorrect key sk-fixture-secret"))
    assert ".." not in model_folder("ollama", "../../bad/model")


def test_gui_selection_configs_and_preferences_exclude_api_keys(tmp_path, monkeypatch):
    import tkinter as tk

    from agent_eval import gui
    from agent_eval.providers import ModelInfo

    monkeypatch.setattr(gui, "PROJECT", tmp_path)
    monkeypatch.setattr(gui.EvaluationApp, "refresh_models", lambda _: None)
    root = tk.Tk()
    root.withdraw()
    try:
        app = gui.EvaluationApp(root)
        app.inventory = [
            ModelInfo(name="tool", provider="ollama", compatible=True),
            ModelInfo(name="embedding", provider="ollama", compatible=False),
        ]
        app.select_all()
        assert app.checked == {"tool"}
        configs = app._configs()
        assert len(configs) == 1 and configs[0].provider == "ollama"
        assert configs[0].max_cost_usd is None
        app.clear_selection()
        assert not app.checked
        gui.save_preferences(
            tmp_path / "preferences.json",
            {"provider": "openai", "api_key": "sk-secret", "OPENAI_API_KEY": "sk-secret", "prices": {}},
        )
        assert "sk-secret" not in (tmp_path / "preferences.json").read_text()
    finally:
        root.destroy()
