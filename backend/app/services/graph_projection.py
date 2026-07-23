from dataclasses import dataclass

from backend.app.models import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    EntityAlias,
    EntityMention,
    EntityRelation,
    KnowledgeEntity,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PKURelation,
    PersonalAssetUnit,
    PersonalKnowledgeUnit,
)


@dataclass
class GraphProjectionResult:
    ckp_count: int = 0
    pku_count: int = 0
    entity_count: int = 0
    alias_count: int = 0
    source_count: int = 0
    relation_count: int = 0


PARENT_TARGET_RELATIONS = {"parent", "part_of", "subtopic_of"}
PARENT_SOURCE_RELATIONS = {"child", "has_child", "includes", "hierarchy"}
ENTITY_RELATION_TYPES = {
    "authored": "AUTHORED",
    "affiliated_with": "AFFILIATED_WITH",
    "educated_at": "EDUCATED_AT",
    "has_email": "HAS_EMAIL",
    "co_author": "CO_AUTHOR",
}


def project_ckp_graph(db, graph, user_id: str = "default-user") -> GraphProjectionResult:
    result = GraphProjectionResult()

    ckps = (
        db.query(CanonicalKnowledgePoint)
        .filter(
            CanonicalKnowledgePoint.user_id == user_id,
            CanonicalKnowledgePoint.status != "deprecated",
        )
        .all()
    )
    active_ckp_ids = {ckp.id for ckp in ckps}
    for ckp in ckps:
        graph.upsert_ckp(
            {
                "id": ckp.id,
                "user_id": ckp.user_id,
                "title": ckp.title,
                "ckp_type": ckp.canonical_type,
                "status": ckp.status,
                "confidence": ckp.confidence,
            }
        )
        result.ckp_count += 1

    pkus = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == user_id,
            PersonalKnowledgeUnit.status != "deprecated",
        )
        .all()
    )
    active_pku_ids = {pku.id for pku in pkus}
    seen_source_ids = set()
    for pku in pkus:
        graph.upsert_pku(
            {
                "id": pku.id,
                "user_id": pku.user_id,
                "unit_type": pku.unit_type,
                "statement_hash": pku.normalized_statement_hash,
                "confidence": pku.confidence,
                "status": pku.status,
            }
        )
        result.pku_count += 1

        source_node = _source_node_for_pku(db, pku, user_id)
        if source_node["id"] not in seen_source_ids:
            graph.upsert_source(source_node)
            seen_source_ids.add(source_node["id"])
            result.source_count += 1
        graph.relate(
            "PKU",
            pku.id,
            "EVIDENCED_BY",
            "Source",
            source_node["id"],
            {"source_kind": pku.source_kind, "source_id": pku.source_id},
        )
        result.relation_count += 1

    ckp_relations = (
        db.query(CanonicalRelation)
        .filter(CanonicalRelation.user_id == user_id)
        .all()
    )
    for relation in ckp_relations:
        if (
            relation.source_canonical_id not in active_ckp_ids
            or relation.target_canonical_id not in active_ckp_ids
        ):
            continue

        props = _relation_props(relation, ["relation_type", "confidence", "reason"])
        if relation.relation_type in PARENT_TARGET_RELATIONS:
            graph.relate(
                "CKP",
                relation.target_canonical_id,
                "HAS_CHILD",
                "CKP",
                relation.source_canonical_id,
                props,
            )
        elif relation.relation_type in PARENT_SOURCE_RELATIONS:
            graph.relate(
                "CKP",
                relation.source_canonical_id,
                "HAS_CHILD",
                "CKP",
                relation.target_canonical_id,
                props,
            )
        else:
            graph.relate(
                "CKP",
                relation.source_canonical_id,
                "RELATED_TO",
                "CKP",
                relation.target_canonical_id,
                props,
            )
        result.relation_count += 1

    links = db.query(PKUCanonicalLink).filter(PKUCanonicalLink.user_id == user_id).all()
    for link in links:
        if link.canonical_id not in active_ckp_ids or link.pku_id not in active_pku_ids:
            continue
        graph.relate(
            "CKP",
            link.canonical_id,
            "SUPPORTED_BY",
            "PKU",
            link.pku_id,
            _relation_props(link, ["relation_type", "role", "confidence", "reason"]),
        )
        result.relation_count += 1

    pku_relations = db.query(PKURelation).filter(PKURelation.user_id == user_id).all()
    for relation in pku_relations:
        if (
            relation.source_pku_id not in active_pku_ids
            or relation.target_pku_id not in active_pku_ids
        ):
            continue
        graph.relate(
            "PKU",
            relation.source_pku_id,
            "RELATED_TO",
            "PKU",
            relation.target_pku_id,
            _relation_props(
                relation,
                ["relation_type", "confidence", "reason", "source_kind", "source_id"],
            ),
        )
        result.relation_count += 1

    return result


def project_entity_graph(db, graph, user_id: str = "default-user") -> GraphProjectionResult:
    result = GraphProjectionResult()

    entities = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.user_id == user_id,
            KnowledgeEntity.status != "deprecated",
        )
        .all()
    )
    active_entity_ids = {entity.id for entity in entities}
    for entity in entities:
        graph.upsert_entity(
            {
                "id": entity.id,
                "user_id": entity.user_id,
                "entity_type": entity.entity_type,
                "canonical_name": entity.canonical_name,
                "normalized_key": entity.normalized_key,
                "status": entity.status,
                "confidence": entity.confidence,
            }
        )
        result.entity_count += 1

    aliases = db.query(EntityAlias).filter(EntityAlias.entity_id.in_(active_entity_ids)).all()
    for alias in aliases:
        graph.upsert_alias(
            {
                "id": alias.id,
                "key": alias.normalized_key,
                "surface_text": alias.alias,
                "entity_id": alias.entity_id,
            }
        )
        result.alias_count += 1
        result.relation_count += 1

    seen_source_ids = set()
    mentions = db.query(EntityMention).filter(EntityMention.entity_id.in_(active_entity_ids)).all()
    for mention in mentions:
        source_node = _source_node_for_mention(db, mention, user_id)
        if source_node["id"] not in seen_source_ids:
            graph.upsert_source(source_node)
            seen_source_ids.add(source_node["id"])
            result.source_count += 1
        graph.relate(
            "Entity",
            mention.entity_id,
            "MENTIONED_IN",
            "Source",
            source_node["id"],
            _relation_props(
                mention,
                [
                    "confidence",
                    "evidence_span",
                    "extraction_method",
                    "source_kind",
                    "source_id",
                ],
            ),
        )
        result.relation_count += 1

    relations = db.query(EntityRelation).filter(EntityRelation.subject_entity_id.in_(active_entity_ids)).all()
    for relation in relations:
        if not relation.object_entity_id or relation.object_entity_id not in active_entity_ids:
            continue
        graph.relate(
            "Entity",
            relation.subject_entity_id,
            ENTITY_RELATION_TYPES.get(relation.predicate, "RELATED_TO"),
            "Entity",
            relation.object_entity_id,
            _relation_props(
                relation,
                [
                    "predicate",
                    "confidence",
                    "evidence_span",
                    "extraction_method",
                    "source_kind",
                    "source_id",
                ],
            ),
        )
        result.relation_count += 1

    return result


def project_asset_unit_entities(db, graph, asset_unit_id: str, user_id: str = "default-user") -> int:
    """Project one PersonalAssetUnit's settled entities to Neo4j."""
    unit = (
        db.query(PersonalAssetUnit)
        .filter(
            PersonalAssetUnit.id == asset_unit_id,
            PersonalAssetUnit.user_id == user_id,
        )
        .one_or_none()
    )
    if unit is None:
        return 0

    mentions = (
        db.query(EntityMention)
        .join(KnowledgeEntity, EntityMention.entity_id == KnowledgeEntity.id)
        .filter(
            EntityMention.source_kind == "personal_asset_unit",
            EntityMention.source_id == asset_unit_id,
            KnowledgeEntity.status != "deprecated",
        )
        .all()
    )
    if not mentions:
        return 0

    source_node = _source_node_for_asset_unit(unit)
    graph.upsert_source(source_node)

    edges = 0
    entity_cache: dict[str, KnowledgeEntity] = {}
    for mention in mentions:
        entity = entity_cache.get(mention.entity_id)
        if entity is None:
            entity = db.query(KnowledgeEntity).filter_by(id=mention.entity_id).one_or_none()
            if entity is None:
                continue
            entity_cache[mention.entity_id] = entity
            graph.upsert_entity(
                {
                    "id": entity.id,
                    "user_id": entity.user_id,
                    "entity_type": entity.entity_type,
                    "canonical_name": entity.canonical_name,
                    "normalized_key": entity.normalized_key,
                    "status": entity.status,
                    "confidence": entity.confidence,
                }
            )

        graph.relate(
            "Entity",
            mention.entity_id,
            "MENTIONED_IN",
            "Source",
            source_node["id"],
            _relation_props(
                mention,
                ["confidence", "evidence_span", "extraction_method", "source_kind", "source_id"],
            ),
        )
        edges += 1

    relations = (
        db.query(EntityRelation)
        .filter(
            EntityRelation.source_kind == "personal_asset_unit",
            EntityRelation.source_id == asset_unit_id,
        )
        .all()
    )
    active_entity_ids = set(entity_cache.keys())
    for relation in relations:
        if not relation.object_entity_id or relation.object_entity_id not in active_entity_ids:
            continue
        graph.relate(
            "Entity",
            relation.subject_entity_id,
            "RELATED_TO",
            "Entity",
            relation.object_entity_id,
            _relation_props(
                relation,
                ["predicate", "confidence", "evidence_span", "extraction_method"],
            ),
        )
        edges += 1

    return edges


def _source_node_for_pku(db, pku: PersonalKnowledgeUnit, user_id: str) -> dict:
    item_id = pku.source_id
    title = pku.source_id
    tenant_id = ""
    kb_uid = ""

    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        if chunk:
            item_id = chunk.item_id
            tenant_id = chunk.tenant_id
            kb_uid = chunk.kb_uid
            item = (
                db.query(KnowledgeItem)
                .filter(
                    KnowledgeItem.id == chunk.item_id,
                    KnowledgeItem.user_id == user_id,
                )
                .first()
            )
            if item and item.title:
                title = item.title

    return {
        "id": f"{pku.source_kind}:{pku.source_id}",
        "tenant_id": tenant_id,
        "kb_uid": kb_uid,
        "source_kind": pku.source_kind,
        "source_id": pku.source_id,
        "item_id": item_id,
        "title": title,
    }


def _source_node_for_mention(db, mention: EntityMention, user_id: str) -> dict:
    item_id = mention.item_id or mention.source_id
    title = mention.item_id or mention.source_id
    tenant_id = ""
    kb_uid = ""

    if mention.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == mention.source_id).first()
        if chunk:
            item_id = chunk.item_id
            tenant_id = chunk.tenant_id
            kb_uid = chunk.kb_uid
            item = (
                db.query(KnowledgeItem)
                .filter(
                    KnowledgeItem.id == chunk.item_id,
                    KnowledgeItem.user_id == user_id,
                )
                .first()
            )
            if item and item.title:
                title = item.title

    return {
        "id": f"{mention.source_kind}:{mention.source_id}",
        "tenant_id": tenant_id,
        "kb_uid": kb_uid,
        "source_kind": mention.source_kind,
        "source_id": mention.source_id,
        "item_id": item_id,
        "title": title,
    }


def _source_node_for_asset_unit(unit: PersonalAssetUnit) -> dict:
    return {
        "id": f"personal_asset_unit:{unit.id}",
        "tenant_id": "",
        "kb_uid": "",
        "source_kind": "personal_asset_unit",
        "source_id": unit.id,
        "item_id": unit.id,
        "title": unit.title or unit.summary or unit.id,
    }


def _relation_props(model, names):
    return {name: getattr(model, name) for name in names}


def project_item_entities(db, graph, item_id: str, user_id: str = "default-user") -> int:
    """Incrementally project one item's entities + mentions to Neo4j.

    Upserts the Source node per chunk, the Entity nodes, and MENTIONED_IN edges.
    Returns the number of edges projected. Scoped to one item (no full reproject).
    """
    edges = 0
    item = db.query(KnowledgeItem).filter_by(id=item_id).one_or_none()
    if item is None:
        return 0

    # Clean this item's previous Source nodes/edges so re-ingest (fresh chunk
    # UUIDs) leaves no zombie Sources. Idempotent: delete then re-project.
    graph.delete_item_sources(item.tenant_id, item.kb_uid, item_id)

    mentions = (
        db.query(EntityMention)
        .join(KnowledgeEntity, EntityMention.entity_id == KnowledgeEntity.id)
        .filter(EntityMention.item_id == item_id, KnowledgeEntity.status != "deprecated")
        .all()
    )
    if not mentions:
        return 0

    entity_cache: dict[str, KnowledgeEntity] = {}
    source_cache: set[str] = set()
    chunk_ids: set[str] = set()
    for mention in mentions:
        entity = entity_cache.get(mention.entity_id)
        if entity is None:
            entity = db.query(KnowledgeEntity).filter_by(id=mention.entity_id).one_or_none()
            if entity is None:
                continue
            entity_cache[mention.entity_id] = entity
            graph.upsert_entity(
                {
                    "id": entity.id,
                    "user_id": entity.user_id,
                    "entity_type": entity.entity_type,
                    "canonical_name": entity.canonical_name,
                    "normalized_key": entity.normalized_key,
                    "status": entity.status,
                    "confidence": entity.confidence,
                }
            )

        source_node = _source_node_for_mention(db, mention, user_id)
        if source_node["id"] not in source_cache:
            graph.upsert_source(source_node)
            source_cache.add(source_node["id"])
        chunk_ids.add(mention.source_id)
        graph.relate(
            "Entity",
            mention.entity_id,
            "MENTIONED_IN",
            "Source",
            source_node["id"],
            _relation_props(
                mention,
                ["confidence", "evidence_span", "extraction_method", "source_kind", "source_id"],
            ),
        )
        edges += 1

    # Project this item's inter-entity relations as RELATED_TO edges.
    if chunk_ids:
        relations = (
            db.query(EntityRelation)
            .filter(EntityRelation.source_kind == "document_chunk", EntityRelation.source_id.in_(chunk_ids))
            .all()
        )
        for relation in relations:
            if not relation.object_entity_id:
                continue
            graph.relate(
                "Entity",
                relation.subject_entity_id,
                "RELATED_TO",
                "Entity",
                relation.object_entity_id,
                _relation_props(
                    relation,
                    ["predicate", "confidence", "evidence_span", "extraction_method"],
                ),
            )
            edges += 1

    return edges
