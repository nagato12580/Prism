import json
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..agent.events import error_event, trace_event
from ..agent.rag.agentic import AgenticRagRunner, RagJudgeResult, RagRunConfig
from ..agent.prompts import AGENT_SYSTEM_PROMPT
from ..agent.runner import LangChainAgentRunner, create_chat_model
from ..agent.trace import AgentTraceRecorder
from ..agent.tools import ToolContext, build_enabled_tools
from ..config import settings
from ..llm.client import chat
from ..observability import logger, quoted
from ..retrieval.unified import make_unified_search


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def _strip_tool_guidance(prompt: str, disabled_tools: set[str]) -> str:
    if not disabled_tools:
        return prompt
    lines = prompt.splitlines()
    kept: list[str] = []
    for line in lines:
        if any(tool_name in line for tool_name in disabled_tools):
            continue
        kept.append(line)
    return "\n".join(kept)


def _load_chunks(chunk_ids: list[str], scope=None) -> dict[str, dict[str, str]]:
    """加载 chunk 文本和所属文档名。

    Small-to-big 检索：命中子块时返回父块完整内容。
    This is intentionally called after unified child-text reranking: parent
    expansion changes final evidence context, not the provider payload.
    Returns: {chunk_id: {"text": str, "doc_name": str}}
    """
    from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem, KnowledgeFile

    db = _Session()
    try:
        chunks_query = db.query(KnowledgeChunk).filter(KnowledgeChunk.chunk_uid.in_(chunk_ids))
        if scope is not None:
            chunks_query = chunks_query.filter(
                KnowledgeChunk.tenant_id == scope.tenant_id,
                KnowledgeChunk.kb_uid == scope.kb_uid,
                KnowledgeChunk.generation == scope.index_generation,
            )
        chunks = chunks_query.all()
        if not chunks:
            return {}

        # Small-to-big：子块替换为父块内容
        parent_ids_needed = {c.parent_id for c in chunks if c.parent_id and c.parent_id not in chunk_ids}
        parent_chunks = {}
        if parent_ids_needed:
            parents_query = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(parent_ids_needed))
            if scope is not None:
                parents_query = parents_query.filter(
                    KnowledgeChunk.tenant_id == scope.tenant_id,
                    KnowledgeChunk.kb_uid == scope.kb_uid,
                    KnowledgeChunk.generation == scope.index_generation,
                )
            parents = parents_query.all()
            parent_chunks = {p.id: p for p in parents}

        # 收集所有需要的 item_ids（含父块）
        all_chunks = list(chunks) + list(parent_chunks.values())
        item_ids = {c.item_id for c in all_chunks}
        items = {
            row[0]: row[1]
            for row in db.query(KnowledgeItem.id, KnowledgeItem.title)
            .filter(KnowledgeItem.id.in_(item_ids))
            .all()
        }
        files = {
            row[0]: row[1] or row[2] or ""
            for row in db.query(KnowledgeFile.item_id, KnowledgeFile.title, KnowledgeFile.original_filename)
            .filter(KnowledgeFile.item_id.in_(item_ids))
            .all()
        }

        result = {}
        for chunk in chunks:
            # 如果命中子块且有父块 → 返回父块内容
            if chunk.parent_id and chunk.parent_id in parent_chunks:
                parent = parent_chunks[chunk.parent_id]
                doc_name = files.get(parent.item_id) or items.get(parent.item_id, "")
                result[chunk.chunk_uid] = {"text": parent.chunk_text, "doc_name": doc_name}
            else:
                doc_name = files.get(chunk.item_id) or items.get(chunk.item_id, "")
                result[chunk.chunk_uid] = {"text": chunk.chunk_text, "doc_name": doc_name}
        return result
    finally:
        db.close()


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _graph_explanations_from_evidence(evidence: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        graph_rag = item.get("graph_rag") if isinstance(item.get("graph_rag"), dict) else {}
        explain = graph_rag.get("explain") if isinstance(graph_rag.get("explain"), dict) else item.get("graph_explain")
        if not isinstance(explain, dict):
            continue
        why = str(explain.get("why") or "").strip().rstrip(".。")
        evidence_type = str(explain.get("evidence_type") or "").upper()
        if not why or evidence_type not in {"EXTRACTED", "INFERRED"}:
            continue
        prefix = "Graph inference" if evidence_type == "INFERRED" else "Direct source evidence"
        line = f"{prefix}: {why}."
        path_text = _graph_path_text(item.get("graph_path") or graph_rag.get("path"))
        if path_text:
            line += f" Path: {path_text}."
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return lines


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


def _judge_rag(
    question: str,
    query: str,
    evidence: list[dict[str, Any]],
    missing: list[str],
) -> RagJudgeResult:
    messages = [
        {
            "role": "system",
            "content": (
                "You judge whether retrieved Prism knowledge evidence is enough to "
                "answer the user's question. Return JSON only, with no markdown."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "search_query": query,
                    "evidence": evidence,
                    "graph_explanations": _graph_explanations_from_evidence(evidence),
                    "previous_missing": missing,
                    "required_json_shape": {
                        "status": "sufficient or insufficient",
                        "answer_basis": "grounded answer basis when sufficient",
                        "useful_chunk_ids": ["chunk ids used when sufficient"],
                        "missing": ["what evidence is missing when insufficient"],
                        "rewrite_query": "better retrieval query when useful",
                        "clarify": {
                            "question": "optional clarification question",
                            "options": [
                                {"label": "option label", "value": "option value"}
                            ],
                        },
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]

    try:
        payload = json.loads(chat(messages))
    except Exception:
        return RagJudgeResult(
            status="insufficient",
            missing=["The evidence judge returned invalid JSON."],
        )

    if not isinstance(payload, dict):
        return RagJudgeResult(
            status="insufficient",
            missing=["The evidence judge returned invalid JSON."],
        )

    if payload.get("status") == "sufficient":
        answer_basis = payload.get("answer_basis")
        useful_chunk_ids = payload.get("useful_chunk_ids", [])
        if (
            not isinstance(answer_basis, str)
            or not answer_basis.strip()
            or not isinstance(useful_chunk_ids, list)
        ):
            return RagJudgeResult(
                status="insufficient",
                missing=["The evidence judge returned malformed sufficient JSON."],
            )

        return RagJudgeResult(
            status="sufficient",
            answer_basis=answer_basis,
            useful_chunk_ids=_as_string_list(useful_chunk_ids),
        )

    clarify = payload.get("clarify")
    return RagJudgeResult(
        status="insufficient",
        missing=_as_string_list(payload.get("missing")),
        rewrite_query=str(payload.get("rewrite_query") or ""),
        clarify=clarify if isinstance(clarify, dict) else None,
    )


def _resolve_search_scope(topic_id: str | None, source_types: list[str] | None = None):
    """从 knowledge_file 表查出 topic 下所有 item_id，用于向量检索后置过滤。"""
    if not topic_id:
        return None
    from backend.app.models.knowledge_item import KnowledgeTopic
    from ..retrieval.contracts import SearchScope

    db = _Session()
    try:
        topic = db.query(KnowledgeTopic).filter(KnowledgeTopic.id == topic_id).one_or_none()
        if topic is None or not topic.active_index_generation:
            return None
        return SearchScope(
            tenant_id=topic.tenant_id, kb_uid=topic.kb_uid,
            index_generation=topic.active_index_generation,
            graph_generation=topic.active_graph_generation,
            source_types=tuple(source_types or ()),
        )
    finally:
        db.close()


def build_agent_runner(
    topic_id: str | None = None,
    source_types: list[str] | None = None,
    clarify_depth: int = 0,
    deep_search_enabled: bool = False,
    deep_search_depth: str = "standard",
    deep_search_top_k: int = 8,
    graph_hops: int = 1,
    rag_max_iterations: int = 3,
) -> LangChainAgentRunner:
    """构造 Agent Runner，注入带过滤的搜索闭包。

    搜索闭包会捕获 topic_id / source_types / allowed_item_ids，
    RAG runner 调用 search(query, top_k) 时自动限定检索范围。
    """
    scope = _resolve_search_scope(topic_id, source_types)
    topic_ids = [topic_id] if topic_id else None

    mode = "deep" if deep_search_enabled else "fast"
    _scoped_search = make_unified_search(
        mode=mode,
        topic_ids=topic_ids,
        source_types=source_types,
        scope=scope,
    )

    rag_runner = AgenticRagRunner(
        search=_scoped_search,
        load_chunks=lambda chunk_ids: _load_chunks(chunk_ids, scope=scope),
        judge=_judge_rag,
        config=RagRunConfig(
            mode=mode,
            top_k=deep_search_top_k,
            graph_hops=graph_hops,
            max_iterations=rag_max_iterations,
        ),
    )
    ctx = ToolContext(
        rag_runner=rag_runner,
        citations=[],
        stats_holder={},
        clarify_holder={},
    )
    tool_overrides = {"deep_knowledge_search": True} if deep_search_enabled else None
    tools = build_enabled_tools(ctx, overrides=tool_overrides)
    model = create_chat_model(settings)
    system_prompt = AGENT_SYSTEM_PROMPT
    if not deep_search_enabled:
        system_prompt = _strip_tool_guidance(system_prompt, {"deep_knowledge_search"})
    if deep_search_enabled:
        system_prompt = (
            AGENT_SYSTEM_PROMPT
            + "\n\n# 深度搜索已开启\n"
            + f"本轮用户开启了深度搜索，最大深度为 `{deep_search_depth}`。"
            + "当问题涉及个人知识库、统一图谱检索、证据完整性、实体关系核实或跨资料综合时，优先调用 deep_knowledge_search。"
        )
    return LangChainAgentRunner(model=model, tools=tools, system_prompt=system_prompt, clarify_depth=clarify_depth)


def answer_stream(
    query: str,
    history: list[dict] | None = None,
    topic_id: str | None = None,
    source_types: list[str] | None = None,
    deep_search_enabled: bool = False,
    deep_search_depth: str = "standard",
    deep_search_top_k: int = 8,
    graph_hops: int = 1,
    rag_max_iterations: int = 3,
    session_id: str | None = None,
    user_message_id: str | None = None,
):
    history = history or []
    # P0-3: Count previous clarify rounds from history to limit depth.
    # Each assistant message with a non-empty clarify JSON counts as one round.
    clarify_depth = sum(
        1 for msg in history
        if msg.get("role") == "assistant" and msg.get("clarify")
    )
    logger.info(
        "[chat] request_start query=%s history_messages=%s topic_id=%s source_types=%s clarify_depth=%s deep_search_enabled=%s deep_search_depth=%s",
        quoted(query),
        len(history),
        topic_id,
        source_types,
        clarify_depth,
        deep_search_enabled,
        deep_search_depth,
    )
    try:
        runner = build_agent_runner(
            topic_id=topic_id,
            source_types=source_types,
            clarify_depth=clarify_depth,
            deep_search_enabled=deep_search_enabled,
            deep_search_depth=deep_search_depth,
            deep_search_top_k=deep_search_top_k,
            graph_hops=graph_hops,
            rag_max_iterations=rag_max_iterations,
        )
        logger.info("[chat] runner_ready")
        trace_recorder = None
        try:
            candidate_recorder = AgentTraceRecorder(
                session_id=session_id,
                user_message_id=user_message_id,
                user_query=query,
                model=settings.LLM_MODEL,
            )
            trace_id = candidate_recorder.start()
            if trace_id:
                trace_recorder = candidate_recorder
                yield trace_event(trace_id)
        except Exception as exc:
            logger.warning(
                "[chat] trace_start_failed; continuing without trace error=%s",
                quoted(str(exc), limit=300),
            )
        yield from runner.stream(query, history, trace_recorder=trace_recorder)
        logger.info("[chat] stream_complete")
    except Exception as exc:
        logger.exception(
            "[chat] request_error error=%s",
            quoted(str(exc), limit=300),
        )
        yield error_event(str(exc))
