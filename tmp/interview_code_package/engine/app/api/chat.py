from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..chat.answer import answer_stream
from ..observability import logger, quoted


router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    history: Optional[list[dict]] = None
    topic_id: Optional[str] = None
    session_id: Optional[str] = None
    user_message_id: Optional[str] = None
    source_types: Optional[list[str]] = None
    deep_search_enabled: bool = False
    deep_search_depth: str = "standard"


@router.post("/answer")
def chat_answer(req: ChatRequest):
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
            session_id=req.session_id,
            user_message_id=req.user_message_id,
        ):
            yield line

    return StreamingResponse(stream(), media_type="application/x-ndjson")
