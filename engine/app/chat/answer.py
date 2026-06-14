import json
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..agent.events import error_event
from ..agent.rag.agentic import AgenticRagRunner, RagJudgeResult
from ..agent.runner import LangChainAgentRunner, create_chat_model
from ..agent.tools import ToolContext, build_enabled_tools
from ..config import settings
from ..llm.client import chat
from ..observability import logger, quoted
from ..retrieval.hybrid import hybrid_search


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def _load_chunks(chunk_ids: list[str]) -> dict[str, dict[str, str]]:
    """加载 chunk 文本和所属文档名。

    Returns: {chunk_id: {"text": str, "doc_name": str}}
    """
    from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem, KnowledgeFile

    db = _Session()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
        if not chunks:
            return {}

        # 批量取 item 信息
        item_ids = {chunk.item_id for chunk in chunks}
        items = {
            row[0]: row[1]
            for row in db.query(KnowledgeItem.id, KnowledgeItem.title)
            .filter(KnowledgeItem.id.in_(item_ids))
            .all()
        }
        # 批量取 doc_name（优先 knowledge_file 的 title/original_filename）
        files = {
            row[0]: row[1] or row[2] or ""
            for row in db.query(KnowledgeFile.item_id, KnowledgeFile.title, KnowledgeFile.original_filename)
            .filter(KnowledgeFile.item_id.in_(item_ids))
            .all()
        }

        result = {}
        for chunk in chunks:
            doc_name = files.get(chunk.item_id) or items.get(chunk.item_id, "")
            result[chunk.id] = {"text": chunk.chunk_text, "doc_name": doc_name}
        return result
    finally:
        db.close()


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


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


def _resolve_allowed_item_ids(topic_id: str | None) -> set[str] | None:
    """从 knowledge_file 表查出 topic 下所有 item_id，用于向量检索后置过滤。"""
    if not topic_id:
        return None
    from backend.app.models.knowledge_item import KnowledgeFile

    db = _Session()
    try:
        item_ids = (
            db.query(KnowledgeFile.item_id)
            .filter(
                KnowledgeFile.topic_id == topic_id,
                KnowledgeFile.item_id.isnot(None),
            )
            .all()
        )
        return {row[0] for row in item_ids if row[0]}
    finally:
        db.close()


def build_agent_runner(
    topic_id: str | None = None,
    source_types: list[str] | None = None,
) -> LangChainAgentRunner:
    """构造 Agent Runner，注入带过滤的搜索闭包。

    搜索闭包会捕获 topic_id / source_types / allowed_item_ids，
    RAG runner 调用 search(query, top_k) 时自动限定检索范围。
    """
    allowed_item_ids = _resolve_allowed_item_ids(topic_id)
    topic_ids = [topic_id] if topic_id else None

    def _scoped_search(query: str, top_k: int) -> list[dict]:
        return hybrid_search(
            query,
            top_k=top_k,
            topic_ids=topic_ids,
            source_types=source_types,
            allowed_item_ids=allowed_item_ids,
        )

    rag_runner = AgenticRagRunner(
        search=_scoped_search,
        load_chunks=_load_chunks,
        judge=_judge_rag,
        max_iterations=3,
        top_k=8,
    )
    ctx = ToolContext(
        rag_runner=rag_runner,
        citations=[],
        stats_holder={},
        clarify_holder={},
    )
    tools = build_enabled_tools(ctx)
    model = create_chat_model(settings)
    return LangChainAgentRunner(model=model, tools=tools)


def answer_stream(
    query: str,
    history: list[dict] | None = None,
    topic_id: str | None = None,
    source_types: list[str] | None = None,
):
    history = history or []
    logger.info(
        "[chat] request_start query=%s history_messages=%s topic_id=%s source_types=%s",
        quoted(query),
        len(history),
        topic_id,
        source_types,
    )
    try:
        runner = build_agent_runner(topic_id=topic_id, source_types=source_types)
        logger.info("[chat] runner_ready")
        yield from runner.stream(query, history)
        logger.info("[chat] stream_complete")
    except Exception as exc:
        logger.exception(
            "[chat] request_error error=%s",
            quoted(str(exc), limit=300),
        )
        yield error_event(str(exc))
