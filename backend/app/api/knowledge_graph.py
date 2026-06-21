from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.asset import PersonalAssetItem, PersonalAssetUnit
from ..models.knowledge_governance import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    PKUCanonicalLink,
    PKURelation,
    PersonalKnowledgeUnit,
)
from ..models.knowledge_item import KnowledgeChunk, KnowledgeItem


router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])
DEFAULT_USER_ID = "default-user"


class KnowledgeGraphNodeUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    statement: Optional[str] = None
    normalized_statement: Optional[str] = None
    summary: Optional[str] = None
    text: Optional[str] = None
    canonical_type: Optional[str] = Field(default=None, max_length=64)
    unit_type: Optional[str] = Field(default=None, max_length=64)
    modality: Optional[str] = Field(default=None, max_length=64)
    source_platform: Optional[str] = Field(default=None, max_length=128)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    media_type: Optional[str] = Field(default=None, max_length=64)
    asset_kind: Optional[str] = Field(default=None, max_length=64)
    category: Optional[str] = Field(default=None, max_length=128)
    status: Optional[str] = Field(default=None, max_length=32)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    tags: Optional[list[str]] = None
    keywords: Optional[list[str]] = None


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


def _asset_confidence(asset: PersonalAssetItem) -> float | None:
    if isinstance(asset.confidence, dict):
        value = asset.confidence.get("overall")
        return value if isinstance(value, (int, float)) else None
    return None


def _ckp_topic_level(canonical: CanonicalKnowledgePoint) -> str:
    extra_meta = canonical.extra_meta if isinstance(canonical.extra_meta, dict) else {}
    topic_level = extra_meta.get("topic_level")
    return topic_level if topic_level in {"parent", "child"} else "child"


def _serialize_canonical(canonical: CanonicalKnowledgePoint) -> dict[str, Any]:
    return _node(
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
        topic_level=_ckp_topic_level(canonical),
    )


def _serialize_pku(pku: PersonalKnowledgeUnit) -> dict[str, Any]:
    return _node(
        f"pku:{pku.id}",
        "pku",
        pku.normalized_statement or pku.statement,
        ref_id=pku.id,
        statement=pku.statement,
        normalized_statement=pku.normalized_statement,
        unit_type=pku.unit_type,
        modality=pku.modality,
        source_kind=pku.source_kind,
        source_id=pku.source_id,
        status=pku.status,
        confidence=pku.confidence,
        keywords=pku.keywords or [],
    )


def _serialize_asset(asset: PersonalAssetItem) -> dict[str, Any]:
    return _node(
        f"asset:{asset.id}",
        "asset",
        asset.title,
        ref_id=asset.id,
        text=asset.rewritten_content or asset.body,
        summary=asset.summary,
        asset_kind=asset.asset_kind,
        source_kind="personal_asset_item",
        source_platform=asset.source_platform,
        source_url=asset.source_url,
        media_type=asset.media_type,
        category=asset.category,
        tags=asset.tags or [],
        confidence=_asset_confidence(asset),
    )


def _serialize_chunk(db: Session, chunk: KnowledgeChunk) -> dict[str, Any]:
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


def _serialize_asset_unit(unit: PersonalAssetUnit) -> dict[str, Any]:
    return _node(
        f"asset_unit:{unit.id}",
        "personal_asset_unit",
        unit.title,
        ref_id=unit.id,
        text=unit.content,
        summary=unit.summary,
        source_kind="personal_asset_unit",
        category=unit.category,
        tags=unit.tags or [],
        status=unit.status,
        source_asset_ids=unit.source_asset_ids or [],
    )


def _source_node_for_pku(db: Session, pku: PersonalKnowledgeUnit) -> dict[str, Any] | None:
    if pku.source_kind == "personal_asset_item":
        asset = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == pku.source_id).first()
        return _serialize_asset(asset) if asset else None

    if pku.source_kind == "personal_asset_unit":
        unit = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.id == pku.source_id).first()
        return _serialize_asset_unit(unit) if unit else None

    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        return _serialize_chunk(db, chunk) if chunk else None

    return None


def _workbench_ckp_node(canonical: CanonicalKnowledgePoint, pku_count: int, source_count: int) -> dict[str, Any]:
    node = _serialize_canonical(canonical)
    node["pku_count"] = pku_count
    node["source_count"] = source_count
    return node


def _source_edge_for_pku(pku: PersonalKnowledgeUnit) -> dict[str, Any] | None:
    source_prefixes = {
        "document_chunk": "chunk",
        "personal_asset_item": "asset",
        "personal_asset_unit": "asset_unit",
    }
    source_prefix = source_prefixes.get(pku.source_kind)
    if not source_prefix:
        return None

    source_node_id = f"{source_prefix}:{pku.source_id}"
    pku_node_id = f"pku:{pku.id}"
    edge_id = f"edge:source:{pku.id}:{source_node_id}"
    return _edge(
        edge_id,
        pku_node_id,
        source_node_id,
        "pku_source",
        pku.source_kind,
        source_kind=pku.source_kind,
        source_id=pku.source_id,
    )


def _canonical_relation_edge(relation: CanonicalRelation, parent_to_child: bool = True) -> dict[str, Any]:
    if parent_to_child:
        source_id = f"ckp:{relation.target_canonical_id}"
        target_id = f"ckp:{relation.source_canonical_id}"
    else:
        source_id = f"ckp:{relation.source_canonical_id}"
        target_id = f"ckp:{relation.target_canonical_id}"

    return _edge(
        f"edge:canonical_relation:{relation.id}",
        source_id,
        target_id,
        "canonical_relation",
        relation.relation_type,
        confidence=relation.confidence,
        reason=relation.reason,
    )


@router.get("/workbench")
def get_knowledge_graph_workbench(
    q: Optional[str] = Query(None),
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(CanonicalKnowledgePoint).filter(
        CanonicalKnowledgePoint.user_id == DEFAULT_USER_ID,
        CanonicalKnowledgePoint.status != "deprecated",
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                CanonicalKnowledgePoint.title.like(like),
                CanonicalKnowledgePoint.canonical_statement.like(like),
                CanonicalKnowledgePoint.summary.like(like),
            )
        )

    canonicals = query.order_by(CanonicalKnowledgePoint.updated_at.desc()).limit(limit).all()
    if not canonicals:
        return {
            "ckps": [],
            "groups": {},
            "parents": [],
            "parent_groups": {},
            "stats": {
                "ckp_count": 0,
                "pku_count": 0,
                "source_count": 0,
            },
        }

    canonical_ids = [canonical.id for canonical in canonicals]
    groups: dict[str, dict[str, Any]] = {
        f"ckp:{canonical.id}": {
            "ckp": _serialize_canonical(canonical),
            "pkus": [],
            "relations": [],
        }
        for canonical in canonicals
    }
    group_pku_ids: dict[str, set[str]] = {f"ckp:{canonical.id}": set() for canonical in canonicals}
    group_source_ids: dict[str, set[str]] = {f"ckp:{canonical.id}": set() for canonical in canonicals}
    all_pku_ids: set[str] = set()
    all_source_ids: set[str] = set()

    links = (
        db.query(PKUCanonicalLink)
        .filter(
            PKUCanonicalLink.user_id == DEFAULT_USER_ID,
            PKUCanonicalLink.canonical_id.in_(canonical_ids),
        )
        .order_by(PKUCanonicalLink.confidence.desc(), PKUCanonicalLink.created_at.desc())
        .limit(limit * 12)
        .all()
    )

    for link in links:
        pku = link.pku
        if not pku or pku.status != "active":
            continue

        canonical_node_id = f"ckp:{link.canonical_id}"
        if canonical_node_id not in groups:
            continue

        pku_node_id = f"pku:{pku.id}"
        link_edge_id = f"edge:{link.id}"
        sources = []
        source_node = _source_node_for_pku(db, pku)
        source_edge = _source_edge_for_pku(pku)
        if source_node and source_edge:
            sources.append({"node": source_node, "edge": source_edge})
            group_source_ids[canonical_node_id].add(source_node["id"])
            all_source_ids.add(source_node["id"])

        groups[canonical_node_id]["pkus"].append(
            {
                "pku": _serialize_pku(pku),
                "link": _edge(
                    link_edge_id,
                    canonical_node_id,
                    pku_node_id,
                    "canonical_pku",
                    link.relation_type,
                    role=link.role,
                    confidence=link.confidence,
                    reason=link.reason,
                ),
                "sources": sources,
            }
        )
        group_pku_ids[canonical_node_id].add(pku.id)
        all_pku_ids.add(pku.id)

    if all_pku_ids:
        pku_relations = (
            db.query(PKURelation)
            .filter(
                PKURelation.user_id == DEFAULT_USER_ID,
                PKURelation.source_pku_id.in_(all_pku_ids),
                PKURelation.target_pku_id.in_(all_pku_ids),
            )
            .order_by(PKURelation.confidence.desc(), PKURelation.created_at.desc())
            .limit(limit * 12)
            .all()
        )
        for relation in pku_relations:
            if relation.source_pku_id not in all_pku_ids or relation.target_pku_id not in all_pku_ids:
                continue
            relation_edge = _edge(
                f"edge:pku_relation:{relation.id}",
                f"pku:{relation.source_pku_id}",
                f"pku:{relation.target_pku_id}",
                "pku_relation",
                relation.relation_type,
                confidence=relation.confidence,
                reason=relation.reason,
                source_kind=relation.source_kind,
                source_id=relation.source_id,
                llm_model=relation.llm_model,
            )
            for ckp_node_id, pku_ids in group_pku_ids.items():
                if relation.source_pku_id in pku_ids and relation.target_pku_id in pku_ids:
                    groups[ckp_node_id]["relations"].append(relation_edge)

    ckps = []
    for canonical in canonicals:
        ckp_node_id = f"ckp:{canonical.id}"
        ckp_node = _workbench_ckp_node(
            canonical,
            pku_count=len(group_pku_ids[ckp_node_id]),
            source_count=len(group_source_ids[ckp_node_id]),
        )
        groups[ckp_node_id]["ckp"] = ckp_node
        ckps.append(ckp_node)

    relations = (
        db.query(CanonicalRelation)
        .filter(
            CanonicalRelation.user_id == DEFAULT_USER_ID,
            CanonicalRelation.relation_type == "subtopic_of",
            CanonicalRelation.source_canonical_id.in_(canonical_ids),
        )
        .order_by(CanonicalRelation.confidence.desc(), CanonicalRelation.created_at.desc())
        .all()
    )
    child_to_relation = {relation.source_canonical_id: relation for relation in relations}
    parent_ids_with_children = {
        row[0]
        for row in db.query(CanonicalRelation.target_canonical_id)
        .filter(
            CanonicalRelation.user_id == DEFAULT_USER_ID,
            CanonicalRelation.relation_type == "subtopic_of",
            CanonicalRelation.target_canonical_id.in_(canonical_ids),
        )
        .distinct()
        .all()
    }
    parent_ids = {relation.target_canonical_id for relation in relations}
    parents_by_id = (
        {
            parent.id: parent
            for parent in db.query(CanonicalKnowledgePoint)
            .filter(
                CanonicalKnowledgePoint.user_id == DEFAULT_USER_ID,
                CanonicalKnowledgePoint.id.in_(parent_ids),
                CanonicalKnowledgePoint.status != "deprecated",
            )
            .all()
        }
        if parent_ids
        else {}
    )
    parent_groups: dict[str, dict[str, Any]] = {}
    parent_order: list[str] = []

    def ensure_parent_group(parent_node: dict[str, Any]) -> dict[str, Any]:
        parent_node_id = parent_node["id"]
        if parent_node_id not in parent_groups:
            parent_groups[parent_node_id] = {
                "parent": parent_node,
                "children": [],
                "stats": {
                    "child_count": 0,
                    "pku_count": 0,
                    "source_count": 0,
                },
            }
            parent_order.append(parent_node_id)
        return parent_groups[parent_node_id]

    for canonical in canonicals:
        child_node_id = f"ckp:{canonical.id}"
        relation = child_to_relation.get(canonical.id)
        parent = parents_by_id.get(relation.target_canonical_id) if relation else None
        if parent:
            parent_node = _serialize_canonical(parent)
            parent_link = _canonical_relation_edge(relation)
        else:
            if canonical.id in parent_ids_with_children:
                ensure_parent_group(dict(groups[child_node_id]["ckp"]))
                continue
            parent_node = dict(groups[child_node_id]["ckp"])
            parent_link = None

        parent_group = ensure_parent_group(parent_node)
        parent_group["children"].append(
            {
                **groups[child_node_id],
                "parent_link": parent_link,
            }
        )

    parents = []
    for parent_node_id in parent_order:
        parent_group = parent_groups[parent_node_id]
        child_count = len(parent_group["children"])
        pku_ids = {
            entry["pku"]["ref_id"]
            for child in parent_group["children"]
            for entry in child["pkus"]
            if entry["pku"].get("ref_id")
        }
        source_ids = {
            source["node"]["id"]
            for child in parent_group["children"]
            for entry in child["pkus"]
            for source in entry["sources"]
        }
        stats = {
            "child_count": child_count,
            "pku_count": len(pku_ids),
            "source_count": len(source_ids),
        }
        parent_group["stats"] = stats
        parent_group["parent"]["child_count"] = child_count
        parent_group["parent"]["pku_count"] = len(pku_ids)
        parent_group["parent"]["source_count"] = len(source_ids)
        parents.append(parent_group["parent"])

    return {
        "ckps": ckps,
        "groups": groups,
        "parents": parents,
        "parent_groups": parent_groups,
        "stats": {
            "ckp_count": len(ckps),
            "pku_count": len(all_pku_ids),
            "source_count": len(all_source_ids),
        },
    }


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
        nodes[f"ckp:{canonical.id}"] = _serialize_canonical(canonical)

    for link in links:
        pku = link.pku
        if not pku or pku.status != "active":
            continue
        pku_node_id = f"pku:{pku.id}"
        canonical_node_id = f"ckp:{link.canonical_id}"
        nodes[pku_node_id] = _serialize_pku(pku)
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

    graph_pku_ids = [
        node["ref_id"]
        for node in nodes.values()
        if node.get("type") == "pku" and node.get("ref_id")
    ]
    if graph_pku_ids:
        pku_relations = (
            db.query(PKURelation)
            .filter(
                PKURelation.user_id == DEFAULT_USER_ID,
                PKURelation.source_pku_id.in_(graph_pku_ids),
                PKURelation.target_pku_id.in_(graph_pku_ids),
            )
            .order_by(PKURelation.confidence.desc())
            .limit(limit * 8)
            .all()
        )
        for relation in pku_relations:
            source_id = f"pku:{relation.source_pku_id}"
            target_id = f"pku:{relation.target_pku_id}"
            if source_id not in nodes or target_id not in nodes:
                continue
            edge_id = f"edge:pku_relation:{relation.id}"
            edges[edge_id] = _edge(
                edge_id,
                source_id,
                target_id,
                "pku_relation",
                relation.relation_type,
                confidence=relation.confidence,
                reason=relation.reason,
                source_kind=relation.source_kind,
                source_id=relation.source_id,
                llm_model=relation.llm_model,
            )

    graph_canonical_ids = [
        node["ref_id"]
        for node in nodes.values()
        if node.get("type") == "canonical" and node.get("ref_id")
    ]
    if graph_canonical_ids:
        canonical_relations = (
            db.query(CanonicalRelation)
            .filter(
                CanonicalRelation.user_id == DEFAULT_USER_ID,
                CanonicalRelation.relation_type == "subtopic_of",
                or_(
                    CanonicalRelation.source_canonical_id.in_(graph_canonical_ids),
                    CanonicalRelation.target_canonical_id.in_(graph_canonical_ids),
                ),
            )
            .order_by(CanonicalRelation.confidence.desc(), CanonicalRelation.created_at.desc())
            .limit(limit * 4)
            .all()
        )
        related_canonical_ids = {
            canonical_id
            for relation in canonical_relations
            for canonical_id in [relation.source_canonical_id, relation.target_canonical_id]
        }
        missing_canonical_ids = [
            canonical_id
            for canonical_id in related_canonical_ids
            if f"ckp:{canonical_id}" not in nodes
        ]
        if missing_canonical_ids:
            missing_canonicals = (
                db.query(CanonicalKnowledgePoint)
                .filter(
                    CanonicalKnowledgePoint.user_id == DEFAULT_USER_ID,
                    CanonicalKnowledgePoint.id.in_(missing_canonical_ids),
                    CanonicalKnowledgePoint.status != "deprecated",
                )
                .all()
            )
            for canonical in missing_canonicals:
                nodes[f"ckp:{canonical.id}"] = _serialize_canonical(canonical)

        for relation in canonical_relations:
            source_id = f"ckp:{relation.target_canonical_id}"
            target_id = f"ckp:{relation.source_canonical_id}"
            if source_id not in nodes or target_id not in nodes:
                continue
            edge_id = f"edge:canonical_relation:{relation.id}"
            edges[edge_id] = _canonical_relation_edge(relation)

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


@router.patch("/nodes/{node_id:path}")
def update_knowledge_graph_node(
    node_id: str,
    update: KnowledgeGraphNodeUpdate,
    db: Session = Depends(get_db),
):
    if ":" not in node_id:
        raise HTTPException(status_code=400, detail="Invalid graph node id")

    node_type, ref_id = node_id.split(":", 1)
    data = update.model_dump(exclude_unset=True)

    if node_type == "ckp":
        canonical = (
            db.query(CanonicalKnowledgePoint)
            .filter(CanonicalKnowledgePoint.id == ref_id, CanonicalKnowledgePoint.user_id == DEFAULT_USER_ID)
            .first()
        )
        if not canonical:
            raise HTTPException(status_code=404, detail="Canonical knowledge point not found")
        if data.get("label") is not None:
            canonical.title = data["label"]
        if data.get("statement") is not None:
            canonical.canonical_statement = data["statement"]
        if "summary" in data:
            canonical.summary = data["summary"]
        if data.get("canonical_type") is not None:
            canonical.canonical_type = data["canonical_type"]
        if data.get("status") is not None:
            canonical.status = data["status"]
        if "confidence" in data:
            canonical.confidence = data["confidence"]
        if data.get("keywords") is not None:
            canonical.keywords = data["keywords"]
        db.commit()
        db.refresh(canonical)
        return _serialize_canonical(canonical)

    if node_type == "pku":
        pku = (
            db.query(PersonalKnowledgeUnit)
            .filter(PersonalKnowledgeUnit.id == ref_id, PersonalKnowledgeUnit.user_id == DEFAULT_USER_ID)
            .first()
        )
        if not pku:
            raise HTTPException(status_code=404, detail="Personal knowledge unit not found")
        if data.get("label") is not None:
            pku.normalized_statement = data["label"]
        if data.get("statement") is not None:
            pku.statement = data["statement"]
        if data.get("normalized_statement") is not None:
            pku.normalized_statement = data["normalized_statement"]
        if data.get("unit_type") is not None:
            pku.unit_type = data["unit_type"]
        if data.get("modality") is not None:
            pku.modality = data["modality"]
        if data.get("status") is not None:
            pku.status = data["status"]
        if "confidence" in data:
            pku.confidence = data["confidence"]
        if data.get("keywords") is not None:
            pku.keywords = data["keywords"]
        db.commit()
        db.refresh(pku)
        return _serialize_pku(pku)

    if node_type == "asset":
        asset = (
            db.query(PersonalAssetItem)
            .filter(PersonalAssetItem.id == ref_id, PersonalAssetItem.user_id == DEFAULT_USER_ID)
            .first()
        )
        if not asset:
            raise HTTPException(status_code=404, detail="Personal asset item not found")
        if data.get("label") is not None:
            asset.title = data["label"]
        if "text" in data:
            asset.rewritten_content = data["text"]
        if "summary" in data:
            asset.summary = data["summary"]
        if data.get("asset_kind") is not None:
            asset.asset_kind = data["asset_kind"]
        if "category" in data:
            asset.category = data["category"] or ""
        if data.get("tags") is not None:
            asset.tags = data["tags"]
        if "source_platform" in data:
            asset.source_platform = data["source_platform"] or ""
        if "source_url" in data:
            asset.source_url = data["source_url"] or ""
        if data.get("media_type") is not None:
            asset.media_type = data["media_type"]
        if data.get("status") is not None:
            asset.status = data["status"]
        if data.get("confidence") is not None:
            confidence = dict(asset.confidence or {})
            confidence["overall"] = data["confidence"]
            asset.confidence = confidence
        db.commit()
        db.refresh(asset)
        return _serialize_asset(asset)

    if node_type == "asset_unit":
        unit = (
            db.query(PersonalAssetUnit)
            .filter(PersonalAssetUnit.id == ref_id, PersonalAssetUnit.user_id == DEFAULT_USER_ID)
            .first()
        )
        if not unit:
            raise HTTPException(status_code=404, detail="Personal asset unit not found")
        if data.get("label") is not None:
            unit.title = data["label"]
        if "text" in data:
            unit.content = data["text"]
        if "summary" in data:
            unit.summary = data["summary"]
        if "category" in data:
            unit.category = data["category"] or ""
        if data.get("tags") is not None:
            unit.tags = data["tags"]
        if data.get("status") is not None:
            unit.status = data["status"]
        db.commit()
        db.refresh(unit)
        return _serialize_asset_unit(unit)

    if node_type == "chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == ref_id).first()
        if not chunk:
            raise HTTPException(status_code=404, detail="Document chunk not found")
        item = (
            db.query(KnowledgeItem)
            .filter(KnowledgeItem.id == chunk.item_id, KnowledgeItem.user_id == DEFAULT_USER_ID)
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="Document item not found")
        if data.get("label") is not None:
            item.title = data["label"]
        if data.get("text") is not None:
            chunk.chunk_text = data["text"]
        if "category" in data:
            item.category = data["category"] or ""
        if data.get("tags") is not None:
            item.tags = data["tags"]
        db.commit()
        db.refresh(chunk)
        return _serialize_chunk(db, chunk)

    raise HTTPException(status_code=400, detail="Unsupported graph node type")
