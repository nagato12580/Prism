import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
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
    title_event,
    token_event,
    tool_call_event,
    tool_result_event,
)
from .prompts import AGENT_SYSTEM_PROMPT
from .active_recall import recall_memory_context
from ..graph.insights import graph_insights_context
from ..config import settings
from ..llm.client import chat
from ..observability import logger, quoted


_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent-tool")
OPEN_KB_DOCUMENT_PER_FILE_LIMIT = 5
FORCED_PARTIAL_DOCUMENT_ANSWER = (
    "我已经连续读取了这篇文档的前 5 个窗口，但目前还没读取完整篇文档。"
    "我会先基于已经读取到的内容回答；是否继续读取后续部分，请回复“继续”。"
)
FORCED_NO_EVIDENCE_ANSWER = "当前知识库没有可用的有效证据来回答这个问题。"


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


def _message_role_summary(messages: list[Any]) -> str:
    summary: list[str] = []
    for index, message in enumerate(messages):
        role = getattr(message, "type", None) or message.__class__.__name__
        tool_call_id = getattr(message, "tool_call_id", None)
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_call_id:
            summary.append(f"{index}:{role}(tool_call_id={tool_call_id})")
        elif tool_calls:
            call_ids = ",".join(str(_call_value(call, "id", "")) for call in tool_calls)
            summary.append(f"{index}:{role}(tool_calls=[{call_ids}])")
        else:
            summary.append(f"{index}:{role}")
    return " | ".join(summary)


def _message_roles(messages: list[Any]) -> list[str]:
    return [str(getattr(message, "type", None) or message.__class__.__name__) for message in messages]


def _content_preview(content: str, limit: int = 500) -> str:
    return content[:limit]


def _looks_like_textual_tool_call(content: str) -> bool:
    normalized = content.strip()
    if not normalized:
        return False
    return (
        "tool_calls" in normalized
        and "invoke name=" in normalized
        and (
            "DSML" in normalized
            or normalized.startswith("<tool_calls")
            or normalized.startswith("<｜｜")
        )
    )


def _tool_call_summaries(tool_calls: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": str(_call_value(call, "name", "")),
            "id": str(_call_value(call, "id", "")),
        }
        for call in tool_calls
    ]


def _candidate_text_from_source(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    for key in ("excerpt", "snippet", "text", "content", "summary", "evidence_span"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _payload_has_meaningful_evidence(payload: dict[str, Any]) -> bool:
    evidence_items = payload.get("evidence_items")
    if isinstance(evidence_items, list) and evidence_items:
        return True

    for key in ("sources", "evidence", "memories", "materials"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if _candidate_text_from_source(value):
                return True
            if key == "materials" and isinstance(value, dict):
                source = value.get("source")
                if _candidate_text_from_source(source):
                    return True
                for raw in value.get("raw_evidence") or []:
                    if _candidate_text_from_source(raw):
                        return True
    return False


def _graph_explanations_from_evidence_items(evidence_items: Any) -> list[str]:
    if not isinstance(evidence_items, list):
        return []
    explanations: list[str] = []
    seen: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        explain = metadata.get("graph_explain")
        if not isinstance(explain, dict):
            continue
        why = str(explain.get("why") or "").strip().rstrip(".。")
        evidence_type = str(explain.get("evidence_type") or "").upper()
        if not why or evidence_type not in {"EXTRACTED", "INFERRED"}:
            continue
        prefix = "Graph inference" if evidence_type == "INFERRED" else "Direct source evidence"
        line = f"{prefix}: {why}."
        path_text = _graph_path_text(metadata.get("graph_path"))
        if path_text:
            line += f" Path: {path_text}."
        if line not in seen:
            seen.add(line)
            explanations.append(line)
    return explanations


def _graph_path_text(graph_path: Any) -> str:
    if not isinstance(graph_path, list):
        return ""
    for route in graph_path:
        if not isinstance(route, dict):
            continue
        steps = route.get("steps")
        if not isinstance(steps, list):
            continue
        labels: list[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            label = step.get("label") or step.get("node_id") or step.get("edge_type")
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
        if labels:
            return " -> ".join(labels)
    return ""


def _enrich_payload_for_model(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    graph_explanations = payload.get("graph_explanations")
    if not isinstance(graph_explanations, list) or not graph_explanations:
        derived = _graph_explanations_from_evidence_items(payload.get("evidence_items"))
        if derived:
            enriched["graph_explanations"] = derived
    return enriched


def _record_trace_step(trace_recorder: Any | None, **kwargs: Any) -> None:
    if trace_recorder is None:
        return
    try:
        trace_recorder.record_step(**kwargs)
    except Exception as exc:
        logger.warning(
            "[agent] trace_record_step_failed step_type=%s error=%s",
            kwargs.get("step_type"),
            quoted(str(exc), limit=300),
        )


def _finish_trace(trace_recorder: Any | None, status: str) -> None:
    if trace_recorder is None:
        return
    try:
        trace_recorder.finish(status)
    except Exception as exc:
        logger.warning(
            "[agent] trace_finish_failed status=%s error=%s",
            status,
            quoted(str(exc), limit=300),
        )


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


def _generate_title(query: str, answer: str) -> str:
    """Generate a short conversation title from the first Q&A pair."""
    prompt = (
        "用简体中文生成一个简短的会话标题（10个字以内），概括以下问答内容：\n"
        f"用户问：{query}\n"
        f"助手答：{answer[:500]}\n"
        "标题："
    )
    result = chat([{"role": "user", "content": prompt}])
    result = result.strip().strip('"''""').strip()
    return result[:30] if result else ""


class LangChainAgentRunner:
    def __init__(
        self,
        model: Any,
        tools: list[Any],
        system_prompt: str = AGENT_SYSTEM_PROMPT,
        max_iterations: int = 5,
        clarify_depth: int = 0,
        tool_timeout_seconds: float | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.clarify_depth = clarify_depth
        self.tool_timeout_seconds = (
            settings.AGENT_TOOL_TIMEOUT_SECONDS
            if tool_timeout_seconds is None
            else tool_timeout_seconds
        )
        self._timed_out_tools: set[str] = set()
        self._pending_clarify: tuple[str, list[dict[str, str]]] | None = None
        self.tool_map = {tool.name: tool for tool in tools}
        self._has_grounding_evidence = False
        self._force_answer_with_available_evidence = False
        self._forced_answer_text: str | None = None
        self._ungrounded_insufficient_results = 0
        self._open_kb_document_counts: dict[str, int] = {}

    def stream(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        trace_recorder: Any | None = None,
    ):
        history = history or []
        self._has_grounding_evidence = False
        self._force_answer_with_available_evidence = False
        self._forced_answer_text = None
        self._ungrounded_insufficient_results = 0
        self._open_kb_document_counts = {}
        is_casual_chat = _is_casual_chat_query(query)
        is_first_exchange = not history or not any(
            msg.get("role") == "user" for msg in history
        )
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

            for iteration in range(1, self.max_iterations + 1):
                logger.info(
                    "[agent] model_invoke iteration=%s message_count=%s",
                    iteration,
                    len(messages),
                )
                logger.info(
                    "[agent] message_roles iteration=%s %s",
                    iteration,
                    _message_role_summary(messages),
                )
                _record_trace_step(
                    trace_recorder,
                    step_type="model_invoke",
                    input_json={
                        "iteration": iteration,
                        "message_count": len(messages),
                        "message_roles": _message_roles(messages),
                    },
                )
                active_model = self.model if self._force_answer_with_available_evidence else model
                response = active_model.invoke(messages)
                tool_calls = getattr(response, "tool_calls", None) or []
                text = _message_content(response)
                _record_trace_step(
                    trace_recorder,
                    step_type="model_response",
                    input_json={"iteration": iteration},
                    output_json={
                        "iteration": iteration,
                        "tool_calls": _tool_call_summaries(tool_calls),
                        "content_preview": _content_preview(text),
                    },
                )
                logger.info(
                    "[agent] model_response iteration=%s response_type=%s tool_calls=%s",
                    iteration,
                    response.__class__.__name__,
                    ",".join(
                        f"{_call_value(call, 'name', '')}:{_call_value(call, 'id', '')}"
                        for call in tool_calls
                    )
                    or "none",
                )
                if self._force_answer_with_available_evidence:
                    tool_calls = []
                if not tool_calls:
                    if (
                        self._force_answer_with_available_evidence
                        and _looks_like_textual_tool_call(text)
                    ):
                        logger.warning(
                            "[agent] suppressed_textual_tool_call_after_force_answer preview=%s",
                            quoted(text, limit=300),
                        )
                        text = ""
                    if self._force_answer_with_available_evidence and not text:
                        text = self._forced_answer_text or FORCED_NO_EVIDENCE_ANSWER
                    if text:
                        logger.info("[agent] output preview=%s", quoted(text))
                        yield agent_status_event("generating answer")
                        yield token_event(text)

                    pending = self._pending_clarify
                    if pending is not None:
                        self._pending_clarify = None
                        question, options = pending
                        yield clarify_event(question, options)

                    # Auto-generate title on first exchange
                    if is_first_exchange and text:
                        try:
                            title = _generate_title(query, text)
                            if title:
                                logger.info("[agent] title_generated title=%s", quoted(title))
                                yield title_event(title)
                        except Exception as exc:
                            logger.warning("[agent] title_generation_failed: %s", quoted(str(exc), limit=200))

                    final_output: dict[str, Any] = {"content": text}
                    if pending is not None:
                        final_output["clarify"] = {
                            "question": question,
                            "options": options,
                        }
                    _record_trace_step(
                        trace_recorder,
                        step_type="final_answer",
                        output_json=final_output,
                    )
                    _finish_trace(trace_recorder, "success")
                    logger.info("[agent] done")
                    yield done_event()
                    return

                messages.append(response)
                for tool_call in tool_calls:
                    name = str(_call_value(tool_call, "name", ""))
                    tool_call_id = str(_call_value(tool_call, "id", name))
                    args = _call_value(tool_call, "args", {}) or {}
                    if not isinstance(args, dict):
                        args = {}
                    query_arg = str(args.get("query") or args.get("question") or "")
                    logger.info(
                        "[agent] tool_call tool=%s tool_call_id=%s query=%s",
                        name,
                        tool_call_id,
                        quoted(query_arg),
                    )
                    _record_trace_step(
                        trace_recorder,
                        step_type="tool_call",
                        input_json={
                            "tool": name,
                            "call_id": tool_call_id,
                            "args": args,
                            "query": query_arg,
                        },
                        tool_name=name,
                        tool_call_id=tool_call_id,
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
                    stats = payload.get("stats")
                    trace_steps = payload.get("trace_steps")
                    if not trace_steps and isinstance(stats, dict):
                        trace_steps = stats.get("deep_trace_steps") or stats.get("trace_steps")
                    evidence_items = payload.get("evidence_items")
                    if not isinstance(evidence_items, list):
                        evidence_items = None
                    has_meaningful_evidence = _payload_has_meaningful_evidence(payload)

                    _record_trace_step(
                        trace_recorder,
                        step_type="tool_result",
                        input_json={
                            "tool": name,
                            "call_id": tool_call_id,
                            "args": args,
                            "query": query_arg,
                        },
                        output_json={
                            "status": status,
                            "summary": summary,
                            "stats": stats,
                            "trace_steps": trace_steps,
                            "evidence_items": evidence_items,
                            "payload": payload,
                        },
                        status=status,
                        tool_name=name,
                        tool_call_id=tool_call_id,
                        latency_ms=latency_ms,
                        evidence_items=evidence_items,
                    )
                    yield tool_result_event(
                        tool=name,
                        status=status,
                        summary=summary,
                        query=query_arg,
                        stats=stats,
                        latency_ms=latency_ms,
                        trace_steps=trace_steps,
                        evidence_items=evidence_items,
                    )

                    sources = payload.get("sources") or []
                    evidence_items = payload.get("evidence_items")
                    evidence = payload.get("evidence") or []
                    payload_status = str(payload.get("status") or "").lower()
                    if (
                        status == "success"
                        and (
                            has_meaningful_evidence
                            or (
                                payload_status == "sufficient"
                                and bool(sources or evidence_items or evidence)
                            )
                        )
                    ):
                        self._has_grounding_evidence = True
                    if sources:
                        yield sources_event(sources)

                    # P0-1: Add ToolMessage FIRST, then check clarify.
                    # Do NOT terminate — let the model see the tool result
                    # and generate text before we emit structured clarify.
                    messages.append(
                        ToolMessage(
                            content=result_text,
                            tool_call_id=tool_call_id,
                        )
                    )
                    logger.info(
                        "[agent] appended_tool_message tool=%s tool_call_id=%s message_roles=%s",
                        name,
                        tool_call_id,
                        _message_role_summary(messages),
                    )

                    if (
                        status == "success"
                        and payload_status == "insufficient"
                        and not has_meaningful_evidence
                    ):
                        self._ungrounded_insufficient_results += 1
                    else:
                        self._ungrounded_insufficient_results = 0

                    if (
                        status == "error"
                        and payload.get("summary") == f"Unknown tool: {name}"
                        and self._has_grounding_evidence
                    ):
                        self._force_answer_with_available_evidence = True
                        messages.append(
                            SystemMessage(
                                content=(
                                    f"The requested tool `{name}` is unavailable in this chat mode. "
                                    "Do not call more tools. Answer now using only the evidence already "
                                    "returned in tool messages. If evidence is incomplete, say so clearly."
                                )
                            )
                        )
                    elif (
                        name == "open_kb_document"
                        and self._record_open_kb_document_call(args) >= OPEN_KB_DOCUMENT_PER_FILE_LIMIT
                    ):
                        self._force_answer_with_available_evidence = True
                        self._forced_answer_text = FORCED_PARTIAL_DOCUMENT_ANSWER
                        messages.append(
                            SystemMessage(
                                content=(
                                    "You have already opened this knowledge-base document 5 times in this "
                                    "answer. Do not call more tools. Answer now using the document content "
                                    "already returned in tool messages. Clearly tell the user the full "
                                    "document has not been completely read and ask whether to continue."
                                )
                            )
                        )
                    elif self._ungrounded_insufficient_results >= 2:
                        self._force_answer_with_available_evidence = True
                        messages.append(
                            SystemMessage(
                                content=(
                                    "The last retrieval tools returned no usable grounded evidence. "
                                    "Do not call more tools. Answer now by clearly stating that the "
                                    "current knowledge base does not contain usable supporting evidence "
                                    "for this question."
                                )
                            )
                        )

                    clarify = _payload_clarify(payload)
                    if clarify is not None:
                        if self.clarify_depth >= 1:
                            # P0-3: Already clarified once — suppress further
                            # clarifies and force answer from available evidence.
                            logger.info(
                                "[agent] clarify_suppressed depth=%s question=%s",
                                self.clarify_depth,
                                quoted(clarify[0]),
                            )
                        else:
                            # P0-2: Track pending clarify for emission AFTER
                            # model generates text in the next loop iteration.
                            logger.info(
                                "[agent] clarify_pending question=%s options=%s",
                                quoted(clarify[0]),
                                len(clarify[1]),
                            )
                            self._pending_clarify = clarify

            logger.warning("[agent] max_iterations_exceeded limit=%s", self.max_iterations)
            _record_trace_step(
                trace_recorder,
                step_type="error",
                output_json={
                    "message": "Agent reached the maximum tool iteration limit.",
                    "iteration_limit": self.max_iterations,
                    "message_count": len(messages),
                    "message_roles": _message_roles(messages),
                },
                status="error",
            )
            _finish_trace(trace_recorder, "error")
            yield error_event("Agent reached the maximum tool iteration limit.")
            logger.info("[agent] done")
            yield done_event()
        except Exception as exc:
            logger.exception(
                "[agent] error message=%s",
                quoted(str(exc), limit=300),
            )
            _record_trace_step(
                trace_recorder,
                step_type="error",
                output_json={"message": str(exc)},
                status="error",
            )
            _finish_trace(trace_recorder, "error")
            yield error_event(str(exc))
            logger.info("[agent] done")
            yield done_event()

    def _record_open_kb_document_call(self, args: dict[str, Any]) -> int:
        file_uid = str(args.get("file_uid") or "").strip()
        key = file_uid or "__unknown__"
        count = self._open_kb_document_counts.get(key, 0) + 1
        self._open_kb_document_counts[key] = count
        return count

    def _build_messages(self, query: str, history: list[dict[str, Any]]) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=self.system_prompt)]
        try:
            recall_block = recall_memory_context(query)
            if recall_block:
                messages.append(SystemMessage(content=recall_block))
                logger.info("[agent] active_recall injected chars=%s", len(recall_block))
        except Exception as exc:
            logger.warning("[agent] active_recall failed (ignored): %s", quoted(str(exc), limit=200))
        try:
            insights_block = graph_insights_context(query)
            if insights_block:
                messages.append(SystemMessage(content=insights_block))
                logger.info("[agent] graph_insights injected chars=%s", len(insights_block))
        except Exception as exc:
            logger.warning("[agent] graph_insights failed (ignored): %s", quoted(str(exc), limit=200))
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

        if name in self._timed_out_tools:
            status = "error"
            result_text = json.dumps(
                {
                    "status": "error",
                    "summary": f"Tool {name} is disabled after a previous timeout in this answer.",
                },
                ensure_ascii=False,
            )
        elif tool is None:
            status = "error"
            result_text = json.dumps(
                {"status": "error", "summary": f"Unknown tool: {name}"},
                ensure_ascii=False,
            )
        else:
            try:
                future = _TOOL_EXECUTOR.submit(tool.invoke, args)
                result_text = future.result(timeout=self.tool_timeout_seconds)
            except TimeoutError:
                future.cancel()
                status = "error"
                self._timed_out_tools.add(name)
                timeout_seconds = int(self.tool_timeout_seconds)
                result_text = json.dumps(
                    {
                        "status": "error",
                        "summary": f"Tool {name} timed out after {timeout_seconds}s.",
                    },
                    ensure_ascii=False,
                )
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
        payload = _enrich_payload_for_model(payload)
        result_text = json.dumps(payload, ensure_ascii=False)

        return result_text, payload, status, latency_ms
