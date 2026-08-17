# prism/backend/app/api/agent_chat_proxy.py
"""Backend-authorized streaming chat proxy.

The browser must never own private Engine authorization. This endpoint:

1. Resolves requested/default KBs with ``KnowledgeAccessPolicy`` (tenant+owner
   scoped). Any forbidden or missing KB is rejected with 403/404 *before* the
   Engine is contacted.
2. Signs an ``AuthorizedKnowledgeScope`` for the run and forwards only the
   signed token + public payload to the Engine.
3. Streams the Engine's NDJSON response back without buffering the whole answer,
   using ``httpx.AsyncClient.stream``. On client disconnect the upstream request
   is cancelled by closing the stream context.

No secret, storage URI, internal path, tenant_id, or actor_id is forwarded in
the payload; only the signed scope token carries authorization.
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.models import ChatMessage, ChatSession
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeAccessPolicy,
    KnowledgeNotFound,
)
from backend.app.services.personal_inbox import (
    PERSONAL_INBOX_SYSTEM_TYPE,
    ensure_personal_inbox_kb,
)


router = APIRouter(prefix="/chat", tags=["chat-proxy"])

_SCOPE_TTL_SECONDS = 600


class ChatAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8000)
    kb_uids: list[str] = Field(default_factory=list, max_length=50)
    include_personal_inbox: bool = False
    history: list[dict[str, Any]] | None = None
    session_id: str | None = None
    user_message_id: str | None = None
    resume_trace_id: str | None = None
    mode: Literal["standard", "deep"] = "standard"
    deep_search_enabled: bool = False
    deep_search_depth: Literal["quick", "standard", "deep"] = "standard"
    deep_search_top_k: int = Field(8, ge=1, le=30)
    graph_hops: int = Field(1, ge=1, le=3)
    rag_max_iterations: int = Field(10, ge=1, le=10)


def _public_payload(req: ChatAnswerRequest) -> dict[str, Any]:
    """Payload forwarded to Engine — public fields only, never scope/secrets."""
    payload: dict[str, Any] = {
        "query": req.query,
        "mode": req.mode,
        "deep_search_enabled": req.deep_search_enabled,
        "deep_search_depth": req.deep_search_depth,
        "deep_search_top_k": req.deep_search_top_k,
        "graph_hops": req.graph_hops,
        "rag_max_iterations": req.rag_max_iterations,
        "include_personal_inbox": req.include_personal_inbox,
    }
    if req.history is not None:
        payload["history"] = req.history
    if req.session_id is not None:
        payload["session_id"] = req.session_id
    if req.user_message_id is not None:
        payload["user_message_id"] = req.user_message_id
    if req.resume_trace_id is not None:
        payload["resume_trace_id"] = req.resume_trace_id
    return payload


async def stream_engine_answer(signed_token: str, payload: dict[str, Any]) -> AsyncIterator[bytes]:
    """Stream the Engine NDJSON response.

    Sends the signed scope via a trusted header (never in the JSON body) and
    streams bytes back. The async context closes (and cancels the upstream
    request) when the caller stops iterating. Tests monkeypatch this function.
    """
    headers = {"X-Prism-Knowledge-Scope": signed_token}
    url = f"{settings.ENGINE_BASE_URL.rstrip('/')}/api/v1/chat/answer"
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk


def _authorize_kbs(
    policy: KnowledgeAccessPolicy, actor: ActorContext, kb_uids: list[str]
) -> list[str]:
    allowed: list[str] = []
    for kb_uid in kb_uids:
        try:
            topic = policy.require_read(actor, kb_uid)
        except KnowledgeNotFound:
            raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_uid}")
        except KnowledgeAccessDenied:
            raise HTTPException(status_code=403, detail=f"access denied to knowledge base: {kb_uid}")
        if topic.system_type == PERSONAL_INBOX_SYSTEM_TYPE:
            continue
        allowed.append(kb_uid)
    return allowed


def _authorize_resume_request(db: Session, actor: ActorContext, req: ChatAnswerRequest) -> None:
    if req.resume_trace_id is None:
        return
    if not req.session_id or not req.user_message_id:
        raise HTTPException(status_code=400, detail="resume requires session_id and user_message_id")

    session = db.query(ChatSession).filter(ChatSession.id == req.session_id).first()
    if session is None or session.user_id != actor.actor_id:
        raise HTTPException(status_code=403, detail="access denied to chat session")

    message = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.id == req.user_message_id,
            ChatMessage.session_id == req.session_id,
            ChatMessage.role == "user",
        )
        .first()
    )
    if message is None:
        raise HTTPException(status_code=403, detail="access denied to chat message")


def _sign_run_scope(actor: ActorContext, allowed_kb_uids: list[str]) -> str:
    scope = AuthorizedKnowledgeScope(
        actor_id=actor.actor_id,
        tenant_id=actor.tenant_id,
        allowed_kb_uids=tuple(allowed_kb_uids),
        run_id=f"{actor.actor_id}:{int(time.time() * 1000)}",
        expires_at=int(time.time()) + _SCOPE_TTL_SECONDS,
    )
    if not settings.KNOWLEDGE_SCOPE_SECRET:
        raise HTTPException(status_code=503, detail="knowledge scope signing is not configured")
    return sign_scope(scope, settings.KNOWLEDGE_SCOPE_SECRET)


@router.post("/answer")
async def chat_answer_proxy(
    req: ChatAnswerRequest,
    request: Request,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    _authorize_resume_request(db, actor, req)
    policy = KnowledgeAccessPolicy(db)
    allowed_kb_uids = _authorize_kbs(policy, actor, req.kb_uids)
    if req.include_personal_inbox:
        personal_inbox = ensure_personal_inbox_kb(
            db,
            tenant_id=actor.tenant_id,
            owner_user_id=actor.actor_id,
        )
        if personal_inbox.kb_uid not in allowed_kb_uids:
            allowed_kb_uids.append(personal_inbox.kb_uid)
        db.commit()
    signed_token = _sign_run_scope(actor, allowed_kb_uids)
    if not allowed_kb_uids:
        # No KB authorized — still forward a signed actor scope so non-knowledge
        # tools such as capture_thought bind writes to the current user.
        payload = _public_payload(req)

        async def stream() -> AsyncIterator[bytes]:
            async for chunk in stream_engine_answer(signed_token, payload):
                if await request.is_disconnected():
                    break
                yield chunk

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    payload = _public_payload(req)

    async def stream() -> AsyncIterator[bytes]:
        async for chunk in stream_engine_answer(signed_token, payload):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(stream(), media_type="application/x-ndjson")
