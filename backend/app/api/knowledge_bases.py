# backend/app/api/knowledge_bases.py
from collections import Counter

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import EvaluationRun, KnowledgeJob, KnowledgeTopic
from backend.app.models.knowledge_types import ResourceStatus
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.graph_client import GraphClient
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeAccessPolicy,
    KnowledgeNotFound,
)
from backend.app.services.personal_inbox import ensure_personal_inbox_kb
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
    system_type: str | None = None
    is_system: bool = False
    delete_disabled: bool = False
    status: str
    version: int
    active_index_generation: str | None = None
    active_graph_generation: str | None = None

    model_config = {"from_attributes": True}


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseResponse]
    total: int
    cursor: str | None = None


class KnowledgeBaseGraphResponse(BaseModel):
    view: str
    nodes: list[dict]
    edges: list[dict]
    stats: dict
    focus: dict


def _empty_graph_payload(*, kb_uid: str, view: str, file_uids: tuple[str, ...]) -> dict:
    return {
        "view": view,
        "nodes": [],
        "edges": [],
        "stats": {
            "node_count": 0,
            "edge_count": 0,
            "entity_count": 0,
            "source_count": 0,
            "node_counts": {},
            "edge_counts": {},
        },
        "focus": {
            "view": view,
            "kb_uid": kb_uid,
            "file_uids": list(file_uids),
        },
    }


def _build_graph_stats(nodes: list[dict], edges: list[dict]) -> dict:
    node_counts = Counter(node.get("type", "") for node in nodes)
    edge_counts = Counter(edge.get("type", "") for edge in edges)
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "entity_count": node_counts.get("entity", 0),
        "source_count": sum(count for node_type, count in node_counts.items() if node_type != "entity"),
        "node_counts": dict(node_counts),
        "edge_counts": dict(edge_counts),
    }


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
    ensure_personal_inbox_kb(
        db,
        tenant_id=actor.tenant_id,
        owner_user_id=actor.actor_id,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
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


@router.get("/capabilities/parsers")
def get_parser_capabilities():
    try:
        from engine.app.ingestion.parsers import build_default_registry
        registry = build_default_registry()
        return {"parsers": registry.capabilities()}
    except Exception:
        raise ApiProblem(503, "PARSER_UNAVAILABLE", "Parser registry cannot be loaded")


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


@router.get("/{kb_uid}/graph", response_model=KnowledgeBaseGraphResponse)
def get_knowledge_base_graph(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
    view: str = Query("entity"),
    file_uid: str | None = Query(None),
    file_uids: list[str] = Query(default_factory=list),
    limit: int = Query(120, ge=1, le=500),
):
    try:
        topic = KnowledgeAccessPolicy(db).require_read(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

    scoped_file_uids = tuple(dict.fromkeys(uid for uid in ([file_uid] if file_uid else []) + file_uids if uid))
    if not topic.active_graph_generation:
        return _empty_graph_payload(kb_uid=kb_uid, view=view, file_uids=scoped_file_uids)

    graph = GraphClient()
    try:
        payload = graph.scoped_subgraph(
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            graph_generation=topic.active_graph_generation,
            view=view,
            file_uids=scoped_file_uids,
            limit=limit,
        )
    finally:
        graph.close()

    return {
        "view": view,
        "nodes": payload["nodes"],
        "edges": payload["edges"],
        "stats": _build_graph_stats(payload["nodes"], payload["edges"]),
        "focus": {
            "view": view,
            "kb_uid": kb_uid,
            "file_uids": list(scoped_file_uids),
        },
    }

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

    topic = (
        db.query(KnowledgeTopic)
        .filter_by(tenant_id=actor.tenant_id, kb_uid=kb_uid)
        .with_for_update()
        .one()
    )

    if topic.is_system or topic.delete_disabled:
        raise ApiProblem(
            409,
            "SYSTEM_KB_DELETE_DISABLED",
            "System knowledge bases cannot be deleted",
        )

    active_run_ids = db.query(EvaluationRun.id).filter(
        EvaluationRun.tenant_id == actor.tenant_id,
        EvaluationRun.kb_uid == kb_uid,
        EvaluationRun.status.in_({"queued", "claimed", "running", "cancel_requested"}),
    )
    active_job = db.query(KnowledgeJob.id).filter(
        KnowledgeJob.tenant_id == actor.tenant_id,
        KnowledgeJob.kb_uid == kb_uid,
        KnowledgeJob.job_type == "evaluation",
        KnowledgeJob.status.in_({"queued", "claimed", "running"}),
    ).first()
    if db.query(active_run_ids.exists()).scalar() or active_job is not None:
        raise ApiProblem(409, "EVALUATION_RUN_ACTIVE", "Active evaluations must finish before deleting the knowledge base")

    topic.status = ResourceStatus.DELETING.value
    topic.deleted_at = local_now()
    db.commit()
    db.refresh(topic)
    return topic
