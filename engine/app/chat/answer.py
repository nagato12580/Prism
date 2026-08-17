import json
import uuid
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..agent.events import done_event, error_event, needs_kb_selection_event, trace_event
from ..agent.knowledge_skill import compose_system_prompt_with_groups, compose_system_prompt_with_knowledge_skill
from ..agent.rag.agentic import AgenticRagRunner, RagJudgeResult, RagRunConfig
from ..agent.prompts import AGENT_SYSTEM_PROMPT
from ..agent.runner import LangChainAgentRunner, create_chat_model
from ..agent.trace import AgentTraceRecorder
from ..agent.tools import (
    BUILTIN_REGISTRY,
    COMMON_TOOLS,
    TOOL_GROUPS,
    ToolContext,
    build_enabled_tools,
    build_tools_by_groups,
)
from ..agent.tools.knowledge_base import build_tools as build_knowledge_tools
from ..config import settings
from ..llm.client import chat
from ..observability import logger, quoted
from ..api.retrieval import AuthorizedKnowledgeScope as RetrievalScope
from ..api.retrieval import RetrievalOverrides, RetrievalRequest, execute_retrieval
from ..retrieval.unified import make_unified_search


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


_DEPTH_CONTROLS = {
    "quick": (1, 1),
    "standard": (2, 3),
    "deep": (3, 5),
}

# ---------------------------------------------------------------------------
# Intent classification for dynamic tool-group injection
# ---------------------------------------------------------------------------

_INTENT_CLASSIFY_PROMPT = """你是意图分类器。根据用户当前问题和 recent_history 中提供的近期对话记录，判断后续对话需要启用哪些工具组。必须结合当前问题与近期对话记录理解上下文；若近期记录为空，只根据当前问题分类。

工具组定义：
- record（记录工具）：用户明确要求记录、收藏想法、观点、心得、待办或资源。
- memory（记忆工具）：用户需要查询自己的偏好、目标、长期记忆、个人背景或历史设置。
- knowledge（知识库工具）：用户需要检索知识库、查询上传的文档或资料、读取文件内容。

分类规则：
1. 闲聊、打招呼、简单问答不需要任何工具组。
2. 明确要求记录、收藏或保存时启用 record。
3. 涉及用户偏好、历史、个人设定或之前说过的内容时启用 memory。
4. 需要查询资料、文档或知识库内容时启用 knowledge。
5. 知识库问题也涉及用户个人偏好时，可以同时启用 knowledge 和 memory。
6. 用户明确提到具体知识库名称时，在 kb_specs 中列出。
7. 必须结合当前问题与近期对话记录分类。当前输入出现“这些 / 它 / 它们 / 继续 / 刚才那个 / 这篇 / 上述 / 前面”等代词或省略式指代时，先使用近期对话补全语义，再进行分类。
8. 近期对话讨论知识库文档、论文、上传资料、引用、表格或章节时，简短的追问通常继承相同的知识任务领域，应启用 knowledge。
9. 如果最近一条助手消息刚枚举了一组对象，用户追问“出处 / 分别 / 展开 / 继续 / 对比”等内容时，通常仍是知识任务，应启用 knowledge。
10. 问题需要结合用户个人背景解释“我的论文 / 我的项目 / 我的设定”等表达时，可以同时启用 memory 和 knowledge。

输入是 JSON 对象，包含 query（当前问题）和 recent_history（近期对话记录）。

返回纯 JSON（不要 markdown 代码块），且必须保持以下结构：
{"groups": ["knowledge", "memory"], "kb_specs": [], "reasoning": "简短中文说明"}

如果不需要任何工具组，groups 为空数组。"""


def classify_intent(query: str, history: list[dict] | None = None) -> dict[str, Any]:
    """Classify user intent into tool groups using a fast LLM call.

    Returns a dict with keys ``groups`` (list of group keys), ``kb_specs``
    (list of explicitly mentioned KB names), and ``reasoning`` (short
    explanation).  On failure, defaults to enabling all groups for safety.
    """
    classifier_input = {
        "query": query,
        "recent_history": _intent_history_payload(history),
    }
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _INTENT_CLASSIFY_PROMPT},
        {"role": "user", "content": json.dumps(classifier_input, ensure_ascii=False)},
    ]
    try:
        raw = chat(messages, timeout_seconds=5, max_retries=0)
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.lstrip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("classification result is not a dict")
        groups = result.get("groups")
        if not isinstance(groups, list):
            groups = []
        # Normalise to known group keys only
        valid_groups = [g for g in groups if g in TOOL_GROUPS]
        kb_specs = result.get("kb_specs")
        if not isinstance(kb_specs, list):
            kb_specs = []
        logger.info(
            "[chat] intent_classified groups=%s kb_specs=%s reasoning=%s",
            valid_groups,
            kb_specs,
            result.get("reasoning", ""),
        )
        return {"groups": valid_groups, "kb_specs": kb_specs, "reasoning": result.get("reasoning", "")}
    except Exception as exc:
        logger.warning("[chat] intent_classification_failed fallback=all error=%s", quoted(str(exc), limit=200))
        return {
            "groups": list(TOOL_GROUPS.keys()),
            "kb_specs": [],
            "reasoning": "classification failed, fallback to all",
        }


class _KnowledgeRetrievalService:
    def __init__(self, db):
        self.db = db

    def query(
        self,
        *,
        tenant_id: str,
        kb_uid: str,
        query: str,
        mode: str = "fast",
        file_uids: tuple[str, ...] = (),
        top_k: int = 10,
        depth: str = "standard",
        graph_hops: int | None = None,
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        from backend.app.models import KnowledgeTopic

        topic = (
            self.db.query(KnowledgeTopic)
            .filter(
                KnowledgeTopic.tenant_id == tenant_id,
                KnowledgeTopic.kb_uid == kb_uid,
                KnowledgeTopic.deleted_at.is_(None),
            )
            .first()
        )
        if topic is None or not topic.active_index_generation:
            return {
                "status": "unavailable",
                "evidence": [],
                "warnings": [
                    {
                        "code": "RETRIEVAL_UNAVAILABLE",
                        "message": "Knowledge base has no active index",
                        "retryable": True,
                    }
                ],
            }
        request = RetrievalRequest(
            query=query,
            mode="deep" if mode == "deep" else "fast",
            filters={"file_uids": tuple(file_uids), "source_types": ()},
            config=RetrievalOverrides(top_k=top_k),
        )
        scope = RetrievalScope(
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            index_generation=topic.active_index_generation,
            graph_generation=topic.active_graph_generation,
        )
        if mode == "deep":
            return self._agentic_query(
                scope=scope,
                query=query,
                file_uids=tuple(file_uids),
                top_k=top_k,
                depth=depth,
                graph_hops=graph_hops,
                max_iterations=max_iterations,
            )
        response = execute_retrieval(request, scope)
        return response.model_dump()

    def _agentic_query(
        self,
        *,
        scope: RetrievalScope,
        query: str,
        file_uids: tuple[str, ...],
        top_k: int,
        depth: str,
        graph_hops: int | None,
        max_iterations: int | None,
    ) -> dict[str, Any]:
        depth_hops, depth_iterations = _DEPTH_CONTROLS.get(depth, _DEPTH_CONTROLS["standard"])
        effective_hops = depth_hops
        if graph_hops is not None and depth == "quick":
            effective_hops = min(graph_hops, depth_hops)
        effective_iterations = depth_iterations
        if max_iterations is not None:
            effective_iterations = min(max_iterations, depth_iterations)
        scope = scope.model_copy(update={"file_uids": tuple(file_uids), "source_types": ()})
        search = make_unified_search(mode="deep", scope=scope)
        runner = AgenticRagRunner(
            search=search,
            load_chunks=lambda chunk_ids: _load_chunks(chunk_ids, scope=scope),
            judge=_judge_rag,
            config=RagRunConfig(
                mode="deep",
                top_k=top_k,
                graph_hops=effective_hops,
                max_iterations=effective_iterations,
            ),
        )
        result = runner.run(query)
        evidence = []
        for hit in result.evidence:
            item = self._agentic_hit_to_evidence(scope, hit)
            if item is not None:
                evidence.append(item)
        status = "ok" if result.status == "sufficient" else ("degraded" if evidence else "no_hits")
        warnings = [] if result.status == "sufficient" else [{
            "code": "AGENTIC_RAG_INSUFFICIENT",
            "message": "agentic retrieval did not judge the evidence sufficient",
            "retryable": False,
        }]
        return {
            "status": status,
            "evidence": evidence,
            "warnings": warnings,
            "retrieval_health": {
                "agentic": {
                    "status": result.status,
                    "iterations": result.iterations,
                    "depth": depth,
                    "graph_hops": effective_hops,
                }
            },
        }

    @staticmethod
    def _agentic_hit_to_evidence(scope: RetrievalScope, hit: dict[str, Any]) -> dict[str, Any] | None:
        file_uid = hit.get("file_uid")
        chunk_uid = hit.get("chunk_uid") or hit.get("chunk_id")
        if not file_uid or not chunk_uid:
            return None
        channels = hit.get("channels")
        if isinstance(channels, dict):
            retrieval_channels = tuple(channels.keys())
        elif isinstance(channels, (list, tuple)):
            retrieval_channels = tuple(str(item) for item in channels)
        else:
            retrieval_channels = ()
        graph_rag = hit.get("graph_rag") if isinstance(hit.get("graph_rag"), dict) else {}
        return {
            "tenant_id": scope.tenant_id,
            "kb_uid": scope.kb_uid,
            "file_uid": str(file_uid),
            "item_id": hit.get("item_id"),
            "chunk_uid": str(chunk_uid),
            "display_title": str(hit.get("display_title") or hit.get("title") or hit.get("doc_name") or ""),
            "excerpt": str(hit.get("excerpt") or hit.get("snippet") or hit.get("text") or ""),
            "score": hit.get("rerank_score") or hit.get("score") or hit.get("rrf_score"),
            "retrieval_channels": retrieval_channels,
            "graph_path": graph_rag.get("path") if isinstance(graph_rag, dict) else (),
            "evidence_type": "chunk",
            "index_generation": scope.index_generation,
        }


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
        topic = db.query(KnowledgeTopic).filter(KnowledgeTopic.kb_uid == topic_id).one_or_none()
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


def _resolve_scope_for_topic(topic_id: str) -> Any | None:
    """Resolve an AuthorizedKnowledgeScope for a single *topic_id*.

    Used as a backward-compatible fallback when the knowledge group is active
    but no scope was pre-signed by the backend proxy.
    """
    from backend.app.models.knowledge_item import KnowledgeTopic
    from ..security.knowledge_scope import AuthorizedKnowledgeScope

    db = _Session()
    try:
        topic = db.query(KnowledgeTopic).filter(
            KnowledgeTopic.kb_uid == topic_id,
            KnowledgeTopic.deleted_at.is_(None),
        ).first()
        if topic is None:
            return None
        return AuthorizedKnowledgeScope(
            actor_id="default-user",
            tenant_id=topic.tenant_id,
            allowed_kb_uids=(topic.kb_uid,),
            run_id=f"legacy:{uuid.uuid4().hex[:12]}",
            expires_at=int(__import__("time").time()) + 600,
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
    knowledge_scope: Any | None = None,
    retrieval_service: Any | None = None,
    db_session: Any | None = None,
    trace_id: str | None = None,
    tool_groups: list[str] | None = None,
) -> LangChainAgentRunner:
    """Construct an Agent Runner with dynamically selected tool groups.

    When *tool_groups* is provided, tools are built only from the selected
    groups plus common tools.  When the ``knowledge`` group is active, a
    valid *knowledge_scope* gates access to KB tools; without it the legacy
    ``knowledge_search`` / ``deep_knowledge_search`` path is used instead.

    When *tool_groups* is ``None`` or empty, the behaviour is backward
    compatible: the full default-enabled toolset is used.
    """
    tool_groups = tool_groups or []
    has_knowledge = "knowledge" in tool_groups
    model = create_chat_model(settings)

    # --- Build ToolContext ---------------------------------------------------
    ctx_kwargs: dict[str, Any] = dict(
        citations=[],
        stats_holder={},
        clarify_holder={},
        deep_search_enabled=deep_search_enabled,
        deep_search_depth=deep_search_depth,
        deep_search_top_k=deep_search_top_k,
        graph_hops=graph_hops,
        rag_max_iterations=rag_max_iterations,
    )

    # --- Path A: Knowledge group + authorized scope (six-tool KB path) ------
    allowed_kb_uids = getattr(knowledge_scope, "allowed_kb_uids", None)
    if has_knowledge and knowledge_scope is not None and allowed_kb_uids is not None:
        ctx = ToolContext(
            db=db_session,
            trace_id=trace_id or getattr(knowledge_scope, "run_id", None),
            run_id=getattr(knowledge_scope, "run_id", None),
            knowledge_scope=knowledge_scope,
            retrieval_service=retrieval_service,
            **ctx_kwargs,
        )
        tools = build_tools_by_groups(ctx, tool_groups, deep_search_enabled=deep_search_enabled)
        system_prompt = compose_system_prompt_with_groups(AGENT_SYSTEM_PROMPT, tool_groups)
        return LangChainAgentRunner(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=rag_max_iterations,
            clarify_depth=clarify_depth,
        )

    # --- Path B: Knowledge group WITHOUT authorized scope (legacy rag_runner) -
    if has_knowledge:
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
        ctx = ToolContext(rag_runner=rag_runner, **ctx_kwargs)
        tools = build_tools_by_groups(ctx, tool_groups, deep_search_enabled=deep_search_enabled)
        system_prompt = compose_system_prompt_with_groups(AGENT_SYSTEM_PROMPT, tool_groups)
        if deep_search_enabled:
            system_prompt += (
                "\n\n# 深度搜索已开启\n"
                + f"本轮用户开启了深度搜索，最大深度为 `{deep_search_depth}`。"
                + "当问题涉及个人知识库、统一图谱检索、证据完整性、实体关系核实或跨资料综合时，优先调用 deep_knowledge_search。"
            )
        return LangChainAgentRunner(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=rag_max_iterations,
            clarify_depth=clarify_depth,
        )

    # --- Path C: No knowledge group (record / memory / common only) ----------
    ctx = ToolContext(knowledge_scope=knowledge_scope, **ctx_kwargs)
    tools = build_tools_by_groups(ctx, tool_groups, deep_search_enabled=deep_search_enabled)
    system_prompt = compose_system_prompt_with_groups(AGENT_SYSTEM_PROMPT, tool_groups)
    return LangChainAgentRunner(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        max_iterations=rag_max_iterations,
        clarify_depth=clarify_depth,
    )


def _intent_history_payload(history: list[dict] | None) -> list[dict[str, str]]:
    if not history:
        return []

    return [
        {"role": item["role"], "content": item["content"]}
        for item in history
        if isinstance(item, dict)
        and item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str)
        and item["content"].strip()
    ]


def _recent_turn_history(history: list[dict[str, Any]], turns: int) -> list[dict[str, Any]]:
    if turns <= 0:
        return []

    selected: list[dict[str, Any]] = []
    user_turns = 0
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        selected.append(item)
        if role == "user":
            user_turns += 1
            if user_turns >= turns:
                break
    return list(reversed(selected))


def _resume_tool_selection_from_checkpoint(checkpoint: Any) -> tuple[list[str], bool]:
    if not isinstance(checkpoint, dict):
        return [], False
    messages = checkpoint.get("messages")
    if not isinstance(messages, list):
        return [], False

    tool_to_group: dict[str, str] = {}
    for group, group_def in TOOL_GROUPS.items():
        tools = group_def.get("tools") if isinstance(group_def, dict) else None
        if not isinstance(tools, list):
            continue
        for tool_name in tools:
            if isinstance(tool_name, str) and tool_name not in COMMON_TOOLS:
                tool_to_group[tool_name] = group

    groups: set[str] = set()
    has_deep_knowledge_search = False
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "ai":
            continue
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_name = tool_call.get("name")
            if tool_name == "deep_knowledge_search":
                has_deep_knowledge_search = True
            group = tool_to_group.get(tool_name)
            if group is not None:
                groups.add(group)

    return [group for group in TOOL_GROUPS if group in groups], has_deep_knowledge_search


def _tool_groups_for_resume_checkpoint(checkpoint: Any) -> list[str]:
    return _resume_tool_selection_from_checkpoint(checkpoint)[0]


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
    knowledge_scope: Any | None = None,
    resume_trace_id: str | None = None,
):
    history = history or []
    db_session = _Session() if knowledge_scope is not None else None
    retrieval_service = _KnowledgeRetrievalService(db_session) if db_session is not None else None
    # P0-3: Count previous clarify rounds from history to limit depth.
    # Each assistant message with a non-empty clarify JSON counts as one round.
    clarify_depth = sum(
        1 for msg in history
        if msg.get("role") == "assistant" and msg.get("clarify")
    )
    # Resume requests must use the saved checkpoint before any new-request preflight.
    if resume_trace_id:
        if not session_id or not user_message_id:
            yield error_event("Cannot resume agent run: resume requires session/user message identifiers.")
            yield done_event()
            if db_session is not None:
                db_session.close()
            return
        try:
            checkpoint = AgentTraceRecorder.load_checkpoint(
                resume_trace_id,
                session_id=session_id,
                user_message_id=user_message_id,
            )
            if checkpoint is None:
                yield error_event("Cannot resume agent run: checkpoint not found or already completed.")
                yield done_event()
                return
            tool_groups, checkpoint_has_deep_search = _resume_tool_selection_from_checkpoint(checkpoint)
            trace_recorder = None
            attach_recorder = getattr(AgentTraceRecorder, "for_existing_trace", None)
            if callable(attach_recorder):
                try:
                    trace_recorder = attach_recorder(
                        resume_trace_id,
                        session_id=session_id,
                        user_message_id=user_message_id,
                    )
                    if trace_recorder is None:
                        logger.warning(
                            "[chat] resume_trace_attach_skipped trace_id=%s",
                            resume_trace_id,
                        )
                        yield error_event("Cannot resume agent run: trace ownership validation failed.")
                        yield done_event()
                        return
                except Exception as exc:
                    logger.warning(
                        "[chat] resume_trace_attach_failed trace_id=%s error=%s",
                        resume_trace_id,
                        quoted(str(exc), limit=300),
                    )
                    yield error_event("Cannot resume agent run: trace ownership validation failed.")
                    yield done_event()
                    return
            runner = build_agent_runner(
                topic_id=topic_id,
                source_types=source_types,
                clarify_depth=clarify_depth,
                deep_search_enabled=deep_search_enabled or checkpoint_has_deep_search,
                deep_search_depth=deep_search_depth,
                deep_search_top_k=deep_search_top_k,
                graph_hops=graph_hops,
                rag_max_iterations=rag_max_iterations,
                knowledge_scope=knowledge_scope,
                db_session=db_session,
                retrieval_service=retrieval_service,
                tool_groups=tool_groups,
            )
            logger.info("[chat] runner_ready")
            yield from runner.resume_stream(checkpoint, trace_recorder=trace_recorder)
            logger.info("[chat] resume_stream_complete trace_id=%s", resume_trace_id)
            return
        except Exception as exc:
            logger.exception(
                "[chat] request_error error=%s",
                quoted(str(exc), limit=300),
            )
            yield error_event(str(exc))
            yield done_event()
            return
        finally:
            if db_session is not None:
                db_session.close()

    # --- Intent classification → dynamic tool groups -------------------------
    intent_history = _recent_turn_history(history, settings.INTENT_RECENT_TURNS)
    intent = classify_intent(query, intent_history)
    tool_groups = intent.get("groups", [])
    kb_specs = intent.get("kb_specs", [])
    # If knowledge group is active but no scope was pre-signed by the backend
    # proxy, try to resolve scope from topic_id for backward compatibility.
    has_knowledge = "knowledge" in tool_groups
    # Preflight: knowledge intent with no authorized scope and no legacy topic
    # cannot reach KB tools. Surface a structured prompt instead of exposing
    # internal "knowledge scope not configured" errors. The signed-scope and
    # `_require_scope()` checks in the tools remain the final safety boundary.
    if has_knowledge and knowledge_scope is None and not topic_id:
        yield needs_kb_selection_event(query, intent.get("reasoning", ""))
        return
    if has_knowledge and knowledge_scope is None and topic_id:
        knowledge_scope = _resolve_scope_for_topic(topic_id)
        if knowledge_scope is not None and db_session is None:
            db_session = _Session()
            retrieval_service = _KnowledgeRetrievalService(db_session)
    logger.info(
        "[chat] request_start query=%s history_messages=%s topic_id=%s source_types=%s "
        "clarify_depth=%s deep_search_enabled=%s deep_search_depth=%s "
        "tool_groups=%s kb_specs=%s has_knowledge=%s has_scope=%s",
        quoted(query),
        len(history),
        topic_id,
        source_types,
        clarify_depth,
        deep_search_enabled,
        deep_search_depth,
        tool_groups,
        kb_specs,
        has_knowledge,
        knowledge_scope is not None,
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
            knowledge_scope=knowledge_scope,
            db_session=db_session,
            retrieval_service=retrieval_service,
            tool_groups=tool_groups,
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
    finally:
        if db_session is not None:
            db_session.close()
