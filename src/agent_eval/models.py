from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

import openai
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.llms.openai_llm import (
    OpenAILLM,
    _function_to_openai,
    _message_to_openai,
    _openai_to_assistant_message,
)
from agentdojo.types import text_content_block_from_string

from agent_eval.storage import atomic_json, read_json


class BudgetExhausted(RuntimeError):
    pass


class InputLimit(RuntimeError):
    pass


class RunCancelled(RuntimeError):
    pass


class Budget:
    """Persist reservations BEFORE requests; a crash conservatively retains the reservation."""

    def __init__(self, path, limit):
        self.path, self.limit = path, limit
        data = read_json(path) if path.exists() else {"accounted_usd": 0.0, "requests": 0}
        self.accounted, self.requests = data["accounted_usd"], data["requests"]

    def save(self):
        atomic_json(
            self.path, {"accounted_usd": self.accounted, "requests": self.requests, "limit_usd": self.limit}
        )

    def reserve(self, amount):
        if self.limit is not None and self.accounted + amount > self.limit + 1e-12:
            raise BudgetExhausted("Insufficient budget for the next request's conservative reservation")
        self.accounted += amount
        self.requests += 1
        self.save()

    def settle(self, reserved, observed):
        self.accounted += observed - reserved
        self.save()


class MeteredTransport:
    def __init__(self, client, config, budget, stop_event=None):
        self.sdk, self.config, self.budget = client, config, budget
        self.stop_event = stop_event
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def safe_error(self, error):
        from agent_eval.providers import redact_error

        return redact_error(error, getattr(self.sdk, "api_key", None))

    def create(self, **kwargs):
        config = self.config
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        if config.reasoning_effort is not None:
            kwargs.setdefault("reasoning_effort", config.reasoning_effort)
        # JSON UTF-8 bytes + overhead is intentionally conservative; no remote call for over-limit inputs.
        byte_bound = (
            len(
                json.dumps(
                    {k: kwargs[k] for k in ["messages", "tools"] if k in kwargs},
                    ensure_ascii=False,
                    default=str,
                ).encode()
            )
            + 2048
        )
        if byte_bound > config.max_input_tokens:
            raise InputLimit(f"Conservative input bound {byte_bound} exceeds {config.max_input_tokens}")
        kwargs["max_tokens" if config.provider == "ollama" else "max_completion_tokens"] = (
            config.max_output_tokens
        )
        input_rate = (config.input_usd_per_million or 0) if config.provider == "openai" else 0
        output_rate = (config.output_usd_per_million or 0) if config.provider == "openai" else 0
        reserve = (config.max_input_tokens * input_rate + config.max_output_tokens * output_rate) / 1e6
        for attempt in range(3):
            if self.stop_event is not None and self.stop_event.is_set():
                raise RunCancelled("Stopped before the next model request")
            self.budget.reserve(reserve)
            started = time.perf_counter()
            record = {"attempt": attempt + 1, "status": "error", "reserved_usd": reserve}
            try:
                response = self.sdk.chat.completions.create(**kwargs)
                usage = response.usage
                observed = reserve
                if usage is not None:
                    observed = (
                        usage.prompt_tokens * input_rate + usage.completion_tokens * output_rate
                    ) / 1e6
                    record.update(
                        prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens
                    )
                    self.budget.settle(reserve, observed)
                record.update(
                    status="completed",
                    cost_usd_estimate=observed,
                    request_id=getattr(response, "_request_id", None),
                    response_model=response.model,
                    system_fingerprint=getattr(response, "system_fingerprint", None),
                    finish_reason=response.choices[0].finish_reason,
                )
                return response
            except Exception as exc:
                record.update(error=self.safe_error(exc), cost_usd_estimate=reserve, usage_unknown=True)
                if (
                    not isinstance(
                        exc, (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)
                    )
                    or attempt == 2
                ):
                    raise
                time.sleep(2**attempt)
            finally:
                record["duration_seconds"] = time.perf_counter() - started
                self.requests.append(record)


class InstrumentedLLM(OpenAILLM):
    def __init__(self, transport, config):
        super().__init__(
            transport, config.model, temperature=config.temperature, reasoning_effort=config.reasoning_effort
        )
        self.name = config.model
        self.provider = config.provider
        self.truncated = False

    def query(self, query, runtime, env=None, messages=(), extra_args=None):
        self.last_messages = list(messages)
        kwargs = {"model": self.model, "messages": [_message_to_openai(m, self.model) for m in messages]}
        if runtime.functions:
            kwargs.update(
                tools=[_function_to_openai(f) for f in runtime.functions.values()], tool_choice="auto"
            )
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            kwargs["reasoning_effort"] = self.reasoning_effort
        response = self.client.chat.completions.create(**kwargs)
        self.truncated |= response.choices[0].finish_reason in {"length", "content_filter"}
        output = _openai_to_assistant_message(response.choices[0].message)
        self.last_messages = [*messages, output]
        return query, runtime, env, [*messages, output], extra_args or {}


class ScriptedLLM(BasePipelineElement):
    """Offline fixture, never a substitute for measured LLM results."""

    name = "offline-script"

    def __init__(self, responses):
        self.responses = iter(copy.deepcopy(responses))

    def query(self, query, runtime, env=None, messages=(), extra_args=None):
        self.last_messages = list(messages)
        output = next(
            self.responses,
            {"role": "assistant", "content": [text_content_block_from_string("Done")], "tool_calls": None},
        )
        self.last_messages = [*messages, output]
        return query, runtime, env, self.last_messages, extra_args or {}
