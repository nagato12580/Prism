import json
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

try:
    from langchain_openai import ChatOpenAI
except ModuleNotFoundError:
    ChatOpenAI = None

from .events import (
    agent_status_event,
    clarify_event,
    done_event,
    error_event,
    sources_event,
    token_event,
    tool_call_event,
    tool_result_event,
)
from .prompts import AGENT_SYSTEM_PROMPT


def create_chat_model(settings):
    if ChatOpenAI is None:
        raise RuntimeError("langchain_openai is not installed")
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        base_url=settings.LLM_API_BASE,
        api_key=settings.LLM_API_KEY,
    )


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return str(content)


def _call_value(tool_call: Any, key: str, default: Any = None) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get(key, default)
    return getattr(tool_call, key, default)


class LangChainAgentRunner:
    def __init__(
        self,
        model: Any,
        tools: list[Any],
        system_prompt: str = AGENT_SYSTEM_PROMPT,
        max_iterations: int = 5,
    ) -> None:
        self.model = model
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.tool_map = {tool.name: tool for tool in tools}

    def stream(self, query: str, history: list[dict[str, Any]] | None = None):
        yield agent_status_event("analyzing question")

        try:
            messages = self._build_messages(query, history or [])
            model = self.model.bind_tools(self.tools) if self.tools else self.model

            for _ in range(self.max_iterations):
                response = model.invoke(messages)
                tool_calls = getattr(response, "tool_calls", None) or []
                if not tool_calls:
                    text = _message_content(response)
                    if text:
                        yield token_event(text)
                    yield done_event()
                    return

                messages.append(response)
                for tool_call in tool_calls:
                    name = str(_call_value(tool_call, "name", ""))
                    args = _call_value(tool_call, "args", {}) or {}
                    if not isinstance(args, dict):
                        args = {}
                    query_arg = str(args.get("query") or args.get("question") or "")
                    yield tool_call_event(name, query_arg)

                    result_text, payload, status, latency_ms = self._invoke_tool(
                        name, args
                    )
                    summary = str(
                        payload.get("summary")
                        or payload.get("question")
                        or result_text
                    )
                    yield tool_result_event(
                        tool=name,
                        status=status,
                        summary=summary,
                        query=query_arg,
                        stats=payload.get("stats"),
                        latency_ms=latency_ms,
                    )

                    sources = payload.get("sources") or []
                    if sources:
                        yield sources_event(sources)

                    if payload.get("status") == "clarify":
                        yield clarify_event(
                            str(payload.get("question", "I need more information.")),
                            list(payload.get("options") or []),
                        )
                        yield done_event()
                        return

                    messages.append(
                        ToolMessage(
                            content=result_text,
                            tool_call_id=str(_call_value(tool_call, "id", name)),
                        )
                    )

            yield error_event("Agent reached the maximum tool iteration limit.")
            yield done_event()
        except Exception as exc:
            yield error_event(str(exc))
            yield done_event()

    def _build_messages(self, query: str, history: list[dict[str, Any]]) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=self.system_prompt)]
        for item in history:
            role = item.get("role")
            content = item.get("content", "")
            if role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "user":
                messages.append(HumanMessage(content=content))
        messages.append(HumanMessage(content=query))
        return messages

    def _invoke_tool(
        self, name: str, args: dict[str, Any]
    ) -> tuple[str, dict[str, Any], str, int]:
        started = time.monotonic()
        status = "success"
        tool = self.tool_map.get(name)

        if tool is None:
            status = "error"
            result_text = json.dumps(
                {"status": "error", "summary": f"Unknown tool: {name}"},
                ensure_ascii=False,
            )
        else:
            try:
                result_text = tool.invoke(args)
            except Exception as exc:
                status = "error"
                result_text = json.dumps(
                    {"status": "error", "summary": str(exc)},
                    ensure_ascii=False,
                )

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            payload = json.loads(result_text)
        except Exception:
            payload = {"summary": result_text}
        if not isinstance(payload, dict):
            payload = {"summary": result_text}

        return result_text, payload, status, latency_ms
