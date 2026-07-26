import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, replace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

try:
    from langchain_openai import ChatOpenAI
except ModuleNotFoundError:
    ChatOpenAI = None

from .events import (
    agent_status_event,
    clarify_event,
    continuation_event,
    done_event,
    error_event,
    sources_event,
    title_event,
    token_event,
    tool_call_event,
    tool_result_event,
)
from .continuation import (
    AgentContinuation,
    continuation_from_history,
    is_bare_continuation,
    resolve_effective_objective,
)
from .prompts import AGENT_SYSTEM_PROMPT
from .active_recall import recall_memory_context
from ..graph.insights import graph_insights_context
from ..config import settings
from ..llm.client import chat
from ..observability import logger, quoted


@dataclass(frozen=True)
class SynthesisEvidence:
    text: str
    kind: str
    tool_call_id: str
    file_uid: str | None
    result_index: int


_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent-tool")
OPEN_KB_DOCUMENT_PER_FILE_LIMIT = 5
DOCUMENT_WINDOW_SUCCESS_STATUSES = frozenset({"ok", "success", "degraded"})
FORCED_PARTIAL_DOCUMENT_ANSWER = (
    "我已经连续读取了这篇文档的 5 个窗口，但目前还没读取完整篇文档。"
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


def _resolved_tool_call_id(tool_call: Any) -> str:
    return str(
        _call_value(tool_call, "id", None)
        or _call_value(tool_call, "name", "")
        or "tool"
    )


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


def _normalized_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    nested_payload = payload.get("payload")
    if isinstance(nested_payload, dict):
        nested_summary = nested_payload.get("summary")
        if isinstance(nested_summary, dict):
            return nested_summary
        if isinstance(nested_payload.get("data"), dict):
            return nested_payload

    summary = payload.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("data"), dict):
        return summary
    return payload


def _decoded_tool_payloads(messages: list[Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            payload = json.loads(str(message.content))
        except Exception:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _decoded_tool_results(messages: list[Any]) -> list[dict[str, Any]]:
    return [
        _normalized_tool_result(payload)
        for payload in _decoded_tool_payloads(messages)
    ]


def _document_windows_from_messages(messages: list[Any]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for payload in _decoded_tool_payloads(messages):
        window = _document_window_from_envelope(payload)
        if window is not None:
            windows.append(window)
    return windows


def _is_successful_document_status(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.strip().lower() in DOCUMENT_WINDOW_SUCCESS_STATUSES
    )


def _validated_document_window(result: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_successful_document_status(result.get("status")):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    kb_uid = data.get("kb_uid")
    file_uid = data.get("file_uid")
    offset = data.get("offset")
    next_offset = data.get("next_offset")
    has_more_after = data.get("has_more_after")
    if (
        not isinstance(content, str)
        or not content.strip()
        or not isinstance(kb_uid, str)
        or not kb_uid.strip()
        or not isinstance(file_uid, str)
        or not file_uid.strip()
        or not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
        or not isinstance(next_offset, int)
        or isinstance(next_offset, bool)
        or next_offset < 0
        or next_offset != offset + len(content)
        or not isinstance(has_more_after, bool)
    ):
        return None
    return {
        "kb_uid": kb_uid.strip(),
        "file_uid": file_uid.strip(),
        "offset": offset,
        "next_offset": next_offset,
        "content": content,
        "has_more_after": has_more_after,
    }


def _document_window_from_envelope(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = _normalized_tool_result(payload)
    if result is not payload and not _is_successful_document_status(payload.get("status")):
        return None
    return _validated_document_window(result)


def _document_window_from_payload(
    payload: dict[str, Any],
    status: str,
) -> dict[str, Any] | None:
    if status != "success":
        return None
    return _document_window_from_envelope(payload)


def _bounded_evidence_text(candidate: Any) -> str:
    text = re.sub(r"\s+", " ", _candidate_text_from_source(candidate)).strip()
    if len(text) > 700:
        return text[:697].rstrip() + "..."
    return text


def _unique_bounded_excerpt(
    text: str,
    quota: int,
    selected_texts: set[str],
) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized or quota <= 0:
        return None

    excerpts = [normalized[:quota], normalized[-quota:]]
    if quota >= 3 and len(normalized) > quota:
        content_quota = quota - 1
        head_length = (content_quota + 1) // 2
        tail_length = content_quota - head_length
        excerpts.append(
            normalized[:head_length]
            + "…"
            + (normalized[-tail_length:] if tail_length else "")
        )
    if len(normalized) > quota:
        excerpts.extend(
            normalized[start : start + quota]
            for start in range(1, len(normalized) - quota + 1)
        )

    tried: set[str] = set()
    for excerpt in excerpts:
        bounded = re.sub(r"\s+", " ", excerpt).strip()
        if not bounded or len(bounded) > quota or bounded in tried:
            continue
        tried.add(bounded)
        if bounded not in selected_texts:
            return bounded
    return None


def _synthesis_evidence_candidates(messages: list[Any]) -> list[SynthesisEvidence]:
    candidates: list[SynthesisEvidence] = []
    list_kinds = {
        "matches": "match",
        "evidence": "semantic",
        "sources": "semantic",
        "evidence_items": "semantic",
        "memories": "memory",
        "materials": "semantic",
    }
    result_index = -1
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        result_index += 1
        try:
            payload = json.loads(str(message.content))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        result = _normalized_tool_result(payload)
        data = result.get("data")
        if not isinstance(data, dict):
            data = {}
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")

        content = data.get("content")
        if isinstance(content, str) and content.strip():
            text = _bounded_evidence_text({"content": content})
            if text:
                file_uid = data.get("file_uid") or result.get("file_uid")
                candidates.append(
                    SynthesisEvidence(
                        text=text,
                        kind="document",
                        tool_call_id=tool_call_id,
                        file_uid=str(file_uid) if file_uid else None,
                        result_index=result_index,
                    )
                )

        for container in (result, data):
            for key, kind in list_kinds.items():
                values = container.get(key)
                if not isinstance(values, list):
                    continue
                candidate_kind = (
                    "coverage"
                    if container is data and key == "evidence" and isinstance(data.get("coverage"), dict)
                    else kind
                )
                for value in values:
                    text = _bounded_evidence_text(value)
                    if not text:
                        continue
                    file_uid = (
                        value.get("file_uid") if isinstance(value, dict) else None
                    ) or container.get("file_uid") or data.get("file_uid") or result.get("file_uid")
                    candidates.append(
                        SynthesisEvidence(
                            text=text,
                            kind=candidate_kind,
                            tool_call_id=tool_call_id,
                            file_uid=str(file_uid) if file_uid else None,
                            result_index=result_index,
                        )
                    )
    return candidates


def _select_synthesis_evidence(
    messages: list[Any],
    required_tool_call_ids: list[str] | None = None,
    char_budget: int = 8400,
) -> list[SynthesisEvidence]:
    candidates = _synthesis_evidence_candidates(messages)
    selected: list[SynthesisEvidence] = []
    seen_texts: set[str] = set()
    selected_ids: set[int] = set()
    used_chars = 0
    allow_oversized_first = True

    def add(candidate: SynthesisEvidence) -> bool:
        nonlocal used_chars
        candidate_id = id(candidate)
        normalized = re.sub(r"\s+", " ", candidate.text).strip()
        if candidate_id in selected_ids or not normalized or normalized in seen_texts:
            return False
        if (
            used_chars + len(normalized) > char_budget
            and (selected or not allow_oversized_first)
        ):
            return False
        selected.append(candidate)
        selected_ids.add(candidate_id)
        seen_texts.add(normalized)
        used_chars += len(normalized)
        return True

    required_ids = {str(call_id) for call_id in (required_tool_call_ids or [])}
    required_groups: list[list[SynthesisEvidence]] = []
    required_group_by_id: dict[str, list[SynthesisEvidence]] = {}
    for candidate in candidates:
        if candidate.tool_call_id not in required_ids:
            continue
        group = required_group_by_id.get(candidate.tool_call_id)
        if group is None:
            group = []
            required_group_by_id[candidate.tool_call_id] = group
            required_groups.append(group)
        group.append(candidate)

    representatives: list[SynthesisEvidence] = []
    representative_sources: list[tuple[list[SynthesisEvidence], int]] = []
    representative_texts: set[str] = set()
    for group in required_groups:
        for candidate_index, candidate in enumerate(group):
            normalized = re.sub(r"\s+", " ", candidate.text).strip()
            if normalized and normalized not in representative_texts:
                representatives.append(candidate)
                representative_sources.append((group, candidate_index))
                representative_texts.add(normalized)
                break

    representative_chars = sum(len(candidate.text) for candidate in representatives)
    allow_oversized_first = len(representatives) <= 1
    if len(representatives) <= 1 or representative_chars <= char_budget:
        for candidate in representatives:
            add(candidate)
    else:
        representative_slots = min(len(representatives), max(char_budget, 0))
        remaining_budget = max(char_budget, 0)
        for index, candidate in enumerate(representatives[:representative_slots]):
            remaining_count = representative_slots - index
            quota = remaining_budget // remaining_count
            group, candidate_index = representative_sources[index]
            choices = [candidate]
            choices.extend(
                later_candidate
                for later_candidate in group[candidate_index + 1 :]
                if re.sub(r"\s+", " ", later_candidate.text).strip()
                not in representative_texts
            )
            for choice in choices:
                excerpt = _unique_bounded_excerpt(choice.text, quota, seen_texts)
                if excerpt is None:
                    continue
                truncated = replace(choice, text=excerpt)
                if add(truncated):
                    selected_ids.add(id(choice))
                    remaining_budget -= len(excerpt)
                    break

    def prioritize_required_group(
        group: list[SynthesisEvidence],
    ) -> list[SynthesisEvidence]:
        coverage_candidates = [candidate for candidate in group if candidate.kind == "coverage"]
        distinct_coverage: list[SynthesisEvidence] = []
        duplicate_coverage: list[SynthesisEvidence] = []
        covered_files: set[str] = set()
        for candidate in coverage_candidates:
            coverage_key = candidate.file_uid or f"result:{candidate.result_index}"
            if coverage_key in covered_files:
                duplicate_coverage.append(candidate)
            else:
                covered_files.add(coverage_key)
                distinct_coverage.append(candidate)
        prioritized_coverage = iter(distinct_coverage + duplicate_coverage)
        return [
            next(prioritized_coverage) if candidate.kind == "coverage" else candidate
            for candidate in group
        ]

    required_group_queues = [prioritize_required_group(group) for group in required_groups]
    required_group_positions = [0] * len(required_group_queues)
    while True:
        advanced = False
        for index, group in enumerate(required_group_queues):
            position = required_group_positions[index]
            if position >= len(group):
                continue
            add(group[position])
            required_group_positions[index] += 1
            advanced = True
        if not advanced:
            break

    def newest_first(kind: str) -> list[SynthesisEvidence]:
        return sorted(
            (candidate for candidate in candidates if candidate.kind == kind),
            key=lambda candidate: -candidate.result_index,
        )

    for candidate in newest_first("match"):
        add(candidate)
    for candidate in newest_first("document"):
        add(candidate)

    coverage = newest_first("coverage")
    covered_files: set[str] = set()
    duplicate_coverage: list[SynthesisEvidence] = []
    for candidate in coverage:
        coverage_key = candidate.file_uid or f"result:{candidate.result_index}"
        if coverage_key in covered_files:
            duplicate_coverage.append(candidate)
            continue
        covered_files.add(coverage_key)
        add(candidate)
    for candidate in duplicate_coverage:
        add(candidate)

    for candidate in sorted(candidates, key=lambda item: -item.result_index):
        add(candidate)
    return selected


def _tool_evidence_texts(messages: list[Any], limit: int = 12) -> list[str]:
    return [item.text for item in _select_synthesis_evidence(messages)[:limit]]


def _partial_document_answer_from_messages(messages: list[Any]) -> str:
    windows = _document_windows_from_messages(messages)
    if not windows:
        return FORCED_PARTIAL_DOCUMENT_ANSWER

    excerpts: list[str] = []
    for index, window in enumerate(windows[-OPEN_KB_DOCUMENT_PER_FILE_LIMIT:], start=1):
        text = re.sub(r"\s+", " ", str(window["content"])).strip()
        if len(text) > 700:
            text = text[:700].rstrip() + "..."
        offset = window.get("offset")
        location = f"offset {offset}" if offset is not None else f"窗口 {index}"
        excerpts.append(f"{index}. {location}: {text}")

    return (
        "我已经连续读取了这篇文档的 5 个窗口，但目前还没读取完整篇文档。\n\n"
        "基于已经读取到的内容，当前可提取的信息如下：\n\n"
        + "\n\n".join(excerpts)
        + "\n\n是否继续读取后续部分？如果需要，请回复“继续”。"
    )


def _normalize_document_cap_progress(text: str) -> str:
    return re.sub(
        r"(?:已经|已)读取到\s*第\s*5\s*页",
        "已读取了 5 个窗口",
        text,
    )


def _document_cap_synthesis_messages(
    query: str,
    messages: list[Any],
    required_tool_call_ids: list[str] | None = None,
) -> list[Any]:
    evidence_texts = [
        item.text
        for item in _select_synthesis_evidence(
            messages,
            required_tool_call_ids=required_tool_call_ids,
        )
    ]
    evidence = "\n\n".join(
        f"{index}. {text}" for index, text in enumerate(evidence_texts, start=1)
    ) or "没有可用的文档片段。"
    return [
        SystemMessage(
            content=(
                "你负责基于给定的文档片段直接回答用户问题。"
                "只输出自然语言答案，不得调用工具，不得输出 XML、DSML 或任何工具调用协议。"
                "请明确说明文档尚未完整读取，并在回答末尾询问用户是否继续读取。"
                "本轮的五次读取是 5 个窗口，不是五页；除非片段明确提供页码元数据，"
                "不得推断或声称已经读取到第5页。"
            )
        ),
        HumanMessage(
            content=(
                f"用户问题：{query}\n\n"
                "以下是本轮已经读取的文档片段：\n\n"
                f"{evidence}"
            )
        ),
    ]


def _iteration_limit_synthesis_messages(
    query: str,
    messages: list[Any],
    required_tool_call_ids: list[str] | None = None,
) -> list[Any]:
    evidence_texts = [
        item.text
        for item in _select_synthesis_evidence(
            messages,
            required_tool_call_ids=required_tool_call_ids,
        )
    ]
    evidence = "\n\n".join(
        f"{index}. {text}" for index, text in enumerate(evidence_texts, start=1)
    ) or "没有可用的工具证据。"
    return [
        SystemMessage(
            content=(
                "工具迭代预算已经耗尽。请基于所有已执行工具返回的证据直接回答用户问题。"
                "只输出自然语言答案，不得再调用工具，不得输出 XML、DSML 或任何工具调用协议。"
                "仅报告证据实际支持的内容与限制，不得臆测未执行的操作或没有证据支持的结论。"
            )
        ),
        HumanMessage(
            content=(
                f"用户问题：{query}\n\n"
                "以下是本轮工具已经返回的证据：\n\n"
                f"{evidence}"
            )
        ),
    ]


def _grounded_fallback_answer_from_messages(
    messages: list[Any],
    required_tool_call_ids: list[str] | None = None,
) -> str:
    snippets = [
        item.text
        for item in _select_synthesis_evidence(
            messages,
            required_tool_call_ids=required_tool_call_ids,
        )[:5]
    ]
    if not snippets:
        return _partial_document_answer_from_messages(messages)

    excerpt_lines = [f"{index}. {text}" for index, text in enumerate(snippets, start=1)]
    return (
        "当前工具调用已达到本轮上限，我先基于已经检索到的证据给出阶段性回答。\n\n"
        "已获得的关键证据如下：\n\n"
        + "\n\n".join(excerpt_lines)
        + "\n\n如果需要更完整的上下文，请继续追问，我会在下一轮继续检索。"
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
    result = _normalized_tool_result(payload)
    data = result.get("data")
    containers = [result]
    if isinstance(data, dict):
        containers.append(data)

    if any(isinstance(container.get("content"), str) and container["content"].strip() for container in containers):
        return True

    evidence_items = result.get("evidence_items")
    if isinstance(evidence_items, list) and evidence_items:
        return True

    for container in containers:
        for key in ("sources", "evidence", "memories", "materials", "matches"):
            values = container.get(key)
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
        self._active_continuation: AgentContinuation | None = None
        self._resume_consumed = False
        self._document_windows_by_file: dict[str, list[dict[str, Any]]] = {}
        self._effective_query = ""
        self._effective_objective_source = "current"

    def stream(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        trace_recorder: Any | None = None,
    ):
        history = history or []
        self._timed_out_tools = set()
        self._pending_clarify = None
        self._has_grounding_evidence = False
        self._force_answer_with_available_evidence = False
        self._forced_answer_text = None
        self._ungrounded_insufficient_results = 0
        self._open_kb_document_counts = {}
        self._active_continuation = None
        self._resume_consumed = False
        self._document_windows_by_file = {}
        validated_continuation = continuation_from_history(history)
        if is_bare_continuation(query):
            self._active_continuation = validated_continuation
        self._effective_query = resolve_effective_objective(
            query,
            history,
            self._active_continuation,
        )
        if not is_bare_continuation(query):
            self._effective_objective_source = "current"
        elif self._active_continuation is not None:
            self._effective_objective_source = "continuation_state"
        elif self._effective_query == query:
            self._effective_objective_source = "current"
        else:
            self._effective_objective_source = "history_fallback"
        is_casual_chat = _is_casual_chat_query(query)
        is_first_exchange = not history or not any(
            msg.get("role") == "user" for msg in history
        )
        logger.info(
            "[agent] start query=%s history_messages=%s max_iterations=%s effective_objective_source=%s",
            quoted(query),
            len(history),
            self.max_iterations,
            self._effective_objective_source,
        )
        yield agent_status_event("chat" if is_casual_chat else "analyzing question")

        try:
            messages = self._build_messages(
                query,
                history,
                effective_query=self._effective_query,
                active_continuation=self._active_continuation,
            )
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
                        "effective_objective_source": self._effective_objective_source,
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
                    tool_call_id = _resolved_tool_call_id(tool_call)
                    args = _call_value(tool_call, "args", {}) or {}
                    if not isinstance(args, dict):
                        args = {}
                    args = self._apply_active_resume(name, args)
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
                    if name == "open_kb_document":
                        self._track_document_window(payload, status)
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
                        synthesis_messages = _document_cap_synthesis_messages(
                            self._effective_query,
                            messages,
                            required_tool_call_ids=[tool_call_id],
                        )
                        _record_trace_step(
                            trace_recorder,
                            step_type="model_invoke",
                            input_json={
                                "iteration": "forced_final_after_open_limit",
                                "message_count": len(synthesis_messages),
                                "message_roles": _message_roles(synthesis_messages),
                                "effective_objective_source": self._effective_objective_source,
                            },
                        )
                        forced_response = self.model.invoke(synthesis_messages)
                        forced_tool_calls = getattr(forced_response, "tool_calls", None) or []
                        forced_text = _message_content(forced_response)
                        _record_trace_step(
                            trace_recorder,
                            step_type="model_response",
                            input_json={"iteration": "forced_final_after_open_limit"},
                            output_json={
                                "iteration": "forced_final_after_open_limit",
                                "tool_calls": _tool_call_summaries(forced_tool_calls),
                                "content_preview": _content_preview(forced_text),
                            },
                        )
                        if forced_tool_calls or _looks_like_textual_tool_call(forced_text):
                            logger.warning(
                                "[agent] forced_final_after_open_limit_ignored_tool_call tool_calls=%s preview=%s",
                                len(forced_tool_calls),
                                quoted(forced_text, limit=300),
                            )
                            forced_text = ""
                        final_text = _normalize_document_cap_progress(
                            forced_text or _partial_document_answer_from_messages(messages)
                        )
                        _record_trace_step(
                            trace_recorder,
                            step_type="final_answer",
                            output_json={"content": final_text},
                        )
                        _finish_trace(trace_recorder, "success")
                        logger.info(
                            "[agent] open_kb_document_limit_reached; returning forced final answer"
                        )
                        yield agent_status_event("generating answer")
                        yield token_event(final_text)
                        continuation = self._continuation_for_file(args)
                        if continuation is not None:
                            yield continuation_event(continuation)
                        logger.info("[agent] done")
                        yield done_event()
                        return
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

                if iteration == self.max_iterations:
                    required_tool_call_ids = [
                        _resolved_tool_call_id(call) for call in tool_calls
                    ]
                    synthesis_messages = _iteration_limit_synthesis_messages(
                        self._effective_query,
                        messages,
                        required_tool_call_ids=required_tool_call_ids,
                    )
                    _record_trace_step(
                        trace_recorder,
                        step_type="model_invoke",
                        input_json={
                            "iteration": "forced_final_after_iteration_limit",
                            "message_count": len(synthesis_messages),
                            "message_roles": _message_roles(synthesis_messages),
                            "effective_objective_source": self._effective_objective_source,
                        },
                    )
                    forced_response = self.model.invoke(synthesis_messages)
                    forced_tool_calls = getattr(forced_response, "tool_calls", None) or []
                    forced_text = _message_content(forced_response)
                    _record_trace_step(
                        trace_recorder,
                        step_type="model_response",
                        input_json={"iteration": "forced_final_after_iteration_limit"},
                        output_json={
                            "iteration": "forced_final_after_iteration_limit",
                            "tool_calls": _tool_call_summaries(forced_tool_calls),
                            "content_preview": _content_preview(forced_text),
                        },
                    )
                    if forced_tool_calls or _looks_like_textual_tool_call(forced_text):
                        forced_text = ""
                    final_text = forced_text or _grounded_fallback_answer_from_messages(
                        messages,
                        required_tool_call_ids=required_tool_call_ids,
                    )
                    _record_trace_step(
                        trace_recorder,
                        step_type="final_answer",
                        output_json={"content": final_text},
                    )
                    _finish_trace(trace_recorder, "success")
                    yield agent_status_event("generating answer")
                    yield token_event(final_text)
                    yield done_event()
                    return

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

    def _apply_active_resume(
        self,
        name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        rewritten = dict(args)
        state = self._active_continuation
        if name != "open_kb_document" or state is None or self._resume_consumed:
            return rewritten

        file_uid = str(rewritten.get("file_uid") or "").strip()
        if file_uid and file_uid != state.file_uid:
            return rewritten

        line = rewritten.get("line")
        offset = rewritten.get("offset")
        explicit_line = isinstance(line, int) and not isinstance(line, bool) and line > 1
        explicit_offset = (
            isinstance(offset, int)
            and not isinstance(offset, bool)
            and offset >= state.next_offset
        )
        if file_uid == state.file_uid and (explicit_line or explicit_offset):
            self._resume_consumed = True
            return rewritten

        starts_at_beginning = line is None or line == 1
        stale_offset = (
            offset is None
            or (
                isinstance(offset, int)
                and not isinstance(offset, bool)
                and offset < state.next_offset
            )
        )
        if starts_at_beginning and stale_offset:
            rewritten["kb_uid"] = state.kb_uid
            rewritten["file_uid"] = state.file_uid
            rewritten["offset"] = state.next_offset
            rewritten.pop("line", None)
            self._resume_consumed = True
        return rewritten

    def _track_document_window(self, payload: dict[str, Any], status: str) -> None:
        window = _document_window_from_payload(payload, status)
        if window is None:
            return
        self._document_windows_by_file.setdefault(window["file_uid"], []).append(window)

    def _continuation_for_file(
        self,
        args: dict[str, Any],
    ) -> AgentContinuation | None:
        file_uid = str(args.get("file_uid") or "").strip()
        windows = self._document_windows_by_file.get(file_uid, [])
        if not windows:
            return None
        furthest = max(windows, key=lambda window: window["next_offset"])
        if not furthest["has_more_after"]:
            return None
        return AgentContinuation(
            version=1,
            objective=self._effective_query,
            kb_uid=furthest["kb_uid"],
            file_uid=furthest["file_uid"],
            next_offset=furthest["next_offset"],
            has_more_after=True,
        )

    def _build_messages(
        self,
        query: str,
        history: list[dict[str, Any]],
        *,
        effective_query: str | None = None,
        active_continuation: AgentContinuation | None = None,
    ) -> list[Any]:
        messages: list[Any] = [SystemMessage(content=self.system_prompt)]
        context_query = effective_query or query
        try:
            recall_block = recall_memory_context(context_query)
            if recall_block:
                messages.append(SystemMessage(content=recall_block))
                logger.info("[agent] active_recall injected chars=%s", len(recall_block))
        except Exception as exc:
            logger.warning("[agent] active_recall failed (ignored): %s", quoted(str(exc), limit=200))
        try:
            insights_block = graph_insights_context(context_query)
            if insights_block:
                messages.append(SystemMessage(content=insights_block))
                logger.info("[agent] graph_insights injected chars=%s", len(insights_block))
        except Exception as exc:
            logger.warning("[agent] graph_insights failed (ignored): %s", quoted(str(exc), limit=200))
        if active_continuation is not None:
            messages.append(
                SystemMessage(
                    content=(
                        "Resume the prior document-reading objective from its saved cursor. "
                        f"Effective objective: {effective_query or query}\n"
                        f"kb_uid: {active_continuation.kb_uid}\n"
                        f"file_uid: {active_continuation.file_uid}\n"
                        f"next_offset: {active_continuation.next_offset}\n"
                        "Do not restart the document from the beginning. Continue from this cursor "
                        "unless a later explicit location is required by the visible conversation."
                    )
                )
            )
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
