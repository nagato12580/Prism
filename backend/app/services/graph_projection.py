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


def _source_node_for_pku(db, pku: PersonalKnowledgeUnit, user_id: str) -> dict:
    item_id = pku.source_id
    title = pku.source_id

    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        if chunk:
            item_id = chunk.item_id
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
        "source_kind": pku.source_kind,
        "source_id": pku.source_id,
        "item_id": item_id,
        "title": title,
    }


def _source_node_for_mention(db, mention: EntityMention, user_id: str) -> dict:
    item_id = mention.item_id or mention.source_id
    title = mention.item_id or mention.source_id

    if mention.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == mention.source_id).first()
        if chunk:
            item_id = chunk.item_id
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
        "source_kind": mention.source_kind,
        "source_id": mention.source_id,
        "item_id": item_id,
        "title": title,
    }


def _relation_props(model, names):
    return {name: getattr(model, name) for name in names}
