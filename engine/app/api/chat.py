# prism/engine/app/api/chat.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from ..observability import logger, quoted
from ..chat.answer import answer_stream

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    history: Optional[list[dict]] = None


@router.post("/answer")
def chat_answer(req: ChatRequest):
    logger.info(
        "[api.chat] request_received query=%s history_messages=%s",
        quoted(req.query),
        len(req.history or []),
    )

    def stream():
        for line in answer_stream(req.query, req.history):
            yield line
    return StreamingResponse(stream(), media_type="application/x-ndjson")
