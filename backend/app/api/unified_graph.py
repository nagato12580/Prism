from __future__ import annotations

from collections import Counter
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    EntityMention,
    EntityRelation,
    KnowledgeChunk,
    KnowledgeEntity,
    KnowledgeFile,
    KnowledgeItem,
    KnowledgeTopic,
    PersonalAssetUnit,
)
from ..security.actor import ActorContext, get_actor_context
from ..services.knowledge_access import KnowledgeAccessPolicy
from ..services.graph_client import GraphClient


router = APIRouter(prefix="/unified-graph", tags=["unified-graph"])
DEFAULT_USER_ID = "default-user"
UnifiedGraphView = Literal["entity", "source"]


def _active_graph_scopes(db: Session, actor: ActorContext) -> list[tuple[str, str, str]]:
    rows = [
        (topic.tenant_id, topic.kb_uid, topic.active_graph_generation)
        for topic in KnowledgeAccessPolicy(db).list_visible_topics(actor)
        if topic.active_graph_generation
    ]
    return [
        (tenant_id, kb_uid, generation)
        for tenant_id, kb_uid, generation in rows
        if tenant_id and kb_uid and generation
    ]


def _active_scope_filter(model, scopes: list[tuple[str, str, str]]):
    return or_(
        *[
            (
                (model.tenant_id == tenant_id)
                & (model.kb_uid == kb_uid)
                & (model.graph_generation == generation)
            )
            for tenant_id, kb_uid, generation in scopes
        ]
    )


def _node(node_id: str, node_type: str, label: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "label": label or node_id,
        **extra,
    }


def _edge(edge_id: str, source: str, target: str, edge_type: str, label: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": edge_type,
        "label": label,
        **extra,
    }


def _normalize_query(q: Optional[str]) -> str | None:
    if not q:
        return None
    normalized = q.strip()
    return normalized or None


def _entity_node(entity: KnowledgeEntity) -> dict[str, Any]:
    return _node(
        f"entity:{entity.id}",
        "entity",
        entity.canonical_name,
        ref_id=entity.id,
        entity_type=entity.entity_type,
        normalized_key=entity.normalized_key,
        description=entity.description,
        confidence=entity.confidence,
        status=entity.status,
        tenant_id=entity.tenant_id,
        kb_uid=entity.kb_uid,
        graph_generation=entity.graph_generation,
    )


def _source_lookup(
    db: Session,
    mentions: list[EntityMention],
    user_id: str = DEFAULT_USER_ID,
) -> tuple[dict[str, KnowledgeChunk], dict[str, KnowledgeItem], dict[str, KnowledgeFile], dict[str, KnowledgeTopic], dict[str, PersonalAssetUnit]]:
    chunk_ids = {mention.source_id for mention in mentions if mention.source_kind == "document_chunk"}
    unit_ids = {mention.source_id for mention in mentions if mention.source_kind == "personal_asset_unit"}

    chunks = (
        db.query(KnowledgeChunk)
        .filter(or_(KnowledgeChunk.id.in_(chunk_ids), KnowledgeChunk.chunk_uid.in_(chunk_ids)))
        .all()
        if chunk_ids
        else []
    )
    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    chunk_by_id.update({chunk.chunk_uid: chunk for chunk in chunks})

    item_ids = {chunk.item_id for chunk in chunks if chunk.item_id}
    items = (
        db.query(KnowledgeItem)
        .filter(KnowledgeItem.id.in_(item_ids))
        .all()
        if item_ids
        else []
    )
    item_by_id = {item.id: item for item in items}
    file_uids = {chunk.file_uid for chunk in chunks if chunk.file_uid}
    files = (
        db.query(KnowledgeFile)
        .filter(KnowledgeFile.file_uid.in_(file_uids))
        .all()
        if file_uids
        else []
    )
    file_by_uid = {file_row.file_uid: file_row for file_row in files}
    topic_uids = {chunk.kb_uid for chunk in chunks if chunk.kb_uid}
    topic_uids.update(file_row.kb_uid for file_row in files if file_row.kb_uid)
    topics = (
        db.query(KnowledgeTopic)
        .filter(KnowledgeTopic.kb_uid.in_(topic_uids))
        .all()
        if topic_uids
        else []
    )
    topic_by_uid = {topic.kb_uid: topic for topic in topics}

    units = (
        db.query(PersonalAssetUnit)
        .filter(
            PersonalAssetUnit.id.in_(unit_ids),
            PersonalAssetUnit.user_id == user_id,
        )
        .all()
        if unit_ids
        else []
    )
    unit_by_id = {unit.id: unit for unit in units}

    return chunk_by_id, item_by_id, file_by_uid, topic_by_uid, unit_by_id


def _source_node(
    *,
    source_kind: str,
    source_id: str,
    view: UnifiedGraphView,
    chunk_by_id: dict[str, KnowledgeChunk],
    item_by_id: dict[str, KnowledgeItem],
    file_by_uid: dict[str, KnowledgeFile],
    topic_by_uid: dict[str, KnowledgeTopic],
    unit_by_id: dict[str, PersonalAssetUnit],
) -> dict[str, Any]:
    chunk = chunk_by_id.get(source_id)
    item = item_by_id.get(chunk.item_id) if chunk else None
    file_row = file_by_uid.get(chunk.file_uid) if chunk else None
    topic = topic_by_uid.get(chunk.kb_uid) if chunk else None
    unit = unit_by_id.get(source_id)

    if source_kind == "document_chunk":
        label = (
            file_row.title
            or file_row.original_filename
            if file_row
            else item.title if item and item.title else source_id
        )
        node_type = "document_chunk"
        node_id = f"chunk:{source_id}"
        return _node(
            node_id,
            node_type,
            label,
            ref_id=source_id,
            source_kind=source_kind,
            source_id=source_id,
            item_id=chunk.item_id if chunk else None,
            file_uid=chunk.file_uid if chunk else None,
            kb_uid=chunk.kb_uid if chunk else None,
            tenant_id=chunk.tenant_id if chunk else None,
            graph_generation=chunk.generation if chunk else None,
            knowledge_base=topic.name if topic else None,
            text=chunk.chunk_text if chunk else None,
            chunk_type=chunk.chunk_type if chunk else None,
            category=item.category if item else "",
            tags=item.tags or [] if item else [],
        )

    if source_kind == "personal_asset_unit":
        label = unit.title if unit and unit.title else source_id
        node_type = "personal_asset_unit"
        node_id = f"asset_unit:{source_id}"
        return _node(
            node_id,
            node_type,
            label,
            ref_id=source_id,
            source_kind=source_kind,
            source_id=source_id,
            item_id=source_id,
            text=unit.content if unit else None,
            summary=unit.summary if unit else None,
            category=unit.category if unit else "",
            tags=unit.tags or [] if unit else [],
            status=unit.status if unit else None,
        )

    node_id = f"source:{source_kind}:{source_id}"
    return _node(
        node_id,
        "source",
        source_id,
        ref_id=source_id,
        source_kind=source_kind,
        source_id=source_id,
        item_id=source_id,
    )


def _build_stats(nodes: dict[str, dict[str, Any]], edges: dict[str, dict[str, Any]], view: UnifiedGraphView) -> dict[str, Any]:
    node_counts = Counter(node["type"] for node in nodes.values())
    edge_counts = Counter(edge["type"] for edge in edges.values())

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "entity_count": node_counts.get("entity", 0),
        "source_count": (
            node_counts.get("document_chunk", 0)
            + node_counts.get("personal_asset_unit", 0)
            + node_counts.get("source", 0)
        ),
        "node_counts": dict(node_counts),
        "edge_counts": dict(edge_counts),
    }


def _focused_entities(db: Session, actor: ActorContext, q: str | None, limit: int) -> list[KnowledgeEntity]:
    scopes = _active_graph_scopes(db, actor)
    if not scopes:
        return []

    query = db.query(KnowledgeEntity).filter(
        _active_scope_filter(KnowledgeEntity, scopes),
        KnowledgeEntity.status != "deprecated",
    )

    if q:
        like = f"%{q}%"
        mention_match_ids = db.query(EntityMention.entity_id).filter(
            or_(
                EntityMention.surface_text.like(like),
                EntityMention.evidence_span.like(like),
            )
        )
        relation_subject_ids = db.query(EntityRelation.subject_entity_id).filter(
            or_(
                EntityRelation.predicate.like(like),
                EntityRelation.evidence_span.like(like),
            )
        )
        relation_object_ids = db.query(EntityRelation.object_entity_id).filter(
            EntityRelation.object_entity_id.isnot(None),
            or_(
                EntityRelation.predicate.like(like),
                EntityRelation.evidence_span.like(like),
            ),
        )
        query = query.filter(
            or_(
                KnowledgeEntity.canonical_name.like(like),
                KnowledgeEntity.normalized_key.like(like),
                KnowledgeEntity.entity_type.like(like),
                KnowledgeEntity.description.like(like),
                KnowledgeEntity.id.in_(mention_match_ids),
                KnowledgeEntity.id.in_(relation_subject_ids),
                KnowledgeEntity.id.in_(relation_object_ids),
            )
        )

    return (
        query.order_by(KnowledgeEntity.updated_at.desc(), KnowledgeEntity.created_at.desc())
        .limit(limit)
        .all()
    )


def _empty_payload(view: UnifiedGraphView, q: str | None) -> dict[str, Any]:
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
            "query": q,
        },
    }


@router.get("")
def get_unified_graph(
    view: UnifiedGraphView = Query("entity"),
    q: Optional[str] = Query(None),
    limit: int = Query(120, ge=1, le=1000),
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    normalized_q = _normalize_query(q)
    entities = _focused_entities(db, actor, normalized_q, limit)
    if not entities:
        return _empty_payload(view, normalized_q)

    entity_ids = {entity.id for entity in entities}
    mentions = (
        db.query(EntityMention)
        .filter(EntityMention.entity_id.in_(entity_ids))
        .order_by(EntityMention.created_at.asc())
        .all()
    )
    relations = (
        db.query(EntityRelation)
        .filter(EntityRelation.subject_entity_id.in_(entity_ids))
        .order_by(EntityRelation.created_at.asc())
        .all()
    )

    chunk_by_id, item_by_id, file_by_uid, topic_by_uid, unit_by_id = _source_lookup(db, mentions, user_id=actor.actor_id)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for entity in entities:
        nodes[f"entity:{entity.id}"] = _entity_node(entity)

    for mention in mentions:
        source = _source_node(
            source_kind=mention.source_kind,
            source_id=mention.source_id,
            view=view,
            chunk_by_id=chunk_by_id,
            item_by_id=item_by_id,
            file_by_uid=file_by_uid,
            topic_by_uid=topic_by_uid,
            unit_by_id=unit_by_id,
        )
        nodes[source["id"]] = source

        if view == "entity":
            edge_id = f"edge:mentioned_in:{mention.entity_id}:{mention.source_kind}:{mention.source_id}"
            if edge_id not in edges:
                edges[edge_id] = _edge(
                    edge_id,
                    f"entity:{mention.entity_id}",
                    source["id"],
                    "mentioned_in",
                    "mentioned_in",
                    confidence=mention.confidence,
                    evidence_span=mention.evidence_span,
                    source_kind=mention.source_kind,
                    source_id=mention.source_id,
                )
            continue

        edge_id = f"edge:mentions_entity:{mention.source_kind}:{mention.source_id}:{mention.entity_id}"
        if edge_id not in edges:
            edges[edge_id] = _edge(
                edge_id,
                source["id"],
                f"entity:{mention.entity_id}",
                "mentions_entity",
                "mentions_entity",
                confidence=mention.confidence,
                evidence_span=mention.evidence_span,
                source_kind=mention.source_kind,
                source_id=mention.source_id,
            )

    if view == "entity":
        for relation in relations:
            if not relation.object_entity_id or relation.object_entity_id not in entity_ids:
                continue
            edge_id = f"edge:related_to:{relation.id}"
            edges[edge_id] = _edge(
                edge_id,
                f"entity:{relation.subject_entity_id}",
                f"entity:{relation.object_entity_id}",
                "related_to",
                relation.predicate or "related_to",
                confidence=relation.confidence,
                evidence_span=relation.evidence_span,
                predicate=relation.predicate,
                source_kind=relation.source_kind,
                source_id=relation.source_id,
            )

    ordered_nodes = sorted(nodes.values(), key=lambda node: (node["type"], node["label"], node["id"]))
    ordered_edges = sorted(edges.values(), key=lambda edge: (edge["type"], edge["source"], edge["target"], edge["id"]))

    return {
        "view": view,
        "nodes": ordered_nodes,
        "edges": ordered_edges,
        "stats": _build_stats(nodes, edges, view),
        "focus": {
            "view": view,
            "query": normalized_q,
            "entity_ids": sorted(entity_ids),
        },
    }


def _require_scoped_entity(entity_id: str, actor: ActorContext) -> None:
    """Scoped graph entity ids are prefixed with ``{tenant}:``; reject any that
    are not within the actor's tenant so cross-tenant ids cannot be queried."""
    if not entity_id.startswith(f"{actor.tenant_id}:"):
        raise HTTPException(status_code=404, detail="Entity not found")


@router.get("/path")
def get_unified_graph_path(
    source_entity_id: str,
    target_entity_id: str,
    limit: int = Query(6, ge=1, le=12),
    actor: ActorContext = Depends(get_actor_context),
):
    _require_scoped_entity(source_entity_id, actor)
    _require_scoped_entity(target_entity_id, actor)
    graph = GraphClient()
    try:
        return {
            "paths": graph.entity_path(
                source_entity_id,
                target_entity_id,
                limit=limit,
            )
        }
    finally:
        graph.close()


@router.get("/explain")
def get_unified_graph_explain(
    entity_id: str,
    source_kind: str,
    source_id: str,
    actor: ActorContext = Depends(get_actor_context),
):
    _require_scoped_entity(entity_id, actor)
    graph = GraphClient()
    try:
        return graph.explain_source_link(entity_id, f"{source_kind}:{source_id}") or {}
    finally:
        graph.close()
