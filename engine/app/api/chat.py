from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..chat.answer import answer_stream
from ..config import settings
from ..observability import logger, quoted
from ..security.knowledge_scope import InvalidKnowledgeScope, verify_scope


router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    history: Optional[list[dict]] = None
    topic_id: Optional[str] = None
    session_id: Optional[str] = None
    user_message_id: Optional[str] = None
    source_types: Optional[list[str]] = None
    deep_search_enabled: bool = False
    deep_search_depth: Literal["quick", "standard", "deep"] = "standard"
    deep_search_top_k: int = Field(8, ge=1, le=30)
    graph_hops: int = Field(1, ge=1, le=3)
    rag_max_iterations: int = Field(3, ge=1, le=10)


@router.post("/answer")
def chat_answer(
    req: ChatRequest,
    x_prism_knowledge_scope: str | None = Header(default=None),
):
    knowledge_scope = None
    if x_prism_knowledge_scope:
        if not settings.KNOWLEDGE_SCOPE_SECRET:
            raise HTTPException(status_code=503, detail="authorized scope verifier is not configured")
        try:
            knowledge_scope = verify_scope(
                x_prism_knowledge_scope,
                secret=settings.KNOWLEDGE_SCOPE_SECRET,
            )
        except InvalidKnowledgeScope as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    logger.info(
        "[api.chat] request_received query=%s history_messages=%s topic_id=%s source_types=%s deep_search_enabled=%s deep_search_depth=%s",
        quoted(req.query),
        len(req.history or []),
        req.topic_id,
        req.source_types,
        req.deep_search_enabled,
        req.deep_search_depth,
    )

    def stream():
        for line in answer_stream(
            req.query,
            req.history,
            topic_id=req.topic_id,
            source_types=req.source_types,
            deep_search_enabled=req.deep_search_enabled,
            deep_search_depth=req.deep_search_depth,
            deep_search_top_k=req.deep_search_top_k,
            graph_hops=req.graph_hops,
            rag_max_iterations=req.rag_max_iterations,
            session_id=req.session_id,
            user_message_id=req.user_message_id,
            knowledge_scope=knowledge_scope,
        ):
            yield line

    return StreamingResponse(stream(), media_type="application/x-ndjson")
