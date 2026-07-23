import logging

import httpx
from pydantic import ValidationError
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiProblem
from backend.app.config import settings
from backend.app.database import get_db
from backend.app.schemas.knowledge import EngineRetrievalEnvelope, KnowledgeRetrievalQuery, KnowledgeRetrievalResponse
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy, KnowledgeNotFound


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-retrieval"])
logger = logging.getLogger("uvicorn.error")


class EnginePayloadDecodeError(ValueError):
    pass


def call_engine_retrieval(request: dict) -> dict:
    # Scope is intentionally not serialized into request JSON. A later trusted
    # transport adapter must bind it to Engine's verifier dependency.
    public_request = {key: value for key, value in request.items() if key != "scope"}
    response = httpx.post(
        f"{settings.ENGINE_BASE_URL.rstrip('/')}/api/v1/internal/retrieval/query",
        json=public_request,
        timeout=30.0,
    )
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise EnginePayloadDecodeError("engine returned invalid JSON") from exc


@router.post("/{kb_uid}/retrieval/query", response_model=KnowledgeRetrievalResponse)
def query_knowledge_base(
    kb_uid: str,
    body: KnowledgeRetrievalQuery,
    response: Response,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        topic = KnowledgeAccessPolicy(db).require_read(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

    if not topic.active_index_generation:
        raise ApiProblem(503, "RETRIEVAL_UNAVAILABLE", "Knowledge base has no active index", retryable=True)

    request = {
        "scope": {
            "tenant_id": actor.tenant_id,
            "kb_uid": topic.kb_uid,
            "index_generation": topic.active_index_generation,
            "graph_generation": topic.active_graph_generation,
        },
        "query": body.query,
        "mode": body.mode,
        "filters": body.filters.model_dump(mode="json"),
        "config": body.config.model_dump(mode="json"),
    }
    try:
        raw_result = call_engine_retrieval(request)
        result = EngineRetrievalEnvelope.model_validate(raw_result)
    except (httpx.HTTPError, EnginePayloadDecodeError, ValidationError) as exc:
        logger.warning("[knowledge-retrieval] engine response unavailable err=%r", exc)
        raise ApiProblem(
            503,
            "RETRIEVAL_UNAVAILABLE",
            "Retrieval service is unavailable",
            retryable=True,
        )

    status = result.status
    if status == "unavailable":
        raise ApiProblem(503, "RETRIEVAL_UNAVAILABLE", "Retrieval engine unavailable", retryable=True)
    if status == "invalid_request":
        raise ApiProblem(422, "INVALID_RETRIEVAL_REQUEST", "Retrieval request is invalid")
    if status == "degraded":
        response.status_code = 206
    return KnowledgeRetrievalResponse.model_validate(result.model_dump())
