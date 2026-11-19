from agentdojo.agent_pipeline.agent_pipeline import TOOL_FILTER_PROMPT, AgentPipeline, load_system_message
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLMToolFilter
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop, ToolsExecutor


class RecordingToolsExecutor(ToolsExecutor):
    def query(self, query, runtime, env=None, messages=(), extra_args=None):
        # Native ToolsExecutor rejects unavailable names before dispatch. Log those attempts too.
        if messages and messages[-1]["role"] == "assistant":
            calls = messages[-1].get("tool_calls") or []
            if calls:
                results = []
                for call in calls:
                    if call.function not in runtime.functions:
                        runtime.run_function(env, call.function, call.args)
                    single = {**messages[-1], "tool_calls": [call]}
                    _, _, _, updated, _ = super().query(
                        query, runtime, env, [*messages[:-1], single], extra_args or {}
                    )
                    results.extend(updated[len(messages) :])
                return query, runtime, env, [*messages, *results], extra_args or {}
        return super().query(query, runtime, env, messages, extra_args or {})


def build_pipeline(llm, condition, max_steps=15):
    elements = [SystemMessage(load_system_message(None)), InitQuery()]
    if condition.upstream_filter:
        elements.append(OpenAILLMToolFilter(TOOL_FILTER_PROMPT, llm.client, llm.model, llm.temperature))
    elements.extend([llm, ToolsExecutionLoop([RecordingToolsExecutor(), llm], max_iters=max_steps)])
    pipeline = AgentPipeline(elements)
    pipeline.name = f"{llm.name}-{condition.name}"
    pipeline.provider = getattr(llm, "provider", "openai")
    return pipeline
