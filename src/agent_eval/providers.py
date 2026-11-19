"""Provider discovery and Ollama's native chat adapter. Credentials never enter configuration."""

from __future__ import annotations

import copy
import json
import re
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import httpx
import openai
from openai.types.chat import ChatCompletion
from pydantic import Field

from agent_eval.schema import StrictModel


def endpoint_url(value):
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/v1"}
    ):
        raise ValueError("Enter an http(s) Ollama server URL, without credentials, query, or custom path")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def redact_error(error, secret=None):
    text = f"{type(error).__name__}: {error}" if isinstance(error, Exception) else str(error)
    if secret:
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"sk-[A-Za-z0-9_*\-]+", "[redacted]", text)
    return text


class ModelInfo(StrictModel):
    name: str
    provider: str
    compatible: bool | None = None
    capabilities: tuple[str, ...] = ()
    size_bytes: int = 0
    digest: str | None = None
    details: dict = Field(default_factory=dict)
    reason: str = "Tool support not verified"


def discover_ollama(url="http://127.0.0.1:11434", timeout=10):
    endpoint = endpoint_url(url)
    with httpx.Client(base_url=endpoint, timeout=timeout, trust_env=False) as client:
        response = client.get("/api/tags")
        response.raise_for_status()
        models = []
        for entry in response.json().get("models", []):
            capabilities = entry.get("capabilities")
            if capabilities is None:
                info = client.post("/api/show", json={"model": entry["name"]})
                info.raise_for_status()
                capabilities = info.json().get("capabilities")
            compatible = None if capabilities is None else "tools" in capabilities
            models.append(
                ModelInfo(
                    name=entry["name"],
                    provider="ollama",
                    compatible=compatible,
                    capabilities=tuple(capabilities or ()),
                    size_bytes=entry.get("size", 0),
                    digest=entry.get("digest"),
                    details=entry.get("details", {}),
                    reason="Tool calling supported"
                    if compatible
                    else "Tool calling not reported"
                    if compatible is None
                    else "Not eligible: model does not advertise tool calling",
                )
            )
    return sorted(models, key=lambda m: m.name.casefold())


def discover_openai(api_key=None):
    client = openai.OpenAI(api_key=api_key, max_retries=0, timeout=20)
    try:
        # /models reports availability, not a reliable per-model tool capability specification.
        excluded = ("text-embedding", "whisper", "tts-", "dall-e", "gpt-image", "omni-moderation")
        return [
            ModelInfo(
                name=m.id, provider="openai", reason="Available to your account; tool support unverified"
            )
            for m in sorted(client.models.list().data, key=lambda x: x.id)
            if not m.id.startswith(excluded)
            and not any(s in m.id for s in ("realtime", "transcribe", "audio"))
        ]
    finally:
        client.close()


class OllamaClient:
    """Translate the shared tool-calling interface to /api/chat with explicit context limits."""

    def __init__(self, config):
        self.config = config
        self.http = httpx.Client(
            base_url=endpoint_url(config.ollama_url), timeout=config.request_timeout_seconds, trust_env=False
        )
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def close(self):
        self.http.close()

    def create(self, **kwargs):
        messages = copy.deepcopy(kwargs["messages"])
        for message in messages:
            if message["role"] == "developer":
                message["role"] = "system"
            content = message.get("content")
            if isinstance(content, list):
                message["content"] = "\n".join(p.get("text", "") for p in content)
            elif content is None:
                message["content"] = ""
            if message["role"] == "tool":
                message["tool_name"] = message.pop("name", "")
                message.pop("tool_call_id", None)
            for call in message.get("tool_calls", []):
                call.pop("id", None)
                call.pop("type", None)
                arguments = call["function"]["arguments"]
                if isinstance(arguments, str):
                    call["function"]["arguments"] = json.loads(arguments)
        options = {
            "num_ctx": self.config.ollama_context_tokens
            or self.config.max_input_tokens + self.config.max_output_tokens + 2048,
            "num_predict": kwargs.get("max_tokens", self.config.max_output_tokens),
        }
        if "temperature" in kwargs:
            options["temperature"] = kwargs["temperature"]
        tools = kwargs.get("tools", [])
        # The upstream pre-filter requests a text-only list. Native Ollama lacks tool_choice.
        if kwargs.get("tool_choice") == "none" and tools:
            messages.append(
                {
                    "role": "user",
                    "content": "Available tool definitions for selection only:\n"
                    + json.dumps(tools)
                    + "\nReturn tool names as text; do not execute tools.",
                }
            )
            tools = []
        payload = {"model": kwargs["model"], "messages": messages, "stream": False, "options": options}
        if tools:
            payload["tools"] = tools
        if self.config.ollama_think is not None:
            payload["think"] = self.config.ollama_think
        response = self.http.post("/api/chat", json=payload)
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise RuntimeError(body["error"])
        message = body.get("message", {})
        calls = [
            {
                "id": f"ollama-{uuid.uuid4().hex}",
                "type": "function",
                "function": {
                    "name": call["function"]["name"],
                    "arguments": json.dumps(call["function"].get("arguments", {})),
                },
            }
            for call in message.get("tool_calls", [])
        ]
        reason = "length" if body.get("done_reason") == "length" else "tool_calls" if calls else "stop"
        usage = None
        if body.get("prompt_eval_count") is not None and body.get("eval_count") is not None:
            prompt, completion = body["prompt_eval_count"], body["eval_count"]
            usage = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            }
        return ChatCompletion(
            id=f"ollama-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=body.get("model", kwargs["model"]),
            object="chat.completion",
            usage=usage,
            choices=[
                {
                    "index": 0,
                    "finish_reason": reason,
                    "message": {
                        "role": "assistant",
                        "content": message.get("content", ""),
                        "tool_calls": calls or None,
                    },
                }
            ],
        )
