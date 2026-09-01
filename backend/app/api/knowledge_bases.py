# backend/app/api/knowledge_bases.py
import logging
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import (
    EntityMention,
    EntityRelation,
    EvaluationRun,
    KnowledgeBaseMembership,
    KnowledgeChunk,
    KnowledgeEntity,
    KnowledgeFile,
    KnowledgeItem,
    KnowledgeJob,
    KnowledgeTopic,
)
from backend.app.models.knowledge_types import KnowledgeGovernanceStatus, ResourceStatus
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.graph_client import GraphClient
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeAccessPolicy,
    KnowledgeNotFound,
)
from backend.app.services.knowledge_rbac import (
    accept_transfer,
    list_memberships,
    reject_transfer,
    remove_membership,
    request_transfer,
    upsert_membership,
    withdraw_transfer,
)
from backend.app.services.personal_inbox import ensure_personal_inbox_kb
from backend.app.api.errors import ApiProblem
from backend.app.utils.time import local_now

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])
logger = logging.getLogger(__name__)


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
    governance_status: str = KnowledgeGovernanceStatus.PERSONAL.value
    transfer_requested_by: str | None = None
    transfer_requested_at: datetime | None = None
    transfer_message: str | None = None
    transfer_reviewed_by: str | None = None
    transfer_reviewed_at: datetime | None = None
    transfer_rejection_reason: str | None = None
    my_role: str | None = None
    can_read: bool = False
    can_contribute: bool = False
    can_edit: bool = False
    can_manage_members: bool = False
    can_delete: bool = False

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


# ---------------------------------------------------------------------------
# RBAC DTOs
# ---------------------------------------------------------------------------


class TransferRequestCreate(BaseModel):
    message: str | None = None


class TransferRejectRequest(BaseModel):
    reason: str | None = None


class MembershipUpdate(BaseModel):
    role: str


class MembershipResponse(BaseModel):
    user_id: str
    role: str
    granted_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


def _kb_response(topic: KnowledgeTopic, actor: ActorContext, policy: KnowledgeAccessPolicy) -> dict:
    payload = KnowledgeBaseResponse.model_validate(topic).model_dump()
    payload.update(policy.capabilities(actor, topic))
    return payload


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


def _mysql_entity_graph_fallback(
    db: Session,
    *,
    tenant_id: str,
    kb_uid: str,
    graph_generation: str,
    view: str,
    file_uids: tuple[str, ...],
    limit: int,
) -> dict:
    """Rebuild a per-file subgraph from MySQL facts when the Neo4j scoped
    projection is still empty.

    Neo4j projection is asynchronous (outbox -> Neo4jOutboxProjector), so
    ``scoped_subgraph`` can return no nodes right after ingestion even though
    ``GraphFactWriter`` already wrote EntityMention/EntityRelation synchronously.
    This fallback produces the same node/edge shape as ``scoped_subgraph`` so
    the document graph tab renders immediately.
    """
    if not file_uids:
        return {"nodes": [], "edges": []}

    mentions = (
        db.query(EntityMention)
        .filter(
            EntityMention.tenant_id == tenant_id,
            EntityMention.kb_uid == kb_uid,
            EntityMention.graph_generation == graph_generation,
            EntityMention.file_uid.in_(file_uids),
            EntityMention.active == "true",
            EntityMention.source_kind == "document_chunk",
        )
        .order_by(EntityMention.created_at.asc())
        .limit(max(limit * 6, 200))
        .all()
    )
    if not mentions:
        return {"nodes": [], "edges": []}

    entity_ids = {mention.entity_id for mention in mentions if mention.entity_id}
    source_ids = {mention.source_id for mention in mentions if mention.source_id}

    entities = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.id.in_(entity_ids),
            KnowledgeEntity.tenant_id == tenant_id,
            KnowledgeEntity.kb_uid == kb_uid,
            KnowledgeEntity.graph_generation == graph_generation,
        )
        .all()
    )
    entity_by_id = {entity.id: entity for entity in entities}

    chunks = (
        db.query(KnowledgeChunk)
        .filter(or_(KnowledgeChunk.id.in_(source_ids), KnowledgeChunk.chunk_uid.in_(source_ids)))
        .all()
    )
    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    chunk_by_id.update({chunk.chunk_uid: chunk for chunk in chunks})

    item_ids = {chunk.item_id for chunk in chunks if chunk.item_id}
    items = (
        db.query(KnowledgeItem).filter(KnowledgeItem.id.in_(item_ids)).all()
        if item_ids
        else []
    )
    item_by_id = {item.id: item for item in items}

    file_ids = {chunk.file_uid for chunk in chunks if chunk.file_uid}
    files = (
        db.query(KnowledgeFile).filter(KnowledgeFile.file_uid.in_(file_ids)).all()
        if file_ids
        else []
    )
    file_by_uid = {file_row.file_uid: file_row for file_row in files}

    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    for entity in entities:
        node_id = f"entity:{entity.id}"
        nodes[node_id] = {
            "id": node_id,
            "type": "entity",
            "label": str(entity.canonical_name or entity.normalized_key or entity.id),
            "ref_id": entity.id,
            "entity_type": entity.entity_type,
            "normalized_key": entity.normalized_key,
            "confidence": entity.confidence,
            "status": entity.status,
        }

    for mention in mentions:
        chunk = chunk_by_id.get(mention.source_id)
        item = item_by_id.get(chunk.item_id) if chunk and chunk.item_id else None
        file_row = file_by_uid.get(mention.file_uid) or (
            file_by_uid.get(chunk.file_uid) if chunk and chunk.file_uid else None
        )

        source_node_id = f"chunk:{mention.source_kind}:{mention.source_id}"
        if file_row:
            label = file_row.title or file_row.original_filename or mention.source_id
        elif item and item.title:
            label = item.title
        else:
            label = mention.source_id
        nodes[source_node_id] = {
            "id": source_node_id,
            "type": "document_chunk",
            "label": str(label),
            "ref_id": mention.source_id,
            "file_uid": mention.file_uid,
            "chunk_uid": mention.chunk_uid,
            "source_kind": mention.source_kind or "document_chunk",
            "source_id": mention.source_id,
            "item_id": mention.item_id,
        }

        entity_node_id = f"entity:{mention.entity_id}"
        if view == "source":
            edge_id = mention.id or f"edge:mention:{mention.entity_id}:{mention.source_id}"
            edges[edge_id] = {
                "id": edge_id,
                "source": source_node_id,
                "target": entity_node_id,
                "type": "mentions_entity",
                "label": "mentions_entity",
                "confidence": mention.confidence,
            }
        else:
            edge_id = mention.id or f"edge:mention:{mention.entity_id}:{mention.source_id}"
            edges[edge_id] = {
                "id": edge_id,
                "source": entity_node_id,
                "target": source_node_id,
                "type": "mentioned_in",
                "label": "mentioned_in",
                "confidence": mention.confidence,
            }

    if entity_ids:
        relations = (
            db.query(EntityRelation)
            .filter(
                EntityRelation.tenant_id == tenant_id,
                EntityRelation.kb_uid == kb_uid,
                EntityRelation.graph_generation == graph_generation,
                EntityRelation.file_uid.in_(file_uids),
                EntityRelation.active == "true",
                EntityRelation.subject_entity_id.in_(entity_ids),
            )
            .order_by(EntityRelation.created_at.asc())
            .limit(max(limit * 6, 200))
            .all()
        )
        for relation in relations:
            if not relation.object_entity_id or relation.object_entity_id not in entity_ids:
                continue
            edge_id = relation.id or (
                f"edge:related:{relation.subject_entity_id}:{relation.object_entity_id}:{relation.predicate}"
            )
            edges[edge_id] = {
                "id": edge_id,
                "source": f"entity:{relation.subject_entity_id}",
                "target": f"entity:{relation.object_entity_id}",
                "type": "related_to",
                "label": str(relation.predicate or "related_to"),
                "confidence": relation.confidence,
            }

    return {
        "nodes": sorted(nodes.values(), key=lambda node: (node["type"], node["label"], node["id"])),
        "edges": sorted(edges.values(), key=lambda edge: (edge["type"], edge["source"], edge["target"], edge["id"])),
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
        governance_status=KnowledgeGovernanceStatus.PERSONAL.value,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    policy = KnowledgeAccessPolicy(db)
    return _kb_response(topic, actor, policy)


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
    policy = KnowledgeAccessPolicy(db)
    all_topics = policy.list_visible_topics(actor)
    all_topics.sort(key=lambda t: (t.created_at, t.kb_uid), reverse=True)

    if cursor:
        cursor_idx = next((i for i, t in enumerate(all_topics) if t.kb_uid == cursor), -1)
        if cursor_idx >= 0:
            all_topics = all_topics[cursor_idx + 1:]

    has_more = len(all_topics) > limit
    items = all_topics[:limit]
    next_cursor = items[-1].kb_uid if has_more and items else None
    return KnowledgeBaseListResponse(
        items=[_kb_response(t, actor, policy) for t in items],
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


# ---------------------------------------------------------------------------
# Admin transfer-request routes (registered before /{kb_uid} to avoid
# FastAPI treating "admin" as a kb_uid value).
# ---------------------------------------------------------------------------


@router.get("/admin/transfer-requests")
def list_transfer_requests(
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    if not policy.is_team_admin(actor):
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Admin access required")
    topics = (
        db.query(KnowledgeTopic)
        .filter_by(
            tenant_id=actor.tenant_id,
            governance_status=KnowledgeGovernanceStatus.PENDING_TRANSFER.value,
            deleted_at=None,
        )
        .all()
    )
    return {
        "items": [_kb_response(t, actor, policy) for t in topics],
        "total": len(topics),
    }


@router.post("/admin/transfer-requests/{kb_uid}/accept", response_model=KnowledgeBaseResponse)
def accept_transfer_request(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        topic = accept_transfer(db, actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    policy = KnowledgeAccessPolicy(db)
    return _kb_response(topic, actor, policy)


@router.post("/admin/transfer-requests/{kb_uid}/reject", response_model=KnowledgeBaseResponse)
def reject_transfer_request(
    kb_uid: str,
    body: TransferRejectRequest | None = None,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        topic = reject_transfer(db, actor, kb_uid, reason=body.reason if body else None)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    policy = KnowledgeAccessPolicy(db)
    return _kb_response(topic, actor, policy)


@router.get("/{kb_uid}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    try:
        topic = policy.require_read(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    return _kb_response(topic, actor, policy)


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

    if not payload["nodes"] and scoped_file_uids:
        try:
            payload = _mysql_entity_graph_fallback(
                db,
                tenant_id=topic.tenant_id,
                kb_uid=topic.kb_uid,
                graph_generation=topic.active_graph_generation,
                view=view,
                file_uids=scoped_file_uids,
                limit=limit,
            )
        except Exception:
            logger.exception("MySQL entity graph fallback failed for kb=%s", kb_uid)
            payload = {"nodes": [], "edges": []}

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
    policy = KnowledgeAccessPolicy(db)
    try:
        topic = policy.require_edit(actor, kb_uid)
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
    return _kb_response(topic, actor, policy)


@router.delete("/{kb_uid}", status_code=200, response_model=KnowledgeBaseResponse)
def delete_knowledge_base(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    try:
        policy.require_delete(actor, kb_uid)
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
    return _kb_response(topic, actor, policy)


# ---------------------------------------------------------------------------
# Transfer-request routes (owner-initiated)
# ---------------------------------------------------------------------------


@router.post("/{kb_uid}/transfer-request", response_model=KnowledgeBaseResponse)
def create_transfer_request(
    kb_uid: str,
    body: TransferRequestCreate | None = None,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        topic = request_transfer(
            db, actor, kb_uid,
            message=body.message if body else None,
        )
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    policy = KnowledgeAccessPolicy(db)
    return _kb_response(topic, actor, policy)


@router.delete("/{kb_uid}/transfer-request", response_model=KnowledgeBaseResponse)
def withdraw_transfer_request(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        topic = withdraw_transfer(db, actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    policy = KnowledgeAccessPolicy(db)
    return _kb_response(topic, actor, policy)


# ---------------------------------------------------------------------------
# Membership management routes
# ---------------------------------------------------------------------------


@router.get("/{kb_uid}/members")
def list_kb_members(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        memberships = list_memberships(db, actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    return {
        "items": [MembershipResponse.model_validate(m).model_dump() for m in memberships],
        "total": len(memberships),
    }


@router.put("/{kb_uid}/members/{user_id}", response_model=MembershipResponse)
def upsert_kb_member(
    kb_uid: str,
    user_id: str,
    body: MembershipUpdate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        membership = upsert_membership(db, actor, kb_uid, user_id, body.role)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    except ValueError as exc:
        raise ApiProblem(400, "INVALID_ROLE", str(exc))
    return membership


@router.delete("/{kb_uid}/members/{user_id}")
def remove_kb_member(
    kb_uid: str,
    user_id: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        remove_membership(db, actor, kb_uid, user_id)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    return {"detail": "deleted"}
