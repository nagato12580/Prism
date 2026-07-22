# backend/app/api/knowledge_bases.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
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
):
    topics = (
        db.query(KnowledgeTopic)
        .filter_by(tenant_id=actor.tenant_id, owner_user_id=actor.actor_id, deleted_at=None)
        .all()
    )
    return KnowledgeBaseListResponse(items=topics, total=len(topics))


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

    if topic.version != body.version:
        raise ApiProblem(409, "VERSION_CONFLICT", f"Expected version {topic.version}, got {body.version}")

    if body.name is not None:
        topic.name = body.name
    if body.description is not None:
        topic.description = body.description
    topic.version = int(topic.version) + 1

    db.commit()
    db.refresh(topic)
    return topic
