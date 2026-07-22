# backend/app/api/knowledge_bases.py
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import KnowledgeTopic
from backend.app.models.knowledge_types import ResourceStatus
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeAccessPolicy,
    KnowledgeNotFound,
)
from backend.app.api.errors import ApiProblem
from backend.app.utils.time import local_now

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    version: int


class KnowledgeBaseResponse(BaseModel):
    kb_uid: str
    tenant_id: str
    owner_user_id: str
    name: str
    description: str | None = None
    status: str
    version: int
    active_index_generation: str | None = None
    active_graph_generation: str | None = None

    model_config = {"from_attributes": True}


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseResponse]
    total: int
    cursor: str | None = None


@router.post("", status_code=201, response_model=KnowledgeBaseResponse)
def create_knowledge_base(
    body: KnowledgeBaseCreate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    topic = KnowledgeTopic(
        tenant_id=actor.tenant_id,
        owner_user_id=actor.actor_id,
        name=body.name,
        description=body.description,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


@router.get("", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    query = (
        db.query(KnowledgeTopic)
        .filter_by(tenant_id=actor.tenant_id, owner_user_id=actor.actor_id, deleted_at=None)
        .order_by(KnowledgeTopic.created_at.desc(), KnowledgeTopic.kb_uid.desc())
    )
    if cursor:
        cursor_topic = db.query(KnowledgeTopic).filter_by(kb_uid=cursor).one_or_none()
        if cursor_topic:
            query = query.filter(
                (KnowledgeTopic.created_at < cursor_topic.created_at)
                | (
                    (KnowledgeTopic.created_at == cursor_topic.created_at)
                    & (KnowledgeTopic.kb_uid < cursor_topic.kb_uid)
                )
            )
    topics = query.limit(limit + 1).all()
    has_more = len(topics) > limit
    items = topics[:limit]
    next_cursor = items[-1].kb_uid if has_more and items else None
    return KnowledgeBaseListResponse(
        items=items,
        total=len(items),
        cursor=next_cursor,
    )


@router.get("/{kb_uid}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        return KnowledgeAccessPolicy(db).require_read(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")


@router.patch("/{kb_uid}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    kb_uid: str,
    body: KnowledgeBaseUpdate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        topic = KnowledgeAccessPolicy(db).require_manage(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

    # DB-level atomic version check
    expected = body.version
    values = {KnowledgeTopic.version: expected + 1}
    if body.name is not None:
        values[KnowledgeTopic.name] = body.name
    if body.description is not None:
        values[KnowledgeTopic.description] = body.description

    rowcount = (
        db.query(KnowledgeTopic)
        .filter(
            KnowledgeTopic.kb_uid == kb_uid,
            KnowledgeTopic.version == expected,
        )
        .update(values, synchronize_session="fetch")
    )
    db.commit()
    if rowcount != 1:
        raise ApiProblem(409, "VERSION_CONFLICT", f"Expected version {expected}, got current")
    db.refresh(topic)
    return topic


@router.delete("/{kb_uid}", status_code=200, response_model=KnowledgeBaseResponse)
def delete_knowledge_base(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        topic = KnowledgeAccessPolicy(db).require_manage(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

    topic.status = ResourceStatus.DELETING.value
    topic.deleted_at = local_now()
    db.commit()
    db.refresh(topic)
    return topic


@router.get("/capabilities/parsers")
def get_parser_capabilities():
    try:
        from engine.app.ingestion.parsers import build_default_registry
        registry = build_default_registry()
        return {"parsers": registry.capabilities()}
    except ImportError:
        return {"parsers": []}
