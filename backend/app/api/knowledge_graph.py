from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.asset import PersonalAssetItem
from ..models.knowledge_governance import CanonicalKnowledgePoint, PKUCanonicalLink, PersonalKnowledgeUnit
from ..models.knowledge_item import KnowledgeChunk, KnowledgeItem


router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])
DEFAULT_USER_ID = "default-user"


def _node(node_id: str, node_type: str, label: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "label": label or "未命名",
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


def _source_node_for_pku(db: Session, pku: PersonalKnowledgeUnit) -> dict[str, Any] | None:
    if pku.source_kind == "personal_asset_item":
        asset = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == pku.source_id).first()
        if not asset:
            return None
        return _node(
            f"asset:{asset.id}",
            "asset",
            asset.title,
            ref_id=asset.id,
            summary=asset.summary,
            source_kind="personal_asset_item",
            source_platform=asset.source_platform,
            category=asset.category,
            tags=asset.tags or [],
        )

    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        if not chunk:
            return None
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == chunk.item_id).first()
        title = item.title if item else "文档片段"
        return _node(
            f"chunk:{chunk.id}",
            "document_chunk",
            title,
            ref_id=chunk.id,
            item_id=chunk.item_id,
            text=chunk.chunk_text,
            source_kind="document_chunk",
            chunk_type=chunk.chunk_type,
            category=item.category if item else "",
            tags=item.tags if item else [],
        )
    return None


@router.get("")
def get_knowledge_graph(
    q: Optional[str] = Query(None),
    limit: int = Query(24, ge=1, le=80),
    db: Session = Depends(get_db),
):
    query = db.query(CanonicalKnowledgePoint).filter(
        CanonicalKnowledgePoint.user_id == DEFAULT_USER_ID,
        CanonicalKnowledgePoint.status != "deprecated",
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                CanonicalKnowledgePoint.title.like(like),
                CanonicalKnowledgePoint.canonical_statement.like(like),
                CanonicalKnowledgePoint.summary.like(like),
            )
        )
    canonicals = query.order_by(CanonicalKnowledgePoint.updated_at.desc()).limit(limit).all()
    canonical_ids = [item.id for item in canonicals]
    links = (
        db.query(PKUCanonicalLink)
        .filter(PKUCanonicalLink.canonical_id.in_(canonical_ids))
        .order_by(PKUCanonicalLink.confidence.desc())
        .limit(limit * 8)
        .all()
        if canonical_ids
        else []
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for canonical in canonicals:
        nodes[f"ckp:{canonical.id}"] = _node(
            f"ckp:{canonical.id}",
            "canonical",
            canonical.title,
            ref_id=canonical.id,
            statement=canonical.canonical_statement,
            summary=canonical.summary,
            canonical_type=canonical.canonical_type,
            status=canonical.status,
            confidence=canonical.confidence,
            keywords=canonical.keywords or [],
        )

    for link in links:
        pku = link.pku
        if not pku or pku.status != "active":
            continue
        pku_node_id = f"pku:{pku.id}"
        canonical_node_id = f"ckp:{link.canonical_id}"
        nodes[pku_node_id] = _node(
            pku_node_id,
            "pku",
            pku.normalized_statement or pku.statement,
            ref_id=pku.id,
            statement=pku.statement,
            normalized_statement=pku.normalized_statement,
            unit_type=pku.unit_type,
            modality=pku.modality,
            source_kind=pku.source_kind,
            source_id=pku.source_id,
            confidence=pku.confidence,
            keywords=pku.keywords or [],
        )
        edges[f"edge:{link.id}"] = _edge(
            f"edge:{link.id}",
            canonical_node_id,
            pku_node_id,
            "canonical_pku",
            link.relation_type,
            role=link.role,
            confidence=link.confidence,
        )

        source_node = _source_node_for_pku(db, pku)
        if source_node:
            nodes[source_node["id"]] = source_node
            edge_id = f"edge:source:{pku.id}:{source_node['id']}"
            edges[edge_id] = _edge(
                edge_id,
                pku_node_id,
                source_node["id"],
                "pku_source",
                pku.source_kind,
                source_kind=pku.source_kind,
            )

    node_counts = Counter(node["type"] for node in nodes.values())
    edge_counts = Counter(edge["type"] for edge in edges.values())

    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_counts": dict(node_counts),
            "edge_counts": dict(edge_counts),
        },
    }
