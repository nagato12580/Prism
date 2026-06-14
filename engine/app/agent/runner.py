import json
import re
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
from ..observability import logger, quoted


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
    if not isinstance(content, list):
        return ""

    visible_text: list[str] = []
    for block in content:
        if isinstance(block, str):
            visible_text.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if block.get("type") == "text" and isinstance(text, str):
                visible_text.append(text)
        else:
            block_type = getattr(block, "type", None)
            text = getattr(block, "text", None)
            if block_type in (None, "text") and isinstance(text, str):
                visible_text.append(text)
    return "".join(visible_text)


def _call_value(tool_call: Any, key: str, default: Any = None) -> Any:
    if isinstance(tool_call, dict):
        return tool_call.get(key, default)
    return getattr(tool_call, key, default)


def _payload_clarify(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]] | None:
    clarify = payload if payload.get("status") == "clarify" else payload.get("clarify")
    if not isinstance(clarify, dict):
        return None

    question = clarify.get("question")
    options = clarify.get("options")
    if not isinstance(question, str) or not isinstance(options, list):
        return None

    validated_options: list[dict[str, str]] = []
    for option in options:
        if not isinstance(option, dict):
            return None
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in option.items()
        ):
            return None
        validated_options.append(dict(option))

    return question, validated_options


def _is_casual_chat_query(query: str) -> bool:
    normalized = re.sub(r"[\s\.,!?，。！？~～]+", "", query).lower()
    if not normalized:
        return False

    casual_phrases = {
        "hi",
        "hello",
        "hey",
        "\u4f60\u597d",
        "\u4f60\u597d\u554a",
        "\u4f60\u597d\u5440",
        "\u60a8\u597d",
        "\u54c8\u55bd",
        "\u55e8",
        "\u5728\u5417",
        "\u65e9\u4e0a\u597d",
        "\u4e2d\u5348\u597d",
        "\u665a\u4e0a\u597d",
        "\u8c22\u8c22",
        "\u518d\u89c1",
    }
    return normalized in casual_phrases


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
        history = history or []
        is_casual_chat = _is_casual_chat_query(query)
        logger.info(
            "[agent] start query=%s history_messages=%s max_iterations=%s",
            quoted(query),
            len(history),
            self.max_iterations,
        )
        yield agent_status_event("chat" if is_casual_chat else "analyzing question")

        try:
            messages = self._build_messages(query, history)
            model = self.model.bind_tools(self.tools) if self.tools else self.model
            knowledge_fallback_used = False

            for iteration in range(1, self.max_iterations + 1):
                logger.info(
                    "[agent] model_invoke iteration=%s message_count=%s",
                    iteration,
                    len(messages),
                )
                response = model.invoke(messages)
                tool_calls = getattr(response, "tool_calls", None) or []
                if not tool_calls:
                    should_fallback = (
                        not is_casual_chat
                        and not knowledge_fallback_used
                        and self._should_fallback_to_knowledge_search(messages)
                    )
                    fallback_events = (
                        self._fallback_knowledge_search(query, messages)
                        if should_fallback
                        else None
                    )
                    if fallback_events is not None:
                        logger.info(
                            "[agent] fallback tool=knowledge_search reason=no_tool_calls"
                        )
                        knowledge_fallback_used = True
                        for event in fallback_events:
                            yield event
                        if any(
                            json.loads(event).get("type") == "done"
                            for event in fallback_events
                        ):
                            return
                        response = model.invoke(messages)
                        tool_calls = getattr(response, "tool_calls", None) or []
                        if tool_calls:
                            messages.append(response)
                            continue

                    text = _message_content(response)
                    if text:
                        logger.info("[agent] output preview=%s", quoted(text))
                        yield token_event(text)
                    logger.info("[agent] done")
                    yield done_event()
                    return

                messages.append(response)
                for tool_call in tool_calls:
                    name = str(_call_value(tool_call, "name", ""))
                    args = _call_value(tool_call, "args", {}) or {}
                    if not isinstance(args, dict):
                        args = {}
                    query_arg = str(args.get("query") or args.get("question") or "")
                    logger.info(
                        "[agent] tool_call tool=%s query=%s",
                        name,
                        quoted(query_arg),
                    )
                    yield tool_call_event(name, query_arg)

                    result_text, payload, status, latency_ms = self._invoke_tool(
                        name, args
                    )
                    summary = str(
                        payload.get("summary")
                        or payload.get("question")
                        or result_text
                    )
                    logger.info(
                        "[agent] tool_result tool=%s status=%s latency_ms=%s summary=%s",
                        name,
                        status,
                        latency_ms,
                        quoted(summary),
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

                    clarify = _payload_clarify(payload)
                    if clarify is not None:
                        question, options = clarify
                        logger.info(
                            "[agent] clarify question=%s options=%s",
                            quoted(question),
                            len(options),
                        )
                        yield clarify_event(question, options)
                        logger.info("[agent] done")
                        yield done_event()
                        return

                    messages.append(
                        ToolMessage(
                            content=result_text,
                            tool_call_id=str(_call_value(tool_call, "id", name)),
                        )
                    )

            logger.warning("[agent] max_iterations_exceeded limit=%s", self.max_iterations)
            yield error_event("Agent reached the maximum tool iteration limit.")
            logger.info("[agent] done")
            yield done_event()
        except Exception as exc:
            logger.exception(
                "[agent] error message=%s",
                quoted(str(exc), limit=300),
            )
            yield error_event(str(exc))
            logger.info("[agent] done")
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

    def _fallback_knowledge_search(
        self,
        query: str,
        messages: list[Any],
    ) -> list[str] | None:
        tool = self.tool_map.get("knowledge_search")
        if tool is None:
            return None

        result_text, payload, status, latency_ms = self._invoke_tool(
            "knowledge_search",
            {"query": query},
        )

        summary = str(payload.get("summary") or payload.get("question") or result_text)
        events = [
            tool_call_event("knowledge_search", query),
            tool_result_event(
                tool="knowledge_search",
                status=status,
                summary=summary,
                query=query,
                stats=payload.get("stats"),
                latency_ms=latency_ms,
            ),
        ]

        sources = payload.get("sources") or []
        if sources:
            events.append(sources_event(sources))

        clarify = _payload_clarify(payload)
        if clarify is not None:
            question, options = clarify
            events.append(clarify_event(question, options))
            events.append(done_event())
            return events

        messages.append(
            ToolMessage(
                content=result_text,
                tool_call_id="knowledge_search_fallback",
            )
        )
        return events

    def _should_fallback_to_knowledge_search(self, messages: list[Any]) -> bool:
        if "knowledge_search" not in self.tool_map:
            return False
        return not any(isinstance(message, ToolMessage) for message in messages)
