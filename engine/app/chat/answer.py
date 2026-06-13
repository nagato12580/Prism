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
from ..retrieval.hybrid import hybrid_search


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def _load_chunks(chunk_ids: list[str]) -> dict[str, str]:
    from backend.app.models.knowledge_item import KnowledgeChunk

    db = _Session()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
        return {chunk.id: chunk.chunk_text for chunk in chunks}
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


def build_agent_runner() -> LangChainAgentRunner:
    rag_runner = AgenticRagRunner(
        search=lambda query, top_k: hybrid_search(query, top_k=top_k),
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


def answer_stream(query: str, history: list[dict] | None = None):
    try:
        runner = build_agent_runner()
        yield from runner.stream(query, history or [])
    except Exception as exc:
        yield error_event(str(exc))
